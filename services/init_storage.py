import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

s3 = boto3.client("s3", endpoint_url="http://minio:9000",
                  aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                  aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
                  region_name="us-east-1", config=Config(signature_version="s3v4"))
for attempt in range(30):
    try:
        s3.list_buckets()
        try:
            s3.create_bucket(Bucket="avatars")
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
        print("Private bucket avatars ready")
        break
    except (BotoCoreError, ClientError):
        if attempt == 29:
            raise
        time.sleep(2)
