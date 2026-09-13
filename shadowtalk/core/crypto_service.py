# shadowtalk/core/crypto_service.py
"""
数字资产密文编解码（方案 B：时间戳 + nonce + PBKDF2 + AES-CTR + HMAC）。

加密流程：
1. 获取当前时间戳精确到分钟（如 "202608191430"）
2. 生成随机 nonce（8 字节 hex）
3. 密钥派生：AES_key || HMAC_key = PBKDF2(reverse(timestamp) + nonce + 私钥, salt, 100000)
4. AES-128-CTR 加密明文 JSON
5. HMAC-SHA256 认证：tag = HMAC(HMAC_key, version || timestamp || nonce || ciphertext)
6. 打包：base64(version || timestamp || nonce || ciphertext || tag)

解密流程：
1. base64 解码 → 拆分各字段
2. 用 timestamp + nonce + 私钥 派生密钥
3. 验证 HMAC tag（防篡改）
4. AES-CTR 解密 → 明文 JSON
"""
import json
import base64
import os
import struct
import time
import logging
from datetime import datetime

from shadowtalk.core.aes_core import (
    aes_ctr_encrypt, aes_ctr_decrypt,
    hmac_sha256, verify_hmac, derive_key,
)

logger = logging.getLogger(__name__)

# ── 配置 ──
# 固定私钥（内置到软件 + 网页端）—— 生产环境应从安全存储读取
PRIVATE_KEY = b"ShadowTalk-Asset-Key-2026"
# PBKDF2 盐值（固定，可公开）
PBKDF2_SALT = b"ShadowTalk-Asset-Salt-v1"
# PBKDF2 迭代次数
PBKDF2_ITERATIONS = 100000
# 格式版本（向前兼容）
FORMAT_VERSION = 1

# 密文结构：version(1) + timestamp(12) + nonce(8) + ctr_nonce(8) + ciphertext(variable) + tag(32)
# timestamp 格式："%Y%m%d%H%M" = 12 字节（如 "202608191430"）
HEADER_SIZE = 1 + 12 + 8  # version + timestamp + nonce
CTR_NONCE_SIZE = 8
TAG_SIZE = 32


class AssetCipher:
    """密文编解码接口（协议）。"""

    def encrypt(self, plaintext: bytes) -> str:
        """加密明文 bytes，返回 Base64 密文字符串。"""
        ...

    def decrypt(self, b64_text: str) -> bytes:
        """解密 Base64 密文，返回明文 bytes。失败抛 InvalidCipherError。"""
        ...


class InvalidCipherError(Exception):
    """密文无效或已损坏。"""
    pass


class TimeKeyCipher:
    """方案 B 实现：时间戳 + nonce + PBKDF2 + AES-CTR + HMAC-SHA256。"""

    def encrypt(self, plaintext: bytes) -> str:
        """加密明文 bytes，返回 Base64 密文字符串。"""
        # 1. 时间戳精确到分钟
        timestamp = datetime.now().strftime("%Y%m%d%H%M").encode("ascii")

        # 2. 随机 nonce（8 字节）
        nonce = os.urandom(8)

        # 3. 密钥派生
        aes_key, hmac_key = self._derive_keys(timestamp, nonce)

        # 4. AES-CTR 加密
        ctr_nonce, ciphertext = aes_ctr_encrypt(aes_key, plaintext)

        # 5. 打包：version || timestamp || nonce || ctr_nonce || ciphertext
        #    ctr_nonce 也作为 nonce 的一部分嵌入密文
        payload = (
            struct.pack("B", FORMAT_VERSION)
            + timestamp
            + nonce
            + ctr_nonce
            + ciphertext
        )

        # 6. HMAC 认证
        tag = hmac_sha256(hmac_key, payload)

        # 7. Base64 编码
        return base64.b64encode(payload + tag).decode("ascii")

    def decrypt(self, b64_text: str) -> bytes:
        """解密 Base64 密文，返回明文 bytes。失败抛 InvalidCipherError。"""
        try:
            # 1. Base64 解码
            raw = base64.b64decode(b64_text.strip())
        except Exception as e:
            raise InvalidCipherError(f"Base64 解码失败：{e}")

        # 2. 拆分字段
        min_size = HEADER_SIZE + CTR_NONCE_SIZE + TAG_SIZE
        if len(raw) < min_size:
            raise InvalidCipherError("密文长度不足")

        version = raw[0]
        if version != FORMAT_VERSION:
            raise InvalidCipherError(f"不支持的密文版本：{version}")

        timestamp = raw[1:13]    # 12 字节 "202608191430"
        nonce = raw[13:21]       # 8 字节随机 nonce
        ctr_nonce = raw[21:29]   # 8 字节 CTR nonce
        ciphertext = raw[29:-TAG_SIZE]
        tag = raw[-TAG_SIZE:]

        # 3. 密钥派生
        aes_key, hmac_key = self._derive_keys(timestamp, nonce)

        # 4. 验证 HMAC
        payload = raw[:-TAG_SIZE]
        if not verify_hmac(hmac_key, payload, tag):
            raise InvalidCipherError("密文认证失败（可能被篡改或密钥错误）")

        # 5. AES-CTR 解密
        try:
            plaintext = aes_ctr_decrypt(aes_key, ctr_nonce, ciphertext)
        except Exception as e:
            raise InvalidCipherError(f"解密失败：{e}")

        return plaintext

    @staticmethod
    def _derive_keys(timestamp: bytes, nonce: bytes) -> tuple:
        """派生 AES 密钥和 HMAC 密钥。

        密钥材料 = reverse(timestamp) + nonce + 私钥
        派生：PBKDF2(密钥材料, salt, 100000) → 32 字节
        拆分：前 16 字节 = AES_key，后 16 字节 = HMAC_key
        """
        # reverse(timestamp)：时间戳倒序
        reversed_ts = timestamp[::-1]
        # 密钥材料 = reverse(timestamp) + nonce + 私钥
        key_material = reversed_ts + nonce + PRIVATE_KEY
        # PBKDF2 派生 32 字节
        derived = derive_key(key_material, PBKDF2_SALT, PBKDF2_ITERATIONS)
        return derived[:16], derived[16:]


def get_cipher() -> AssetCipher:
    """返回当前密文编解码器。"""
    return TimeKeyCipher()
