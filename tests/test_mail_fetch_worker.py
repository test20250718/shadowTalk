# tests/test_mail_fetch_worker.py
"""MailFetchWorker 辅助函数测试。

重点：缺 Message-ID 头的邮件（如 GitLab Code Review 日报）必须生成
稳定且互不相同的合成 ID——此前两封空 mid 邮件在 mail_cache 的
UNIQUE(folder, message_id) 上撞键，后拉取的覆盖先拉取的，
用户看到"少收了一封邮件"。
"""
from shadowtalk.core.mail_receiver import RawEmail
from shadowtalk.ui.threads.mail_fetch_worker import _fallback_message_id


def _make_raw(subject: str, body: str, date: str = "Thu, 3 Sep 2026 09:23:35 +0800",
              sender: str = "gitlab@raise3d.com") -> RawEmail:
    return RawEmail(
        message_id="",  # 缺 Message-ID 头的邮件
        sender=sender,
        subject=subject,
        in_reply_to="",
        references="",
        body_text=body,
        date=date,
    )


class TestFallbackMessageId:

    def test_different_emails_get_different_ids(self):
        """两封内容不同的空 mid 邮件 → 合成 ID 不同（不再互相覆盖）。"""
        daily2 = _make_raw("[Code Review] daily-2-commits", "# Report day 2")
        daily3 = _make_raw(
            "[Code Review] daily-3-commits", "# Report day 3",
            date="Fri, 4 Sep 2026 10:16:35 +0800")
        id2 = _fallback_message_id(daily2)
        id3 = _fallback_message_id(daily3)
        assert id2 != id3
        assert id2.startswith("no-mid-")
        assert id3.startswith("no-mid-")

    def test_same_email_stable_id(self):
        """同一封邮件多次拉取 → 合成 ID 相同（去重仍然有效）。"""
        raw = _make_raw("[Code Review] daily-2-commits", "# Report day 2")
        assert _fallback_message_id(raw) == _fallback_message_id(raw)

    def test_body_difference_only_still_distinct(self):
        """同主题同日期但正文不同的两封邮件（如连续两封日报）也不撞键。"""
        a = _make_raw("日报", "第一封内容")
        b = _make_raw("日报", "第二封内容，内容变了")
        assert _fallback_message_id(a) != _fallback_message_id(b)
