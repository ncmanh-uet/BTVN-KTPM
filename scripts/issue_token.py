"""Offline demo issuer; never expose as an unauthenticated HTTP endpoint."""
import argparse
import os
from datetime import datetime, timedelta, timezone

import jwt

parser = argparse.ArgumentParser()
parser.add_argument("--user-id", type=int, default=1)
args = parser.parse_args()
now = datetime.now(timezone.utc)
print(jwt.encode({"sub": str(args.user_id), "iat": now, "exp": now+timedelta(hours=1),
                  "iss": "btvn-gateway", "aud": "btvn-api"}, os.environ["JWT_SECRET"], algorithm="HS256"))
