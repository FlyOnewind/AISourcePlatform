"""入库任务 actor — 异步入库 + 分段进度报告。"""

import logging

import dramatiq

from app.core.models import JobStage, JobStatus

logger = logging.getLogger(__name__)


def _update_job(job_id: str, **kwargs):
    """更新 job 状态字段（判空安全），供 actor 不同阶段调用。"""
    # 延迟导入避免 broker 初始化前的循环依赖
    from app.core.deps import job_repo  # pylint: disable=import-outside-toplevel

    if job_repo is None:
        return
    job = job_repo.get(job_id)
    if job is None:
        return
    for key, value in kwargs.items():
        setattr(job, key, value)
    job_repo.update(job)


@dramatiq.actor(
    max_retries=3,
    min_backoff=15_000,      # 首次重试等待 15 秒
    max_backoff=300_000,     # 重试间隔上限 5 分钟
    time_limit=1_800_000,    # 30 分钟硬超时，超时后 Dramatiq 强制中断
)
def ingest_document(job_id: str, doc_id: str):
    """异步入库 actor。

    分阶段更新 job.stage 和 job.progress，SSE 端点实时推送前端弹条。
    幂等性：ingestion_pipeline.ingest() 内部先清理旧产物再重入。

    Args:
        job_id: 入库任务 ID。
        doc_id: 目标文档 ID。
    """
    # 延迟导入避免 broker 初始化前的循环依赖
    from app.core.deps import document_repo, ingestion_pipeline  # pylint: disable=import-outside-toplevel

    # ── 阶段 0：标记开始 ──
    _update_job(job_id, status=JobStatus.processing, stage=JobStage.PARSING, progress=5)

    # ── 获取文档 ──
    doc = document_repo.get(doc_id) if document_repo else None
    if doc is None:
        _update_job(
            job_id,
            status=JobStatus.failed,
            progress=0,
            error_message=f"文档 {doc_id} 不存在",
        )
        return

    try:
        # ── 进度回调：pipeline 各阶段实时更新 job 进度 ──
        def _on_progress(stage: str, pct: int):
            _update_job(job_id, stage=stage, progress=pct)

        # pipeline.ingest(doc, raw_content=None) 会通过 doc.source_uri 自动从 MinIO 读取文件
        doc = ingestion_pipeline.ingest(
            doc, options={"progress_callback": _on_progress},
        )

        # ingest 成功 → 文档已由 pipeline 标记为 active
        _update_job(
            job_id,
            status=JobStatus.completed,
            stage=JobStage.COMPLETED,
            progress=100,
        )
        logger.info("异步入库完成: doc_id=%s, job_id=%s", doc_id, job_id)

    except Exception:
        import traceback  # pylint: disable=import-outside-toplevel

        error_msg = traceback.format_exc()[-2000:]  # 取尾部最多 2000 字符
        _update_job(
            job_id,
            status=JobStatus.failed,
            stage=JobStage.FAILED,
            progress=0,
            error_message=error_msg[:2000],
        )
        logger.exception("异步入库失败: doc_id=%s, job_id=%s", doc_id, job_id)
        raise  # 抛出异常，让 Dramatiq 根据重试策略决定是否重试
