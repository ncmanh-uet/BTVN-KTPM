import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("JWT_SECRET", "test-secret-123456789012345678901234567890")
os.environ.setdefault("MINIO_ROOT_USER", "testadmin")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "testpassword")

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from services import gateway, users, orders


def token(**changes):
    now = datetime.now(timezone.utc)
    claims = dict(sub="1", iat=now, exp=now+timedelta(minutes=5),
                  iss=gateway.ISSUER, aud=gateway.AUDIENCE)
    claims.update(changes)
    return {"Authorization": "Bearer "+jwt.encode(claims, gateway.SECRET, algorithm="HS256")}


@pytest.fixture
def client():
    gateway.limiter = gateway.SlidingWindow()
    user_client, order_client = TestClient(users.app), TestClient(orders.app)

    async def handle(request):
        target = user_client if request.url.port == 8001 else order_client
        response = target.get(request.url.raw_path.decode())
        return httpx.Response(response.status_code, json=response.json())

    with TestClient(gateway.app) as client:
        original = gateway.app.state.client
        gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        yield client
        # Mock transport holds no sockets; original is closed by lifespan.
        gateway.app.state.client = original


def test_routing_and_aggregation(client):
    headers = token()
    assert client.get("/users/me", headers=headers).json()["id"] == 1
    assert client.get("/users", headers=headers).json()[0]["id"] == 1
    assert len(client.get("/orders", headers=headers).json()) == 2
    data = client.get("/dashboard", headers=headers).json()
    assert data["user"]["id"] == 1
    assert data["order_count"] == 2
    assert data["total_amount"] == 1000000
    assert client.get("/users/2", headers=headers).status_code == 403
    assert client.get("/users/me", headers=token(sub="999")).status_code == 404


def test_jwt(client):
    assert client.get("/dashboard").status_code == 401
    assert client.get("/dashboard", headers=token(exp=0)).status_code == 401
    assert client.get("/dashboard", headers=token(aud="wrong")).status_code == 401
    assert client.get("/dashboard", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_rate_limit(client):
    statuses = [client.get("/users/me").status_code for _ in range(11)]
    assert statuses == [401]*10+[429]
    window = gateway.SlidingWindow()
    assert all(window.accept(0) for _ in range(10))
    assert not window.accept(0.999)
    assert window.accept(1.0)


def test_valet_key(client):
    response = client.post("/users/me/avatar-upload-url", headers=token(), json={"content_type": "image/png"})
    assert response.status_code == 200
    data = response.json()
    query = parse_qs(urlparse(data["upload_url"]).query)
    assert query["X-Amz-Expires"] == ["300"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]
    assert data["object_key"].startswith("1/")
    assert client.post("/users/me/avatar-upload-url", headers=token(), json={"content_type": "text/html"}).status_code == 422


def test_upstream_failure(client):
    async def fail(request):
        raise httpx.ConnectError("offline")
    gateway.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    assert client.get("/dashboard", headers=token()).status_code == 502
