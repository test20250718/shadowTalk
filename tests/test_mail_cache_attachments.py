# tests/test_mail_cache_attachments.py
# 邮箱缓存附件持久化测试（Task 4: MailCacheRepository 附件方法）
import os
import pytest
from shadowtalk.data.repositories import MailCacheRepository


class TestMailCacheAttachments:
    SAMPLE_EMAILS = [{
        "message_id": "<att@test.com>",
        "sender": "发件人",
        "sender_addr": "from@test.com",
        "subject": "带附件的邮件",
        "body_text": "正文",
        "received_at": "2026-08-28 10:00:00",
    }]

    def _make_email_with_attachment(self):
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        email_id = emails[0]["id"]
        attachments = [{
            "filename": "test.png",
            "content_type": "image/png",
            "size": 1024,
            "content_id": "<cid001>",
            "is_inline": 1,
            "payload": b"fake image data",
        }]
        return email_id, attachments

    def test_save_and_get_attachments(self):
        email_id, attachments = self._make_email_with_attachment()
        MailCacheRepository.save_attachments(email_id, attachments)
        result = MailCacheRepository.get_attachments(email_id)
        assert len(result) == 1
        assert result[0]["filename"] == "test.png"
        assert result[0]["is_inline"] == 1

    def test_save_attachments_writes_files(self):
        email_id, attachments = self._make_email_with_attachment()
        MailCacheRepository.save_attachments(email_id, attachments)
        result = MailCacheRepository.get_attachments(email_id)
        saved_path = result[0]["saved_path"]
        assert saved_path
        assert os.path.exists(saved_path)
        with open(saved_path, 'rb') as f:
            assert f.read() == b"fake image data"

    def test_get_attachments_empty(self):
        MailCacheRepository.upsert_batch("INBOX", self.SAMPLE_EMAILS)
        emails = MailCacheRepository.get_by_folder("INBOX")
        email_id = emails[0]["id"]
        result = MailCacheRepository.get_attachments(email_id)
        assert result == []

    def test_cascade_delete(self):
        email_id, attachments = self._make_email_with_attachment()
        MailCacheRepository.save_attachments(email_id, attachments)
        from shadowtalk.data.database import Database
        with Database.transaction() as conn:
            conn.execute("DELETE FROM mail_cache WHERE id=?", (email_id,))
        result = MailCacheRepository.get_attachments(email_id)
        assert result == []
