"""部门接口测试：注册下拉用的公开部门清单（无需登录）。"""
import pytest


@pytest.mark.asyncio
async def test_list_departments(client):
    resp = await client.get("/api/v1/departments")
    assert resp.status_code == 200
    data = resp.json()
    # 至少包含 hr（演示文档所在部门），且每项都有 value/label 字段
    assert any(d["value"] == "hr" for d in data)
    assert all({"value", "label"} <= set(d) for d in data)
