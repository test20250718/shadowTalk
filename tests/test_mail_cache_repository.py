# tests/test_mail_cache_repository.py
# 邮箱客户端邮件缓存仓库测试（Task 1: MailCacheRepository）
import pytest
from shadowtalk.data.repositories import MailCacheRepository


class TestMailCacheRepository:
    SAMPLE_EMAILS = [
        {
            "message_id": "<msg1@test.com>",
            "sender": "张三",
            "sender_addr": "zhangsan@test.com",
            "subject": "测试邮件一",
            "body_text": "这是第一封测试邮件的正文。",
            "received_at": "2026-08-27 10:00:00",
        },
        {
            "message_id": "<msg2@test.com>",
            "sender": "李四",
            "sender_addr": "lisi@test.com",
            "subject": "测试邮件二",
            "body_text": "这是第二封测试邮件的正文。",
            "received_at": "2026-08-27 11:00:00",
        },
    ]

    def test_upsert_and_get_by_folder(self):
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        assert len(emails) == 2
        # 按 received_at DESC 排序：测试邮件二（11:00）在前
        assert emails[0]["subject"] == "测试邮件二"
        assert emails[1]["subject"] == "测试邮件一"

    def test_upsert_deduplicates(self):
        """同一 message_id 重复 upsert 不产生重复行。"""
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        assert len(emails) == 2

    def test_get_by_folder_ordered_by_received_at_desc(self):
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        assert emails[0]["subject"] == "测试邮件二"

    def test_get_by_folder_with_limit(self):
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX", limit=1)
        assert len(emails) == 1

    def test_get_by_id(self):
        MailCacheRepository.upsert_batch("INBOX", [self.SAMPLE_EMAILS[0]])
        emails = MailCacheRepository.get_by_folder("INBOX")
        eid = emails[0]["id"]
        row = MailCacheRepository.get_by_id(eid)
        assert row["subject"] == "测试邮件一"

    def test_body_html_persisted(self):
        """HTML 原文正文入库并可读回（V1.5 富文本渲染）。"""
        email = dict(self.SAMPLE_EMAILS[0])
        email["body_html"] = "<table><tr><td>摘要</td></tr></table>"
        MailCacheRepository.upsert_batch("INBOX", [email])
        row = MailCacheRepository.get_by_folder("INBOX")[0]
        assert row["body_html"] == "<table><tr><td>摘要</td></tr></table>"

    def test_body_html_updated_on_conflict(self):
        """同 message_id 重新拉取时 body_html 更新到最新。"""
        email = dict(self.SAMPLE_EMAILS[0])
        email["body_html"] = "<p>旧正文</p>"
        MailCacheRepository.upsert_batch("INBOX", [email])
        email["body_html"] = "<p>新正文</p>"
        MailCacheRepository.upsert_batch("INBOX", [email])
        row = MailCacheRepository.get_by_folder("INBOX")[0]
        assert row["body_html"] == "<p>新正文</p>"

    def test_mark_read(self):
        MailCacheRepository.upsert_batch("INBOX", [self.SAMPLE_EMAILS[0]])
        emails = MailCacheRepository.get_by_folder("INBOX")
        eid = emails[0]["id"]
        MailCacheRepository.mark_read(eid)
        row = MailCacheRepository.get_by_id(eid)
        assert row["is_read"] == 1

    def test_get_folders(self):
        MailCacheRepository.upsert_batch("INBOX", [self.SAMPLE_EMAILS[0]])
        MailCacheRepository.upsert_batch("Sent", [self.SAMPLE_EMAILS[1]])
        folders = MailCacheRepository.get_folders()
        assert "INBOX" in folders
        assert "Sent" in folders

    def test_different_folders_independent(self):
        MailCacheRepository.upsert_batch("INBOX", [self.SAMPLE_EMAILS[0]])
        MailCacheRepository.upsert_batch("Sent", [self.SAMPLE_EMAILS[1]])
        inbox = MailCacheRepository.get_by_folder("INBOX")
        sent = MailCacheRepository.get_by_folder("Sent")
        assert len(inbox) == 1
        assert len(sent) == 1
        assert inbox[0]["subject"] == "测试邮件一"
        assert sent[0]["subject"] == "测试邮件二"

    def test_get_by_folder_returns_dicts(self):
        """回归（用户报告：刷新后邮件列表空白）：
        get_by_folder 必须返回 dict 而非 sqlite3.Row——
        _EmailListItem 用 email.get(...) 访问字段，Row 没有该方法。"""
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        assert isinstance(emails[0], dict)
        # .get() 访问不抛 AttributeError（带默认值兜底）
        assert emails[0].get("is_read", 0) == 0

    def test_get_by_id_returns_dict(self):
        """回归：get_by_id 返回 dict，供 .get() 访问 has_html 等字段。"""
        MailCacheRepository.upsert_batch("INBOX", [self.SAMPLE_EMAILS[0]])
        emails = MailCacheRepository.get_by_folder("INBOX")
        row = MailCacheRepository.get_by_id(emails[0]["id"])
        assert isinstance(row, dict)
        assert row.get("has_html", 0) == 0

    def test_get_attachments_returns_dicts(self):
        """回归：get_attachments 返回 dict 列表。"""
        MailCacheRepository.upsert_batch("INBOX", [{
            **self.SAMPLE_EMAILS[0],
            "attachments": [{
                "filename": "test.txt",
                "content_type": "text/plain",
                "size": 100,
                "content_id": "",
                "is_inline": 0,
                "payload": b"data",
            }],
        }])
        emails = MailCacheRepository.get_by_folder("INBOX")
        atts = MailCacheRepository.get_attachments(emails[0]["id"])
        assert len(atts) == 1
        assert isinstance(atts[0], dict)
        assert atts[0].get("filename") == "test.txt"

    def test_reupsert_does_not_duplicate_attachments(self):
        """同一邮件重复 upsert（自动刷新场景）附件不累积。

        此前 _save_attachments 只增不删，每 3 分钟刷新一次就多存一份，
        附件栏显示几十个重复附件（用户报告）。
        """
        email = {
            **self.SAMPLE_EMAILS[0],
            "attachments": [
                {"filename": "a.md", "content_type": "text/plain",
                 "size": 10, "content_id": "", "is_inline": 0,
                 "payload": b"md-content"},
                {"filename": "b.html", "content_type": "text/html",
                 "size": 20, "content_id": "", "is_inline": 0,
                 "payload": b"<p>html</p>"},
            ],
        }
        # 模拟连续 3 次自动刷新重新拉取同一封邮件
        for _ in range(3):
            MailCacheRepository.upsert_batch("INBOX", [email])
        eid = MailCacheRepository.get_by_folder("INBOX")[0]["id"]
        atts = MailCacheRepository.get_attachments(eid)
        assert len(atts) == 2
        assert {a["filename"] for a in atts} == {"a.md", "b.html"}

    def test_delete_removes_email_and_attachments(self):
        """delete：删邮件行（级联附件行）+ 清附件目录。"""
        import shutil
        from shadowtalk.config.paths import get_base_dir
        MailCacheRepository.upsert_batch("INBOX", [
            self.SAMPLE_EMAILS[0],
            {**self.SAMPLE_EMAILS[1],
             "attachments": [{
                 "filename": "a.txt", "content_type": "text/plain",
                 "size": 10, "content_id": "", "is_inline": 0,
                 "payload": b"xxx",
             }]},
        ])
        emails = MailCacheRepository.get_by_folder("INBOX")
        target = next(e for e in emails if e["has_attachments"])
        att_dir = get_base_dir() / "mail_attachments" / str(target["id"])
        assert att_dir.exists()  # 附件已落盘
        assert len(MailCacheRepository.get_attachments(target["id"])) == 1

        MailCacheRepository.delete(target["id"])

        assert MailCacheRepository.get_by_id(target["id"]) is None
        assert MailCacheRepository.get_attachments(target["id"]) == []
        assert not att_dir.exists()  # 目录已清理
        # 另一封不受影响
        remaining = MailCacheRepository.get_by_folder("INBOX")
        assert len(remaining) == 1
