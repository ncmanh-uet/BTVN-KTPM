import asyncio
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import boto3
import httpx
import jwt
from botocore.config import Config
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

SECRET = os.environ["JWT_SECRET"]
ISSUER = "btvn-gateway"
AUDIENCE = "btvn-api"
USER_URL = os.getenv("USER_SERVICE_URL", "http://127.0.0.1:8001")
ORDER_URL = os.getenv("ORDER_SERVICE_URL", "http://127.0.0.1:8002")
BUCKET = os.getenv("MINIO_BUCKET", "avatars")


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        app.state.client = client
        yield


app = FastAPI(title="API Gateway — BTVN", lifespan=lifespan)
security = HTTPBearer(auto_error=False)


class SlidingWindow:
    def __init__(self, limit=10, window=1.0):
        self.limit, self.window = limit, window
        self.hits = deque()

    def accept(self, now):
        while self.hits and self.hits[0] <= now - self.window:
            self.hits.popleft()
        if len(self.hits) >= self.limit:
            return False
        self.hits.append(now)
        return True


# Global gateway limit; run exactly one worker so all requests share this window.
limiter = SlidingWindow()


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    start = time.perf_counter()
    if request.url.path != "/health" and not limiter.accept(time.monotonic()):
        return JSONResponse({"detail": "Maximum 10 requests per second"}, 429,
                            headers={"Retry-After": "1"})
    response = await call_next(request)
    response.headers["X-Gateway-Time-Ms"] = f"{(time.perf_counter()-start)*1000:.3f}"
    return response


def identity(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    try:
        if credentials is None:
            raise ValueError("Missing token")
        claims = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"],
                            issuer=ISSUER, audience=AUDIENCE,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        user_id = int(claims["sub"])
        if user_id <= 0:
            raise ValueError("Invalid subject")
        return user_id
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired JWT", headers={"WWW-Authenticate": "Bearer"})


async def upstream(url, **params):
    try:
        result = await app.state.client.get(url, params=params)
        result.raise_for_status()
        return result.json()
    except httpx.TimeoutException:
        raise HTTPException(504, "Upstream timeout")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "User not found")
        raise HTTPException(502, "Upstream service error")
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, "Upstream unavailable or invalid response")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users/me")
async def me(user_id: int = Depends(identity)):
    return await upstream(f"{USER_URL}/users/{user_id}")


@app.get("/users")
async def own_users(user_id: int = Depends(identity)):
    return [await upstream(f"{USER_URL}/users/{user_id}")]


@app.get("/users/{requested_id}")
async def user(requested_id: int, user_id: int = Depends(identity)):
    if requested_id != user_id:
        raise HTTPException(403, "Only your own profile is accessible")
    return await upstream(f"{USER_URL}/users/{user_id}")


@app.get("/orders")
async def orders(user_id: int = Depends(identity)):
    return await upstream(f"{ORDER_URL}/orders", user_id=user_id)


@app.get("/dashboard")
async def dashboard(user_id: int = Depends(identity)):
    user, orders = await asyncio.gather(
        upstream(f"{USER_URL}/users/{user_id}"),
        upstream(f"{ORDER_URL}/orders", user_id=user_id),
    )
    return {"user": user, "orders": orders, "order_count": len(orders),
            "total_amount": sum(order["total"] for order in orders)}


class AvatarRequest(BaseModel):
    content_type: str = Field(pattern=r"^image/(png|jpeg|webp)$")


@app.post("/users/me/avatar-upload-url")
def avatar(body: AvatarRequest, user_id: int = Depends(identity)):
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[body.content_type]
    key = f"{user_id}/{uuid4()}.{extension}"
    # Sign the external endpoint directly: rewriting a signed hostname breaks SigV4.
    s3 = boto3.client("s3", endpoint_url=os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000"),
                      aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                      aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
                      region_name="us-east-1",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    url = s3.generate_presigned_url("put_object", Params={"Bucket": BUCKET, "Key": key,
                                   "ContentType": body.content_type}, ExpiresIn=300)
    return {"upload_url": url, "method": "PUT", "expires_in": 300,
            "expires_at": (datetime.now(timezone.utc)+timedelta(seconds=300)).isoformat(),
            "headers": {"Content-Type": body.content_type}, "object_key": key}
