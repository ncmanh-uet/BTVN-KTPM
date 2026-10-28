"""Live checks against Compose; expects the demo user 1 JWT."""
import argparse
import asyncio
import base64

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--token", required=True)
args = parser.parse_args()
headers = {"Authorization": f"Bearer {args.token}"}


async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False) as client:
        await asyncio.sleep(1.1)
        response = await client.get("/dashboard", headers=headers)
        response.raise_for_status()
        assert response.json()["order_count"] == 2
        assert (await client.get("/users/me")).status_code == 401
        response = await client.post("/users/me/avatar-upload-url", headers=headers,
                                     json={"content_type": "image/png"})
        response.raise_for_status()
        grant = response.json()
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
        uploaded = await client.put(grant["upload_url"], content=png, headers=grant["headers"])
        uploaded.raise_for_status()
        assert (await client.get(grant["upload_url"].split("?")[0])).status_code == 403
        await asyncio.sleep(1.1)
        responses = await asyncio.gather(*[client.get("/users/me", headers=headers) for _ in range(11)])
        codes = [r.status_code for r in responses]
        assert codes.count(200) == 10 and codes.count(429) == 1, codes
        print("PASS: dashboard, JWT, MinIO upload/private bucket, 10 requests/s")


asyncio.run(main())
