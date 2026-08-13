"""Celery 应用：文档处理的异步任务队列。"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "rag",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.process_document"],
)

celery_app.conf.task_default_queue = "documents"
# 任务执行完再确认，避免 worker 崩溃丢任务
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
