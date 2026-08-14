"""部门接口：注册下拉等公开场景使用，返回配置的部门清单（单一来源）。"""
from fastapi import APIRouter

from app.core.config import DEPARTMENTS

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[dict[str, str]], summary="部门清单")
async def list_departments() -> list[dict[str, str]]:
    return DEPARTMENTS
