"""任务状态 API — SSE 端点实时推送入库进度。"""

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.deps import job_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}/stream")
async def job_status_stream(job_id: str):
    """SSE 端点：实时推送入库任务的状态和进度。

    前端使用 EventSource 连接此端点，接收以下事件类型：
      - progress: 进度更新（含 status、stage、progress 百分比）
      - completed: 入库成功（含 doc_id）
      - failed: 入库失败（含 error_message）

    连接保持直到任务终态（completed/failed），最长约 10 分钟超时。

    注意：此端点每秒查询一次 PostgreSQL，单个文件入库仅持续数秒，
    总体 DB 负载可忽略。
    """
    if job_repo is None:
        async def err():
            payload = json.dumps(
                {"error_message": "任务仓储不可用"},
                ensure_ascii=False,
            )
            yield f"event: failed\ndata: {payload}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    async def event_generator():
        last_status = ""
        last_stage = ""
        last_progress = -1
        max_ticks = 600  # 600 × 1s = 10 分钟

        for _ in range(max_ticks):
            job = job_repo.get(job_id)
            if job is None:
                payload = json.dumps(
                    {"error_message": f"任务 {job_id} 不存在"},
                    ensure_ascii=False,
                )
                yield f"event: failed\ndata: {payload}\n\n"
                return

            current_status = job.status.value
            current_stage = job.stage
            current_progress = job.progress

            # 只在有变化时推送（status/stage/progress 任一改变即推送）
            if (current_status != last_status
                    or current_stage != last_stage
                    or current_progress != last_progress):
                last_status = current_status
                last_stage = current_stage
                last_progress = current_progress

                payload = json.dumps(
                    {
                        "job_id": job.job_id,
                        "doc_id": job.doc_id,
                        "status": job.status.value,
                        "stage": job.stage,
                        "progress": job.progress,
                    },
                    ensure_ascii=False,
                )
                yield f"event: progress\ndata: {payload}\n\n"

            # 终态 → 推送终态事件 → 关闭连接
            if job.status.value == "completed":
                payload = json.dumps(
                    {"doc_id": job.doc_id, "job_id": job.job_id},
                    ensure_ascii=False,
                )
                yield f"event: completed\ndata: {payload}\n\n"
                return

            if job.status.value == "failed":
                payload = json.dumps(
                    {
                        "doc_id": job.doc_id,
                        "job_id": job.job_id,
                        "error_message": job.error_message,
                    },
                    ensure_ascii=False,
                )
                yield f"event: failed\ndata: {payload}\n\n"
                return

            await asyncio.sleep(1)

        # 超时 → 推送超时事件
        payload = json.dumps(
            {"error_message": "任务超时，请稍后重试"},
            ensure_ascii=False,
        )
        yield f"event: failed\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
