# V1.4 邮箱附件表迁移测试（TDD 先行）
# 验证 mail_attachments 表存在、mail_cache 新增 has_html/has_attachments 列
import pytest
from shadowtalk.data.database import Database


class TestMailV14Migration:
    def test_mail_attachments_table_exists(self):
        conn = Database.get_connection()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "mail_attachments" in tables

    def test_mail_attachments_columns(self):
        conn = Database.get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mail_attachments)")}
        expected = {"id", "email_id", "filename", "content_type", "size",
                    "content_id", "is_inline", "saved_path", "created_at"}
        assert expected <= cols

    def test_mail_cache_has_new_columns(self):
        conn = Database.get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mail_cache)")}
        assert "has_html" in cols
        assert "has_attachments" in cols

    def test_mail_attachments_insert_and_query(self):
        conn = Database.get_connection()
        cur = conn.execute(
            "INSERT INTO mail_cache (folder, message_id, subject) VALUES (?, ?, ?)",
            ("INBOX", "<test@x.com>", "测试邮件")
        )
        email_id = cur.lastrowid
        conn.execute(
            """INSERT INTO mail_attachments
               (email_id, filename, content_type, size, content_id, is_inline)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (email_id, "test.png", "image/png", 1024, "<cid001>", 1)
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM mail_attachments WHERE email_id=?", (email_id,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["filename"] == "test.png"
        assert rows[0]["is_inline"] == 1
