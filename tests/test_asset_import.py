# tests/test_asset_import.py
"""
数字分身资产导入模块测试

覆盖：合法导入、头像落盘、重导入去重与覆盖、非法密文、缺字段、周期校验。
"""
import json
import base64
import os
import pytest
from shadowtalk.core.asset_import_service import (
    AssetImportService, AssetBundle, InvalidCipherError, RevokedAssetError,
)
from shadowtalk.core.crypto_service import get_cipher
from shadowtalk.data.repositories import FriendRepository


def _make_bundle_payload(**overrides) -> dict:
    """构造一个合法的密文字典（供测试用）。"""
    payload = {
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
    payload.update(overrides)
    return payload


def _encode_bundle(payload: dict) -> str:
    """把字典加密为 Base64 密文字符串（使用 TimeKeyCipher）。"""
    cipher = get_cipher()
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return cipher.encrypt(plaintext)


class TestParseBundle:
    def test_parse_valid_bundle(self):
        payload = _make_bundle_payload()
        bundle = AssetImportService.parse_bundle(json.dumps(payload).encode("utf-8"))
        assert bundle.nickname == "小明"
        assert bundle.persona == "你是一个开朗的高中生，喜欢打篮球。"
        assert bundle.authorizer_email == "xiaoming@example.com"
        assert bundle.recipient_email == "user@example.com"
        assert bundle.mail_sync_enable is True
        assert bundle.mail_receiver_address == "xiaoming@example.com"
        assert bundle.mail_sync_cycle == "weekly"

    def test_parse_invalid_json_raises(self):
        with pytest.raises(InvalidCipherError):
            AssetImportService.parse_bundle("不是JSON".encode("utf-8"))

    def test_parse_missing_required_field_raises(self):
        payload = _make_bundle_payload()
        del payload["nickname"]
        with pytest.raises(InvalidCipherError):
            AssetImportService.parse_bundle(json.dumps(payload).encode("utf-8"))

    def test_parse_invalid_cycle_raises(self):
        payload = _make_bundle_payload(mail_sync_cycle="hourly")
        with pytest.raises(InvalidCipherError):
            AssetImportService.parse_bundle(json.dumps(payload).encode("utf-8"))

    def test_parse_with_avatar_bytes(self):
        payload = _make_bundle_payload(avatar_base64=base64.b64encode(b"\x89PNGfake").decode("ascii"))
        bundle = AssetImportService.parse_bundle(json.dumps(payload).encode("utf-8"))
        assert bundle.avatar_bytes == b"\x89PNGfake"
        assert bundle.avatar_ext == ".png"


class TestImportAsset:
    def test_import_creates_friend_with_mail_config(self):
        """合法密文->落库，校验 mail_sync_* 字段正确。"""
        payload = _make_bundle_payload()
        b64 = _encode_bundle(payload)
        fid = AssetImportService.import_asset(b64)
        friend = FriendRepository.get_by_id(fid)
        assert friend["name"] == "小明"
        assert friend["system_prompt"] == "你是一个开朗的高中生，喜欢打篮球。"
        assert friend["authorizer_email"] == "xiaoming@example.com"
        assert friend["recipient_email"] == "user@example.com"
        assert friend["mail_sync_enable"] == 1
        assert friend["mail_receiver_address"] == "xiaoming@example.com"
        assert friend["mail_sync_cycle"] == "weekly"

    def test_import_persists_avatar(self):
        """头像字节写入 AVATAR_DIR/<fid>/avatar.<ext>。"""
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        payload = _make_bundle_payload(
            avatar_base64=base64.b64encode(fake_png).decode("ascii"),
            avatar_ext=".png",
        )
        b64 = _encode_bundle(payload)
        fid = AssetImportService.import_asset(b64)
        friend = FriendRepository.get_by_id(fid)
        assert friend["avatar_path"]
        assert os.path.isfile(friend["avatar_path"])
        with open(friend["avatar_path"], "rb") as f:
            assert f.read() == fake_png

    def test_reimport_overwrites_persona_and_mail_config(self):
        """同 authorizer+recipient 再次导入->字段覆盖、好友数不增。"""
        payload = _make_bundle_payload()
        b64 = _encode_bundle(payload)
        fid1 = AssetImportService.import_asset(b64)
        count_before = len(FriendRepository.get_all())

        # 重导入：改人设和周期
        payload2 = _make_bundle_payload(
            persona="你变成了一个沉默的大学生。",
            mail_sync_cycle="monthly",
        )
        b64_2 = _encode_bundle(payload2)
        fid2 = AssetImportService.import_asset(b64_2)

        count_after = len(FriendRepository.get_all())
        assert fid2 == fid1                        # 同一好友
        assert count_after == count_before          # 好友数不增
        friend = FriendRepository.get_by_id(fid1)
        assert friend["system_prompt"] == "你变成了一个沉默的大学生。"
        assert friend["mail_sync_cycle"] == "monthly"

    def test_reimport_preserves_email_session_id(self):
        """覆盖不改变 email_session_id（保持邮件会话连续）。"""
        payload = _make_bundle_payload()
        fid = AssetImportService.import_asset(_encode_bundle(payload))
        # 手动设置一个 session_id（模拟已发送过邮件）
        FriendRepository.update(fid, email_session_id="test-session-123")
        sid_before = FriendRepository.get_by_id(fid)["email_session_id"]

        payload2 = _make_bundle_payload(persona="新人设")
        AssetImportService.import_asset(_encode_bundle(payload2))

        sid_after = FriendRepository.get_by_id(fid)["email_session_id"]
        assert sid_before == sid_after == "test-session-123"

    def test_invalid_cipher_shows_error(self):
        """非法 base64 / 解密失败->InvalidCipherError。"""
        with pytest.raises(InvalidCipherError):
            AssetImportService.import_asset("!!!不是有效的base64!!!")

    def test_missing_required_field_raises(self):
        """解密后 JSON 缺必填字段->抛错。"""
        payload = _make_bundle_payload()
        del payload["authorizer_email"]
        b64 = _encode_bundle(payload)
        with pytest.raises(InvalidCipherError):
            AssetImportService.import_asset(b64)

    def test_mail_sync_cycle_validation(self):
        """非法 cycle 值被拒绝。"""
        payload = _make_bundle_payload(mail_sync_cycle="yearly")
        b64 = _encode_bundle(payload)
        with pytest.raises(InvalidCipherError):
            AssetImportService.import_asset(b64)

    def test_revoked_asset_reimport_blocked(self):
        """已撤销的分身拒绝重新导入。"""
        payload = _make_bundle_payload()
        fid = AssetImportService.import_asset(_encode_bundle(payload))
        # 模拟已撤销
        FriendRepository.update(fid, asset_revoked=1)

        with pytest.raises(RevokedAssetError):
            AssetImportService.import_asset(_encode_bundle(payload))
