# tests/test_crypto_service.py
"""
数字资产加密模块测试

覆盖：加解密往返、篡改检测、非法输入、密钥派生。
"""
import json
import base64
import os
import pytest
from shadowtalk.core.crypto_service import (
    TimeKeyCipher, InvalidCipherError, get_cipher,
    FORMAT_VERSION, PRIVATE_KEY, PBKDF2_SALT,
)


class TestTimeKeyCipher:
    def test_encrypt_decrypt_roundtrip(self):
        """加密 → 解密往返，明文应一致。"""
        cipher = TimeKeyCipher()
        plaintext = '{"nickname": "测试", "persona": "你是一个助手。"}'.encode("utf-8")
        ciphertext = cipher.encrypt(plaintext)
        # 密文是 Base64 字符串
        assert isinstance(ciphertext, str)
        # 解密后应还原
        decrypted = cipher.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_ciphertext_is_base64(self):
        """密文应是有效的 Base64 字符串。"""
        cipher = TimeKeyCipher()
        ciphertext = cipher.encrypt(b"test data")
        # 应能解码
        raw = base64.b64decode(ciphertext)
        assert len(raw) > 0

    def test_different_plaintexts_produce_different_ciphertexts(self):
        """不同明文应产生不同密文（随机 nonce 保证）。"""
        cipher = TimeKeyCipher()
        ct1 = cipher.encrypt(b"plaintext one")
        ct2 = cipher.encrypt(b"plaintext two")
        assert ct1 != ct2

    def test_same_plaintext_different_ciphertexts(self):
        """同一明文两次加密应产生不同密文（随机 nonce）。"""
        cipher = TimeKeyCipher()
        ct1 = cipher.encrypt(b"same plaintext")
        ct2 = cipher.encrypt(b"same plaintext")
        assert ct1 != ct2  # 不同 nonce → 不同密文

    def test_tampered_ciphertext_detected(self):
        """篡改密文应被 HMAC 检测到。"""
        cipher = TimeKeyCipher()
        ciphertext = cipher.encrypt(b"original data")
        raw = bytearray(base64.b64decode(ciphertext))
        # 篡改密文部分（修改最后一个字节）
        raw[-35] ^= 0xff
        tampered = base64.b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(InvalidCipherError):
            cipher.decrypt(tampered)

    def test_invalid_base64_raises(self):
        """非法 Base64 输入应抛 InvalidCipherError。"""
        cipher = TimeKeyCipher()
        with pytest.raises(InvalidCipherError):
            cipher.decrypt("!!!不是有效的base64!!!")

    def test_too_short_ciphertext_raises(self):
        """过短密文应抛 InvalidCipherError。"""
        cipher = TimeKeyCipher()
        short = base64.b64encode(b"short").decode("ascii")
        with pytest.raises(InvalidCipherError):
            cipher.decrypt(short)

    def test_asset_bundle_roundtrip(self):
        """模拟真实资产数据的加解密往返。"""
        cipher = TimeKeyCipher()
        asset = {
            "nickname": "小明",
            "persona": "你是一个开朗的高中生，喜欢打篮球。",
            "avatar_base64": "",
            "avatar_ext": ".png",
            "authorizer_email": "xiaoming@example.com",
            "recipient_email": "user@example.com",
            "mail_sync_enable": True,
            "mail_receiver_address": "xiaoming@example.com",
            "mail_sync_cycle": "weekly",
        }
        plaintext = json.dumps(asset, ensure_ascii=False).encode("utf-8")
        ciphertext = cipher.encrypt(plaintext)
        decrypted = cipher.decrypt(ciphertext)
        restored = json.loads(decrypted.decode("utf-8"))
        assert restored == asset

    def test_get_cipher_returns_cipher(self):
        """get_cipher 应返回 AssetCipher 实例。"""
        cipher = get_cipher()
        assert isinstance(cipher, TimeKeyCipher)


class TestKeyDerivation:
    def test_derive_keys_deterministic(self):
        """相同 timestamp + nonce 应派生相同密钥。"""
        cipher = TimeKeyCipher()
        ts = b"202608191430"
        nonce = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        keys1 = cipher._derive_keys(ts, nonce)
        keys2 = cipher._derive_keys(ts, nonce)
        assert keys1 == keys2

    def test_derive_keys_different_nonce(self):
        """不同 nonce 应派生不同密钥。"""
        cipher = TimeKeyCipher()
        ts = b"202608191430"
        nonce1 = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        nonce2 = b"\x08\x07\x06\x05\x04\x03\x02\x01"
        keys1 = cipher._derive_keys(ts, nonce1)
        keys2 = cipher._derive_keys(ts, nonce2)
        assert keys1 != keys2

    def test_derive_keys_output_length(self):
        """派生的 AES key 和 HMAC key 各 16 字节。"""
        cipher = TimeKeyCipher()
        ts = b"202608191430"
        nonce = os.urandom(8)
        aes_key, hmac_key = cipher._derive_keys(ts, nonce)
        assert len(aes_key) == 16
        assert len(hmac_key) == 16
