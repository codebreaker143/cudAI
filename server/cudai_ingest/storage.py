"""
Where uploaded recordings are kept.

- LocalStorage: a directory on the server (development, tests, small pilots).
  The app uploads to this server's own /v1/blob endpoint with signed links.
- S3Storage: any S3-compatible bucket (AWS S3, Cloudflare R2, Google Cloud
  Storage interoperability, MinIO). The app uploads straight to the bucket
  with pre-signed PUT links, so video never passes through this server.

Keys look like recordings/<recording id>/<path>. Each object's SHA-256 is
kept with it (a sidecar file, or x-amz-meta-sha256), so re-uploads can be
skipped and completeness checked.
"""

import hashlib
import hmac
import json
import os
import shutil
import time
from urllib.parse import urlencode


class LocalStorage:
    def __init__(self, root: str, signing_key: bytes):
        self.root = os.path.abspath(root)
        self.signing_key = signing_key
        os.makedirs(self.root, exist_ok=True)

    def path(self, key: str) -> str:
        return os.path.join(self.root, "objects", *key.split("/"))

    def _meta_path(self, key: str) -> str:
        return os.path.join(self.root, "meta", *key.split("/")) + ".sha256"

    def _write(self, path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def sha256(self, key: str) -> str | None:
        try:
            with open(self._meta_path(key), "r") as f:
                return f.read().strip()
        except OSError:
            return None

    def put(self, key: str, data: bytes) -> None:
        self._write(self.path(key), data)
        self._write(self._meta_path(key), hashlib.sha256(data).hexdigest().encode())

    def read_json(self, key: str):
        try:
            with open(self.path(key), "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            return None

    def write_json(self, key: str, data) -> None:
        self.put(key, json.dumps(data, indent=2).encode())

    def download(self, key: str, dest: str) -> None:
        shutil.copyfile(self.path(key), dest)

    def upload_file(self, key: str, src: str) -> None:
        with open(src, "rb") as f:
            self.put(key, f.read())

    def exists(self, key: str) -> bool:
        return os.path.exists(self.path(key))

    def list_ids(self, prefix: str) -> list:
        """Recording ids under prefix/ (e.g. "recordings")."""
        folder = os.path.join(self.root, "objects", prefix)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def delete_prefix(self, prefix: str) -> None:
        for tree in ("objects", "meta"):
            shutil.rmtree(os.path.join(self.root, tree, *prefix.split("/")), ignore_errors=True)

    # Signed upload links ------------------------------------------------------

    def _signature(self, key: str, sha256: str, size: int, expires: int) -> str:
        message = f"{key}\n{sha256}\n{size}\n{expires}".encode()
        return hmac.new(self.signing_key, message, hashlib.sha256).hexdigest()

    def upload_ticket(self, key: str, sha256: str, size: int, ttl: int, base_url: str) -> dict:
        expires = int(time.time()) + ttl
        query = urlencode(
            {
                "key": key,
                "sha256": sha256,
                "size": size,
                "expires": expires,
                "signature": self._signature(key, sha256, size, expires),
            }
        )
        return {
            "method": "PUT",
            "url": f"{base_url.rstrip('/')}/v1/blob?{query}",
            "headers": {"Content-Type": "application/octet-stream"},
        }

    def check_ticket(self, key: str, sha256: str, size: int, expires: int, signature: str) -> bool:
        expected = self._signature(key, sha256, size, expires)
        return expires >= time.time() and hmac.compare_digest(expected, signature)


class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None = None, region: str | None = None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            config=Config(signature_version="s3v4"),
        )

    def _missing(self, error) -> bool:
        return error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")

    def sha256(self, key: str) -> str | None:
        from botocore.exceptions import ClientError

        try:
            head = self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if self._missing(e):
                return None
            raise
        return head.get("Metadata", {}).get("sha256")

    def put(self, key: str, data: bytes) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            Metadata={"sha256": hashlib.sha256(data).hexdigest()},
        )

    def read_json(self, key: str):
        from botocore.exceptions import ClientError

        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as e:
            if self._missing(e):
                return None
            raise
        return json.loads(body)

    def write_json(self, key: str, data) -> None:
        self.put(key, json.dumps(data, indent=2).encode())

    def download(self, key: str, dest: str) -> None:
        self.s3.download_file(self.bucket, key, dest)

    def upload_file(self, key: str, src: str) -> None:
        digest = hashlib.sha256()
        with open(src, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
        self.s3.upload_file(src, self.bucket, key, ExtraArgs={"Metadata": {"sha256": digest.hexdigest()}})

    def exists(self, key: str) -> bool:
        return self.sha256(key) is not None or self.read_json(key) is not None

    def list_ids(self, prefix: str) -> list:
        ids = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/", Delimiter="/"
        ):
            ids += [p["Prefix"].rstrip("/").rsplit("/", 1)[-1] for p in page.get("CommonPrefixes", [])]
        return sorted(ids)

    def delete_prefix(self, prefix: str) -> None:
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/"
        ):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})

    def upload_ticket(self, key: str, sha256: str, size: int, ttl: int, base_url: str) -> dict:
        url = self.s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentLength": size,
                "Metadata": {"sha256": sha256},
            },
            ExpiresIn=ttl,
        )
        # Signed headers: the upload must send them exactly.
        return {"method": "PUT", "url": url, "headers": {"x-amz-meta-sha256": sha256}}


def storage_from_config(config: dict):
    if config["storage"] == "s3":
        return S3Storage(config["s3_bucket"], config.get("s3_endpoint"), config.get("s3_region"))
    return LocalStorage(config["storage_dir"], config["signing_key"])
