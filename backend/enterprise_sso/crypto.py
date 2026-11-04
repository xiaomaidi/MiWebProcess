"""client_secret 静态加密：Fernet（密钥由 SECRET_KEY 派生）。

设计要点：
- 磁盘上只保存 ``enc:v1:<token>``；API 永不返回明文（字段 write_only + 摘要布尔）。
- 未安装 ``cryptography`` 时降级为明文存储（绝不因此 500），但仍不会通过 API 返回。
- 读取历史明文（无前缀）保持兼容；解密失败返回空串并记录告警（不抛异常、不泄露密文）。
- 密钥轮换（SECRET_KEY 变更）后旧密文解不开 → 登录流程返回「配置失效」，需重新填写 secret。
"""
from __future__ import annotations

import base64
import hashlib
import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger("enterprise_sso")

_PREFIX = "enc:v1:"


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception:  # pragma: no cover - cryptography 一般随 requirements 安装
        return None
    try:
        key = hashlib.sha256(
            f"{settings.SECRET_KEY}|enterprise-sso.client-secret".encode("utf-8")
        ).digest()
        return Fernet(base64.urlsafe_b64encode(key))
    except Exception:  # pragma: no cover
        return None


def encrypt_secret(plaintext: str) -> str:
    """明文 → 存储值（空值保持空值，已加密值幂等返回）。"""
    value = "" if plaintext is None else str(plaintext)
    if not value:
        return ""
    if value.startswith(_PREFIX):
        return value
    fernet = _fernet()
    if fernet is None:
        return value
    try:
        return _PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")
    except Exception:
        logger.warning("sso.secret.encrypt_failed")
        return value


def decrypt_secret(stored: str) -> str:
    """存储值 → 明文（非加密历史值原样返回；解密失败返回空串）。"""
    value = "" if stored is None else str(stored)
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return value
    fernet = _fernet()
    if fernet is None:
        logger.warning("sso.secret.decrypt_unavailable")
        return ""
    try:
        return fernet.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except Exception:
        logger.warning("sso.secret.decrypt_failed")
        return ""


class EncryptedTextField(models.TextField):
    """透明加解密的 TextField：模型层看到明文，数据库列是密文。

    注意：Fernet 每次加密使用随机 IV，因此不能用该字段做等值查询。
    """

    def from_db_value(self, value, expression, connection):
        return decrypt_secret(value)

    def get_prep_value(self, value):
        return encrypt_secret(value)
