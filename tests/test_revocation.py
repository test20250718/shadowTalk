# tests/test_mail_revocation.py
"""
授权作废模块测试

覆盖：精确标签匹配、AI 语义兜底、安全校验（非授权方忽略）、冻结态行为。
"""
import os
import json
import base64
import pytest
from unittest.mock import patch, MagicMock

from shadowtalk.core.revocation_service import RevocationService
from shadowtalk.core.mail_receiver import RawEmail
from shadowtalk.core.asset_import_service import AssetImportService
from shadowtalk.core.crypto_service import get_cipher
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository,
)


def _make_friend_with_session(**overrides) -> int:
    """创建一个有 session_id 且开启邮件同步的好友。"""
    payload = {
        "nickname": "测试分身",
        "persona": "你是一个开朗的高中生。",
        "avatar_base64": "",
        "avatar_ext": ".png",
        "authorizer_email": "author@test.com",
        "recipient_email": "recipient@test.com",
        "mail_sync_enable": True,
        "mail_receiver_address": "author@test.com",
        "mail_sync_cycle": "daily",
    }
    payload.update(overrides)
    # 使用 TimeKeyCipher 加密（与生产环境一致）
    cipher = get_cipher()
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ciphertext = cipher.encrypt(plaintext)
    fid = AssetImportService.import_asset(ciphertext)
    FriendRepository.update(fid, email_session_id="a1b2c3d4e5f6a7b8")
    return fid


def _make_raw_email(sender="author@test.com", body="测试内容") -> RawEmail:
    """构造一个 RawEmail。"""
    return RawEmail(
        message_id="test-msg-1",
        sender=sender,
        subject="[ShadowTalk-sess1234] 聊天记录",
        in_reply_to="",
        references="",
        body_text=body,
        date="",
    )


def _get_friend(fid) -> dict:
    """获取 friend Row。"""
    return FriendRepository.get_by_id(fid)


class TestExactTag:
    def test_exact_tag_triggers_revoke(self):
        """#作废授权# -> revoke。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="请 #作废授权#")
        result = RevocationService.evaluate(raw, friend)
        assert result == "revoke"

    def test_no_tag_treated_as_human_reply(self):
        """无标签 -> human_reply。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="这是一条普通回复")
        result = RevocationService.evaluate(raw, friend)
        assert result == "human_reply"


class TestQuotedFooterSafety:
    """回信引用原文的回归测试：我们发出的邮件尾部必带
    "回复 #作废授权# 可取消授权"提示，对全文做精确匹配会把每封
    普通回信都误判成撤销（用户报告：刚收到回信分身就被冻结）。"""

    _QUOTED_REPLY = (
        "收到，谢谢\n"
        "\n"
        "\n"
        "在 2026-08-22 11:33:42,13701650622@163.com 写道：\n"
        "以下是您授权的数字分身【秘书】最近的聊天记录：\n"
        "[2026-08-22 10:31] 我：\n"
        "最近的工作如何？\n"
        "——\n"
        "此邮件由 ShadowTalk 影聊自动发送，包含您授权的数字分身聊天记录。\n"
        "如需取消该分身的授权，请直接回复 #作废授权#。\n"
    )

    def test_quoted_footer_not_revoke(self):
        """引用原文里的 #作废授权# 提示语不得触发撤销。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body=self._QUOTED_REPLY)
        assert RevocationService.evaluate(raw, friend) == "human_reply"

    def test_ai_fallback_receives_extracted_body_only(self):
        """AI 兜底只应看到剥离引用后的本人正文——把含 #作废授权#
        提示语的原邮件喂给 AI，很容易被诱导判成 YES。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body=self._QUOTED_REPLY)
        mock_ai = MagicMock()
        mock_ai.chat.return_value = "NO"
        assert RevocationService.evaluate(raw, friend, mock_ai) == "human_reply"
        sent_messages = mock_ai.chat.call_args.args[0]
        user_content = sent_messages[1]["content"]
        assert "收到，谢谢" in user_content      # 本人正文完整送达
        assert "#作废授权#" not in user_content  # 引用原文的提示语已剥离

    def test_pure_quote_no_own_words(self):
        """纯引用（无本人正文）-> human_reply，不撤销。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(
            body="在 2026-08-22 11:33:42,13701650622@163.com 写道：\n"
                 "#作废授权#\n")
        assert RevocationService.evaluate(raw, friend) == "human_reply"

    def test_genuine_tag_in_own_words_still_revoke(self):
        """本人正文里的 #作废授权#（未被引用过滤剥离）仍正常撤销。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(
            body="我考虑清楚了，#作废授权# 吧\n"
                 "\n在 2026-08-22 11:33:42,13701650622@163.com 写道：\n"
                 "如需取消该分身的授权，请直接回复 #作废授权#。\n")
        assert RevocationService.evaluate(raw, friend) == "revoke"


class TestAIFallback:
    def test_ai_yes_triggers_revoke(self):
        """AI 返回 YES -> revoke。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="我不想让你用了，取消吧")

        mock_ai = MagicMock()
        mock_ai.chat.return_value = "YES"
        result = RevocationService.evaluate(raw, friend, mock_ai)
        assert result == "revoke"

    def test_ai_no_treated_as_human_reply(self):
        """AI 返回 NO -> human_reply。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="今天天气真好")

        mock_ai = MagicMock()
        mock_ai.chat.return_value = "NO"
        result = RevocationService.evaluate(raw, friend, mock_ai)
        assert result == "human_reply"

    def test_ai_failure_defaults_no(self):
        """AI 调用失败 -> 保守视为 NO（human_reply）。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="取消吧")

        mock_ai = MagicMock()
        mock_ai.chat.side_effect = Exception("连接失败")
        result = RevocationService.evaluate(raw, friend, mock_ai)
        assert result == "human_reply"

    def test_ai_messy_response_yes(self):
        """AI 返回带解释的 YES -> 仍识别为 revoke。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="取消授权")

        mock_ai = MagicMock()
        mock_ai.chat.return_value = "YES，用户明确表示要终止授权"
        result = RevocationService.evaluate(raw, friend, mock_ai)
        assert result == "revoke"

    def test_no_ai_client_skips_fallback(self):
        """无 AI 客户端时跳过 AI 兜底（普通回复 -> human_reply）。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(body="取消吧")  # 口语化但无 AI 判断
        result = RevocationService.evaluate(raw, friend, None)
        assert result == "human_reply"


class TestSecurityCheck:
    def test_unauthorized_sender_ignored(self):
        """sender != mail_receiver_address -> 忽略（不插入、不冻结）。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        raw = _make_raw_email(
            sender="hacker@evil.com",
            body="#作废授权#"  # 即使有标签，非授权方也忽略
        )
        result = RevocationService.evaluate(raw, friend)
        assert result == "ignore"

    def test_exact_tag_only_for_authorized_sender(self):
        """精确标签仅对授权方生效。"""
        fid = _make_friend_with_session()
        friend = _get_friend(fid)
        # 授权方 + 标签 -> revoke
        raw = _make_raw_email(sender="author@test.com", body="#作废授权#")
        assert RevocationService.evaluate(raw, friend) == "revoke"


class TestRevokedBehavior:
    def test_revoked_friend_stops_sync(self):
        """asset_revoked=1 后调度跳过。"""
        from shadowtalk.core.mail_sync_scheduler import MailSyncScheduler
        fid = _make_friend_with_session()
        # 撤销前应在待发列表
        due_before = MailSyncScheduler.sync_due_friends()
        assert fid in due_before
        # 撤销
        FriendRepository.update(fid, asset_revoked=1)
        due_after = MailSyncScheduler.sync_due_friends()
        assert fid not in due_after

    def test_revoked_friend_freezes_chat(self):
        """冻结态拒绝发送（DB 层面验证）。"""
        fid = _make_friend_with_session()
        FriendRepository.update(fid, asset_revoked=1)
        friend = _get_friend(fid)
        assert friend["asset_revoked"] == 1

    def test_revoked_asset_reimport_blocked(self):
        """已撤销的分身拒绝重新导入。"""
        from shadowtalk.core.asset_import_service import RevokedAssetError
        # 先创建好友并记录密文
        payload = {
            "nickname": "测试分身",
            "persona": "你是一个开朗的高中生。",
            "avatar_base64": "",
            "avatar_ext": ".png",
            "authorizer_email": "author@test.com",
            "recipient_email": "recipient@test.com",
            "mail_sync_enable": True,
            "mail_receiver_address": "author@test.com",
            "mail_sync_cycle": "daily",
        }
        cipher = get_cipher()
        plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ciphertext = cipher.encrypt(plaintext)
        # 首次导入
        fid = AssetImportService.import_asset(ciphertext)
        FriendRepository.update(fid, email_session_id="a1b2c3d4e5f6a7b8")
        # 撤销
        FriendRepository.update(fid, asset_revoked=1)
        # 重新导入同一密文应被拒绝
        with pytest.raises(RevokedAssetError):
            AssetImportService.import_asset(ciphertext)
