"""媒体存储：默认本地磁盘；USE_S3=1 时切到 MinIO/S3（boto3 直连）。"""
from __future__ import annotations

import mimetypes
import os
import re
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db.models.signals import post_delete
from django.dispatch import receiver


class S3FileStorage(FileSystemStorage):
    """boto3 实现的 S3/MinIO 存储（键名即路径）。"""

    def __init__(self):
        super().__init__()
        import boto3
        from botocore.client import Config

        endpoint = os.environ.get("S3_ENDPOINT_URL")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
            config=Config(s3={"addressing_style": "virtual" if not endpoint else "path"}),
        )
        self.bucket = os.environ.get("S3_BUCKET", "webprocess")
        self.base_url = os.environ.get(
            "S3_PUBLIC_URL",
            f"{endpoint or 'https://s3.amazonaws.com'}/{self.bucket}",
        ).rstrip("/")

    def _key(self, name: str) -> str:
        return name.lstrip("/")

    def _save(self, name, content):
        self._client.put_object(
            Bucket=self.bucket,
            Key=self._key(name),
            Body=content.read(),
            ContentType=content.content_type or "application/octet-stream",
        )
        return name

    def url(self, name):
        return f"{self.base_url}/{self._key(name)}"

    def exists(self, name):
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(name))
            return True
        except Exception:
            return False

    def delete(self, name):
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._key(name))
        except Exception:
            pass

    def size(self, name):
        try:
            r = self._client.head_object(Bucket=self.bucket, Key=self._key(name))
            return r.get("ContentLength")
        except Exception:
            return None

    def open(self, name, mode="rb"):
        import io

        data = self._client.get_object(Bucket=self.bucket, Key=self._key(name))["Body"].read()
        return io.BytesIO(data)


def get_media_storage():
    if os.environ.get("USE_S3", "").lower() in ("1", "true", "yes", "on"):
        return S3FileStorage()
    return FileSystemStorage()


def generate_object_name(directory: str, filename: str) -> str:
    """安全对象名：media/<directory>/<yyyy>/<mm>/<uuid><ext>。"""
    base = os.path.basename(filename or "")
    ext = os.path.splitext(base)[1].lower()
    if ext and not re.match(r"^\.[a-z0-9]{1,10}$", ext):
        ext = ""
    now = _now()
    return f"{directory}/{now.year:04d}/{now.month:02d}/{uuid.uuid4().hex}{ext}"


def _now():
    from django.utils import timezone

    return timezone.now()


def file_ext_type(filename: str) -> str:
    mime = mimetypes.guess_type(os.path.basename(filename or ""))[0] or "application/octet-stream"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("font/"):
        return "font"
    return "file"
