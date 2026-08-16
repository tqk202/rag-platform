"""回答反馈接口：用户对回答点赞/点踩（同倾向再点取消，异倾向切换）。"""
from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.feedback import FeedbackCreate
from app.services import feedback_service

router = APIRouter(prefix="/chat/messages", tags=["feedback"])


@router.post("/{message_id}/feedback", summary="提交回答反馈")
async def submit_feedback(
    message_id: int, db: DbSession, user: CurrentUser, data: FeedbackCreate
) -> dict:
    return await feedback_service.submit_feedback(db, user, message_id, data.sentiment, data.comment)
