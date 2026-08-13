"""W5 可观测性测试：request_id 全链路追踪。"""
import pytest


@pytest.mark.asyncio
async def test_health_returns_request_id(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    rid = resp.headers.get("x-request-id")
    assert rid and len(rid) >= 8


@pytest.mark.asyncio
async def test_client_supplied_request_id_is_echoed(client):
    """网关/负载均衡传进来的 X-Request-ID 会被透传，分布式追踪的接入口。"""
    resp = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert resp.headers.get("x-request-id") == "trace-abc-123"


@pytest.mark.asyncio
async def test_request_id_is_unique_per_request(client):
    r1 = await client.get("/health")
    r2 = await client.get("/health")
    assert r1.headers.get("x-request-id") != r2.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_error_path_also_carries_request_id(client):
    """401 等异常路径同样有 request_id，坏请求也能按 id 定位。"""
    resp = await client.get("/api/v1/documents")
    assert resp.status_code == 401
    assert resp.headers.get("x-request-id")
