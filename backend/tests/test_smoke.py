"""冒烟测试：验证应用能启动、受保护接口有认证。"""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_documents_requires_auth(client):
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 401
