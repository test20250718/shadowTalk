# tests/test_mail_sender.py
"""
邮件发送与同步调度测试

覆盖：邮件组装（主题短码、作废尾部）、SMTP 发送（MailHog）、周期判定、游标去重。
无 MailHog 时 SMTP 发送测试自动跳过。
"""
import os
import json
import base64
import pytest
from unittest.mock import patch, MagicMock

from shadowtalk.core.mail_composer import MailComposer, REVOCATION_FOOTER
from shadowtalk.core.mail_sender import MailSender, MailSendError
from shadowtalk.core.mail_sync_scheduler import MailSyncScheduler
from shadowtalk.core.asset_import_service import AssetImportService
from shadowtalk.core.crypto_service import get_cipher
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def _make_friend_with_mail_sync(**overrides) -> int:
    """创建一个开启邮件同步的好友。"""
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
    return AssetImportService.import_asset(ciphertext)


class TestMailComposer:
    def _make_friend_row(self, **kwargs):
        """构造一个模拟的 friend Row 对象。"""
        friend = {
            "id": 1,
            "name": "测试分身",
            "remark": "",
            "mail_receiver_address": "author@test.com",
            "email_session_id": "abc1234567890def",
        }
        friend.update(kwargs)
        return friend

    def test_compose_subject_contains_session_shortcode(self):
        """主题含 [ShadowTalk-xxxxxxxx]。"""
        friend = self._make_friend_row()
        messages = [
            {"sender_type": "user", "content": "你好", "create_time": "2026-08-19 10:00:00"},
            {"sender_type": "ai", "content": "你好！", "create_time": "2026-08-19 10:00:01"},
        ]
        msg = MailComposer.compose(friend, messages, "abc1234567890def")
        assert "[ShadowTalk-abc12345]" in msg.subject

    def test_compose_includes_revocation_footer(self):
        """正文尾部含 #作废授权#。"""
        friend = self._make_friend_row()
        messages = [
            {"sender_type": "user", "content": "你好", "create_time": "2026-08-19 10:00:00"},
        ]
        msg = MailComposer.compose(friend, messages, "session123")
        assert "#作废授权#" in msg.body_text

    def test_compose_has_session_header(self):
        """extra_headers 含 X-ShadowTalk-Session。"""
        friend = self._make_friend_row()
        messages = [
            {"sender_type": "user", "content": "你好", "create_time": "2026-08-19 10:00:00"},
        ]
        msg = MailComposer.compose(friend, messages, "mysessionid")
        assert msg.extra_headers["X-ShadowTalk-Session"] == "mysessionid"

    def test_compose_message_id_format(self):
        """Message-ID 格式为 <session_id>@shadowtalk.local。"""
        friend = self._make_friend_row()
        messages = [
            {"sender_type": "user", "content": "你好", "create_time": "2026-08-19 10:00:00"},
        ]
        msg = MailComposer.compose(friend, messages, "abc123")
        assert msg.message_id == "abc123@shadowtalk.local"

    def test_compose_empty_messages(self):
        """空消息列表也能组装（边界情况）。"""
        friend = self._make_friend_row()
        msg = MailComposer.compose(friend, [], "session123")
        assert msg.subject
        assert "#作废授权#" in msg.body_text


class TestMailSender:
    def test_send_composes_message_with_session_header(self):
        """SMTP 发送的邮件含 X-ShadowTalk-Session + Message-ID（使用 mock）。"""
        sender = MailSender("smtp.test.com", 587, True, "user@test.com", "pass")
        from shadowtalk.core.mail_composer import MailMessage

        mail_msg = MailMessage(
            subject="[ShadowTalk-abc123] 测试聊天记录",
            body_text="测试正文\n" + REVOCATION_FOOTER,
            message_id="abc123@shadowtalk.local",
            extra_headers={"X-ShadowTalk-Session": "abc123"},
            to="author@test.com",
        )

        # mock smtplib.SMTP_SSL
        with patch("shadowtalk.core.mail_sender.smtplib.SMTP_SSL") as mock_ssl:
            mock_server = MagicMock()
            mock_ssl.return_value = mock_server
            result_id = sender.send(mail_msg)
            assert result_id == "abc123@shadowtalk.local"
            mock_server.login.assert_called_once_with("user@test.com", "pass")
            mock_server.send_message.assert_called_once()
            mock_server.quit.assert_called_once()

    def test_send_without_tls(self):
        """非 TLS 模式使用 SMTP（非 SMTP_SSL）。"""
        sender = MailSender("127.0.0.1", 1025, False, "", "")
        from shadowtalk.core.mail_composer import MailMessage

        mail_msg = MailMessage(
            subject="[ShadowTalk-abc123] 测试",
            body_text="正文",
            message_id="abc123@shadowtalk.local",
            extra_headers={},
            to="to@test.com",
        )

        with patch("shadowtalk.core.mail_sender.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value = mock_server
            sender.send(mail_msg)
            mock_server.login.assert_not_called()  # 无用户名不登录
            mock_server.send_message.assert_called_once()

    def test_send_failure_raises(self):
        """SMTP 异常转为 MailSendError。"""
        sender = MailSender("smtp.test.com", 587, True, "user@test.com", "pass")
        from shadowtalk.core.mail_composer import MailMessage

        mail_msg = MailMessage(
            subject="测试", body_text="正文",
            message_id="id@shadowtalk.local",
            extra_headers={}, to="to@test.com",
        )

        with patch("shadowtalk.core.mail_sender.smtplib.SMTP_SSL") as mock_ssl:
            import smtplib
            mock_ssl.side_effect = smtplib.SMTPException("连接失败")
            with pytest.raises(MailSendError):
                sender.send(mail_msg)

    def test_send_real_mailhog(self):
        """真实 MailHog 发送测试（无 MailHog 时跳过）。"""
        import smtplib
        # 尝试连接 MailHog
        try:
            test_server = smtplib.SMTP("127.0.0.1", 1025)
            test_server.quit()
        except (ConnectionRefusedError, OSError):
            pytest.skip("MailHog 未运行（127.0.0.1:1025）")

        sender = MailSender("127.0.0.1", 1025, False, "", "")
        from shadowtalk.core.mail_composer import MailMessage

        mail_msg = MailMessage(
            subject="[ShadowTalk-test123] 测试分身聊天记录",
            body_text="以下是测试聊天记录：\n\n[2026-08-19 10:00] 我：你好\n\n" + REVOCATION_FOOTER,
            message_id="test123@shadowtalk.local",
            extra_headers={"X-ShadowTalk-Session": "test123"},
            to="author@test.com",
        )
        result_id = sender.send(mail_msg)
        assert result_id == "test123@shadowtalk.local"


class TestMailSyncScheduler:
    def test_sync_skips_disabled_friends(self):
        """mail_sync_enable=0 不进入待发列表。"""
        fid = _make_friend_with_mail_sync(mail_sync_enable=False)
        due = MailSyncScheduler.sync_due_friends()
        assert fid not in due

    def test_sync_skips_revoked_friends(self):
        """asset_revoked=1 不进入待发列表。"""
        fid = _make_friend_with_mail_sync()
        FriendRepository.update(fid, asset_revoked=1)
        due = MailSyncScheduler.sync_due_friends()
        assert fid not in due

    def test_sync_includes_enabled_friend_without_sent(self):
        """从未发送的 enable 好友进入待发列表。"""
        fid = _make_friend_with_mail_sync()
        due = MailSyncScheduler.sync_due_friends()
        assert fid in due

    def test_due_info_generates_session_id(self):
        """首次获取 due_info 时生成 session_id。"""
        fid = _make_friend_with_mail_sync()
        # 确保无 session_id
        FriendRepository.update(fid, email_session_id="")
        info = MailSyncScheduler.due_info(fid)
        assert info["session_id"]
        # 已写回数据库
        friend = FriendRepository.get_by_id(fid)
        assert friend["email_session_id"] == info["session_id"]

    def test_due_info_returns_new_messages(self):
        """due_info 返回 id 大于游标的消息。"""
        fid = _make_friend_with_mail_sync()
        # 插入一些消息
        MessageRepository.insert(fid, "user", "消息1", 1)
        MessageRepository.insert(fid, "ai", "回复1", 1)
        MessageRepository.insert(fid, "user", "消息2", 2)
        info = MailSyncScheduler.due_info(fid)
        assert len(info["messages"]) == 3

    def test_mark_sent_updates_cursor(self):
        """发送后 last_sent_message_id 更新，下次不发重复。"""
        fid = _make_friend_with_mail_sync()
        m1 = MessageRepository.insert(fid, "user", "消息1", 1)
        MessageRepository.insert(fid, "ai", "回复1", 1)
        m3 = MessageRepository.insert(fid, "user", "消息2", 2)

        MailSyncScheduler.mark_sent(fid, m3)
        friend = FriendRepository.get_by_id(fid)
        assert friend["last_sent_message_id"] == m3
        assert friend["last_sent_at"]  # 已记录发送时间

        # 下次 due_info 应返回空（无新消息）
        info = MailSyncScheduler.due_info(fid)
        assert len(info["messages"]) == 0

    def test_never_sent_friend_sends_on_enable(self):
        """首次启用即发（last_sent_at 为空）。"""
        fid = _make_friend_with_mail_sync()
        friend = FriendRepository.get_by_id(fid)
        assert friend["last_sent_at"] == ""
        due = MailSyncScheduler.sync_due_friends()
        assert fid in due

    def test_minute_level_cycle(self):
        """分钟级测试周期："5min" 按分钟间隔判定到期。"""
        from datetime import datetime, timedelta
        fid = FriendRepository.insert(
            name="分钟测试", remark="", system_prompt="",
            mail_sync_enable=1, mail_receiver_address="a@t.com",
            mail_sync_cycle="5min",
        )
        # 从未发送 → 立即到期
        assert fid in MailSyncScheduler.sync_due_friends()
        # 3 分钟前发送 → 未满 5 分钟，不到期
        three_min_ago = (datetime.now() - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
        FriendRepository.update(fid, last_sent_at=three_min_ago)
        assert fid not in MailSyncScheduler.sync_due_friends()
        # 6 分钟前发送 → 已超 5 分钟，到期
        six_min_ago = (datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S")
        FriendRepository.update(fid, last_sent_at=six_min_ago)
        assert fid in MailSyncScheduler.sync_due_friends()

    def test_daily_cycle_not_due_within_24h(self):
        """daily 周期：2 小时前发送过则不到期。

        回归：last_sent_at 曾存 UTC 时间，与本地 now 比较会差数小时，
        导致周期判定永远"到期"。现在存本地时间，比较正确。
        """
        from datetime import datetime, timedelta
        fid = _make_friend_with_mail_sync()  # 默认 daily
        two_hours_ago = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        FriendRepository.update(fid, last_sent_at=two_hours_ago)
        assert fid not in MailSyncScheduler.sync_due_friends()

    def test_manually_created_friend_can_configure_mail_sync(self):
        """手动创建的好友可以配置邮件同步（无 authorizer_email）。"""
        # 手动创建好友（无 authorizer_email）
        fid = FriendRepository.insert(
            name="手动好友",
            remark="",
            system_prompt="你是一个助手。",
            mail_sync_enable=1,
            mail_receiver_address="partner@example.com",
            mail_sync_cycle="weekly",
        )
        friend = FriendRepository.get_by_id(fid)
        # 手动创建的好友没有 authorizer_email
        assert friend["authorizer_email"] == ""
        # 邮件同步字段已保存
        assert friend["mail_sync_enable"] == 1
        assert friend["mail_receiver_address"] == "partner@example.com"
        assert friend["mail_sync_cycle"] == "weekly"
        # 应进入待发列表
        due = MailSyncScheduler.sync_due_friends()
        assert fid in due

    def test_asset_imported_friend_mail_sync_readonly(self):
        """资产导入的好友邮件同步字段来自密文，UI 层只读展示。"""
        fid = _make_friend_with_mail_sync()
        friend = FriendRepository.get_by_id(fid)
        assert friend["authorizer_email"] == "author@test.com"
        # 验证只读判断逻辑：有 authorizer_email → 资产导入 → 只读
        is_asset_imported = bool(friend["authorizer_email"])
        assert is_asset_imported is True

    def test_manually_created_friend_dialog_editable(self):
        """手动创建的好友可以配置邮件同步。"""
        fid = FriendRepository.insert(
            name="手动好友2",
            remark="",
            system_prompt="你是一个助手。",
        )
        friend = FriendRepository.get_by_id(fid)
        assert friend["authorizer_email"] == ""
        # 验证可编辑判断逻辑：无 authorizer_email → 手动创建 → 可编辑
        is_asset_imported = bool(friend["authorizer_email"])
        assert is_asset_imported is False
        # 配置邮件同步
        FriendRepository.update(
            fid,
            mail_sync_enable=1,
            mail_receiver_address="partner@example.com",
            mail_sync_cycle="weekly",
        )
        updated = FriendRepository.get_by_id(fid)
        assert updated["mail_sync_enable"] == 1
        assert updated["mail_receiver_address"] == "partner@example.com"
        assert updated["mail_sync_cycle"] == "weekly"
