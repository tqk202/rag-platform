"""文档处理任务：Celery 异步执行，避免阻塞上传接口。

W10 补全重试：W9 只在"在线问答"路径对 HTTP 调用重试；这里是"离线入库"路径。
上传时嵌入接口抖动，任务直接失败会静默卡住文档——所以任务层对瞬时错误
自动重试（复用 W9 的退避策略），永久错误（解析失败等）不重试。

瞬时/永久的分界与 W9 一致：
- 瞬时（值得重试）：嵌入 API 429/5xx（W9 单次调用重试耗尽后的漏网）、
  网络层错误（连接重置、超时）——换几次重跑大概率能成功。
- 永久（不重试）：解析失败、文件格式问题等——重放也必然失败。
"""
import asyncio
import logging

import httpx

from app.core import http_retry
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# 最多总尝试次数（第 1 次 + 最多 2 次重试），与 W9 DEFAULT_ATTEMPTS=3 对齐
MAX_ATTEMPTS = 3


def is_transient(exc: BaseException) -> bool:
    """是否瞬时错误（值得重试）：与 W9 同一套判断（429/5xx 或网络层）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in http_retry.RETRYABLE_STATUS
    if isinstance(exc, httpx.HTTPError):
        return True  # TransportError / RequestError 等网络层瞬时故障
    return isinstance(exc, (ConnectionError, TimeoutError))


@celery_app.task(bind=True, name="documents.process")
def process_document_task(self, document_id: int) -> None:
    try:
        asyncio.run(_run(document_id))
    except Exception as exc:
        if not is_transient(exc):
            # 永久错误：process_document 已标 failed + failure_reason，直接收尾
            logger.warning("文档 %s 永久失败，不重试：%s", document_id, exc)
            raise
        if self.request.retries + 1 >= MAX_ATTEMPTS:
            # 瞬时错误但重试耗尽：保持 failed（原因已由 process_document 落库）
            logger.warning("文档 %s 瞬时错误重试耗尽（%s 次）", document_id, MAX_ATTEMPTS)
            raise
        countdown = http_retry.backoff_delay(
            self.request.retries, http_retry.DEFAULT_BASE, http_retry.DEFAULT_CAP
        )
        logger.warning(
            "文档 %s 瞬时错误，第 %s 次重试，%.2fs 后重跑",
            document_id, self.request.retries + 1, countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _run(document_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.ingestion_service import process_document

    async with AsyncSessionLocal() as db:
        await process_document(db, document_id)
