"""存储对账任务：定时（外部 cron/beat）或手动触发，收敛 Milvus 与 DB 偏差。

P1-1 一致性补偿：外部存储不参与事务，崩溃可能留孤儿向量。对账任务以 DB
为准清理孤儿、报告缺向量，生产可挂 cron 周期跑，也可手动触发管理端点。
"""
import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="documents.reconcile")
def reconcile_task(self, document_id: int) -> None:
    asyncio.run(_run(document_id))


async def _run(document_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.reconcile_service import reconcile_document

    async with AsyncSessionLocal() as db:
        result = await reconcile_document(db, document_id)
        logger.info("对账任务完成：%s", result)
