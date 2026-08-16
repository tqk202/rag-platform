"""导出点踩反馈为候选 badcase，供人工审核后并入黄金评测集。

闭环：用户在问答页点踩 -> 这里把「问题 + 错误回答 + 部门 + 评论」拉成候选 ->
人工审核补 golden_passage（必须能逐字命中 demo 文档原文）-> 并入
eval_data/golden_set.json 的 cases -> 下轮评测自动覆盖该 badcase。

注意：不自动并入评测集——badcase 需要人能核对的「标准答案出处」，只有人才能判
（反馈里的错误回答不能直接当标准答案）。这是「反馈 -> 候选 -> 人工审核 -> 评测集」
的真实工程闭环，不是盲目回灌。

用法（在 backend/ 下）：
  .venv/Scripts/python scripts/export_badcases.py [--out eval_data/feedback_badcases.json]
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.chat import ChatMessage  # noqa: E402
from app.models.feedback import AnswerFeedback  # noqa: E402
from app.models.user import User  # noqa: E402


async def _question_before(db, message_id: int, session_id: int) -> str | None:
    """该回答（assistant 消息）之前最近的一条 user 消息 = 对应问题。"""
    return await db.scalar(
        select(ChatMessage.content)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == "user",
            ChatMessage.id < message_id,
        )
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )


async def main(out_path: str) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    AnswerFeedback, ChatMessage.content, ChatMessage.session_id,
                    User.username, User.department,
                )
                .join(ChatMessage, ChatMessage.id == AnswerFeedback.message_id)
                .join(User, User.id == AnswerFeedback.user_id)
                .where(AnswerFeedback.sentiment == "dislike")
                .order_by(AnswerFeedback.id)
            )
        ).all()

        cases: list[dict] = []
        for fb, answer, session_id, username, department in rows:
            question = await _question_before(db, fb.message_id, session_id)
            cases.append(
                {
                    "id": f"badcase-{fb.id}",
                    "question": question or "",
                    "answer": (answer or "")[:200],
                    "username": username,
                    "department": department,
                    # 以下字段需人工核对后并入 golden_set.json：
                    "knowledge_base": None,  # 需人工补：归属知识库名
                    "doc": None,  # 需人工补：golden_set.json 里的 doc 文件名
                    "golden_passage": None,  # 需人工补：标准答案出处原文（逐字命中）
                    "expect": "answer",
                    "comment": fb.comment,
                }
            )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"count": len(cases), "cases": cases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已导出 {len(cases)} 条点踩 badcase 候选 -> {out}")
    if cases:
        print(
            "下一步：人工审核每条，补 doc + golden_passage 后，"
            "把 case 并入 eval_data/golden_set.json 的 cases 数组"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out", default="eval_data/feedback_badcases.json", help="输出路径"
    )
    args = parser.parse_args()
    asyncio.run(main(args.out))
