"""AI Provider API Key 的对称加密；密钥从 Django SECRET_KEY 派生。"""
from __future__ import annotations

import base64
import hashlib

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

PREFIX = "AIF:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(str(settings.SECRET_KEY).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    return PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith(PREFIX):
        return text
    try:
        return _fernet().decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask_key(value: str) -> str:
    text = decrypt_secret(value)
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:3]}***{text[-4:]}"
