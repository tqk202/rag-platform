"""文档处理任务：Celery 异步执行，避免阻塞上传接口。"""
import asyncio

from app.tasks.celery_app import celery_app


@celery_app.task(name="documents.process")
def process_document_task(document_id: int) -> None:
    asyncio.run(_run(document_id))


async def _run(document_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.ingestion_service import process_document

    async with AsyncSessionLocal() as db:
        await process_document(db, document_id)
