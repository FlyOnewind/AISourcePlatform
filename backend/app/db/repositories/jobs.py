"""入库任务仓储 — IngestJob 的 CRUD 和查询操作。"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import IngestJob, JobStatus
from app.db.models import DbIngestJob
from app.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class IngestJobRepository(BaseRepository):
    """入库任务仓储，提供 IngestJob 的 CRUD 和去重查询。"""

    # ── ORM 双向转换 ─────────────────────────────────────────────────

    @staticmethod
    def _to_db(job: IngestJob) -> DbIngestJob:
        """领域模型 → ORM 对象。"""
        return DbIngestJob(
            job_id=job.job_id,
            doc_id=job.doc_id,
            dramatiq_message_id=job.dramatiq_message_id,
            status=job.status.value,
            stage=job.stage,
            progress=job.progress,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @staticmethod
    def _from_db(db_job: DbIngestJob) -> IngestJob:
        """ORM 对象 → 领域模型。"""
        return IngestJob(
            job_id=db_job.job_id,
            doc_id=db_job.doc_id,
            dramatiq_message_id=db_job.dramatiq_message_id or "",
            status=JobStatus(db_job.status),
            stage=db_job.stage or "",
            progress=db_job.progress or 0,
            error_message=db_job.error_message,
            created_at=db_job.created_at,
            updated_at=db_job.updated_at,
        )

    # ── CRUD ─────────────────────────────────────────────────────────

    def create(self, job: IngestJob) -> IngestJob:
        """创建新任务记录。"""
        with self._session() as session:
            session: Session
            db_job = self._to_db(job)
            session.add(db_job)
            session.flush()
            result = self._from_db(db_job)
            session.commit()
            return result

    def get(self, job_id: str) -> IngestJob | None:
        """按 job_id 获取任务。"""
        with self._session() as session:
            session: Session
            db_job = session.get(DbIngestJob, job_id)
            if db_job is None:
                return None
            return self._from_db(db_job)

    def update(self, job: IngestJob) -> IngestJob:
        """更新任务状态、阶段、进度、错误信息等字段。"""
        with self._session() as session:
            session: Session
            db_job = session.get(DbIngestJob, job.job_id)
            if db_job is None:
                raise ValueError(f"任务 {job.job_id} 不存在，无法更新")
            db_job.dramatiq_message_id = job.dramatiq_message_id
            db_job.status = job.status.value
            db_job.stage = job.stage
            db_job.progress = job.progress
            db_job.error_message = job.error_message
            session.flush()
            result = self._from_db(db_job)
            session.commit()
            return result

    def find_active_by_doc_id(self, doc_id: str) -> IngestJob | None:
        """查找与同一文档关联的活跃任务（queued 或 processing），用于去重。"""
        with self._session() as session:
            session: Session
            db_job = (
                session.query(DbIngestJob)
                .filter(
                    DbIngestJob.doc_id == doc_id,
                    DbIngestJob.status.in_(["queued", "processing"]),
                )
                .order_by(DbIngestJob.created_at.desc())
                .first()
            )
            if db_job is None:
                return None
            return self._from_db(db_job)

    def list_by_status(self, status: str) -> list[IngestJob]:
        """列出指定状态的所有任务，供超时恢复使用。"""
        with self._session() as session:
            session: Session
            db_jobs = (
                session.query(DbIngestJob)
                .filter(DbIngestJob.status == status)
                .all()
            )
            return [self._from_db(j) for j in db_jobs]

    def hard_delete(self, job_id: str) -> None:
        """物理删除任务记录（仅用于入队失败回滚）。"""
        with self._session() as session:
            session: Session
            db_job = session.get(DbIngestJob, job_id)
            if db_job is not None:
                session.delete(db_job)
                session.commit()

    def count(self) -> int:
        """获取任务总数。"""
        with self._session() as session:
            session: Session
            return session.query(DbIngestJob).count()
