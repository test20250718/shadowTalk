# tests/test_mail_receiver.py
"""
IMAP 邮件接收测试

覆盖：邮件解析、会话匹配（In-Reply-To/主题短码）、引用过滤、去重。
无 MailHog 时 IMAP 连接测试自动跳过。
"""
import os
import json
import base64
import pytest
from unittest.mock import patch, MagicMock

from shadowtalk.core.mail_receiver import (
    MailReceiver, extract_reply_body, match_session_id,
    RawEmail, MailReceiveError, _extract_body, extract_attachments,
    _html_to_text, _extract_bodies,
)
from shadowtalk.core.asset_import_service import AssetImportService
from shadowtalk.core.crypto_service import get_cipher
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, ProcessedEmailRepository,
)
from shadowtalk.ui.threads.mail_receive_worker import MailReceiveWorker


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
    # 设置 session_id（使用合法 hex 字符）
    FriendRepository.update(fid, email_session_id="a1b2c3d4e5f6a7b8")
    return fid


class TestExtractReplyBody:
    def test_extract_reply_body_strips_quoting(self):
        """剥离 '>' 引用行。"""
        text = "这是回复\n> 这是引用\n> 又一行引用"
        result = extract_reply_body(text)
        assert ">" not in result
        assert "这是回复" in result

    def test_extract_reply_body_strips_on_wrote(self):
        """剥离 'On ... wrote:' 之后内容。"""
        text = "我的回复\nOn 2026-08-19, author@test.com wrote:\n> 原邮件内容"
        result = extract_reply_body(text)
        assert "我的回复" in result
        assert "原邮件内容" not in result

    def test_extract_reply_body_strips_chinese_wrote(self):
        """剥离 163 等中文网页邮箱的 '在 ... 写道：' 引用头及之后内容。"""
        text = ("收到，谢谢\n\n\n\n在 2026-08-22 11:33:42,13701650622@163.com 写道：\n"
                "以下是原邮件内容")
        result = extract_reply_body(text)
        assert result == "收到，谢谢"

    def test_extract_reply_body_strips_before_separator(self):
        """剥离 '——分隔线之后的内容（引用历史）。"""
        text = "最新回复\n——\n旧邮件内容\n更多旧内容"
        result = extract_reply_body(text)
        assert "最新回复" in result
        assert "旧邮件内容" not in result

    def test_extract_reply_body_simple_text(self):
        """纯文本无引用时原样返回。"""
        text = "就是一句简单的回复"
        result = extract_reply_body(text)
        assert result == "就是一句简单的回复"


class TestMatchSessionId:
    def _make_friend(self, fid, session_id, mail_receiver):
        """构造模拟 friend Row。"""
        return {
            "id": fid,
            "email_session_id": session_id,
            "mail_receiver_address": mail_receiver,
        }

    def test_match_session_by_subject_shortcode(self):
        """按主题短码 [ShadowTalk-xxxxxxxx] 匹配。"""
        # session_id 是 uuid4().hex（仅 0-9a-f），短码取前 8 位
        friend = self._make_friend(1, "a1b2c3d4e5f6a7b8", "author@test.com")
        raw = RawEmail(
            message_id="msg1",
            sender="author@test.com",
            subject="[ShadowTalk-a1b2c3d4] 测试分身聊天记录",
            in_reply_to="",
            references="",
            body_text="回复内容",
            date="",
        )
        result = match_session_id(raw, [friend])
        assert result is not None
        assert result["id"] == 1

    def test_match_session_by_in_reply_to(self):
        """按 In-Reply-To 头匹配。"""
        friend = self._make_friend(1, "a1b2c3d4e5f6a7b8", "author@test.com")
        raw = RawEmail(
            message_id="msg2",
            sender="author@test.com",
            subject="回复：聊天记录",
            in_reply_to="a1b2c3d4e5f6a7b8@shadowtalk.local",
            references="",
            body_text="回复内容",
            date="",
        )
        result = match_session_id(raw, [friend])
        assert result is not None
        assert result["id"] == 1

    def test_match_session_by_references(self):
        """按 References 头匹配。"""
        friend = self._make_friend(1, "a1b2c3d4e5f6a7b8", "author@test.com")
        raw = RawEmail(
            message_id="msg3",
            sender="author@test.com",
            subject="回复",
            in_reply_to="",
            references="a1b2c3d4e5f6a7b8@shadowtalk.local other-id",
            body_text="回复内容",
            date="",
        )
        result = match_session_id(raw, [friend])
        assert result is not None
        assert result["id"] == 1

    def test_match_session_no_match(self):
        """无匹配时返回 None。"""
        friend = self._make_friend(1, "a1b2c3d4e5f6a7b8", "author@test.com")
        raw = RawEmail(
            message_id="msg4",
            sender="other@test.com",
            subject="无关邮件",
            in_reply_to="",
            references="",
            body_text="内容",
            date="",
        )
        result = match_session_id(raw, [friend])
        assert result is None


class TestProcessedEmailRepository:
    def test_exists_and_record(self):
        """记录已处理邮件后 exists 返回 True。"""
        # 创建真实好友（FK 约束需要）
        fid = _make_friend_with_session()
        assert not ProcessedEmailRepository.exists("test-msg-1")
        ProcessedEmailRepository.record("test-msg-1", fid, "human_reply")
        assert ProcessedEmailRepository.exists("test-msg-1")

    def test_record_idempotent(self):
        """重复记录不报错（INSERT OR IGNORE）。"""
        fid = _make_friend_with_session()
        ProcessedEmailRepository.record("test-msg-2", fid, "revoked")
        ProcessedEmailRepository.record("test-msg-2", fid, "revoked")  # 重复
        assert ProcessedEmailRepository.exists("test-msg-2")


class TestMailReceiverMock:
    def test_fetch_recent_parses_headers(self):
        """mock IMAP：解析出 In-Reply-To/Subject/正文。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")

        # 构造 mock 邮件
        from email.mime.text import MIMEText
        mock_email = MIMEText("测试正文", "plain", "utf-8")
        mock_email["Message-ID"] = "<test123@external.com>"
        mock_email["From"] = "author@test.com"
        mock_email["Subject"] = "[ShadowTalk-sess1234] 聊天记录"
        mock_email["In-Reply-To"] = "<sess1234567890ab@shadowtalk.local>"
        mock_email["Date"] = "Wed, 19 Aug 2026 10:00:00 +0800"

        mock_raw = mock_email.as_bytes()

        # mock imaplib
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1"])
            mock_conn.fetch.return_value = ("OK", [(b"1", mock_raw)])

            results = receiver.fetch_recent()
            assert len(results) == 1
            assert results[0].sender == "author@test.com"
            assert "ShadowTalk-sess1234" in results[0].subject
            assert "sess1234567890ab" in results[0].in_reply_to
            assert "测试正文" in results[0].body_text
            # 163 兼容：登录后必须发送 ID 命令（否则 SELECT 被
            # "Unsafe Login" 拒绝）
            id_calls = [c for c in mock_conn._simple_command.call_args_list
                        if c.args[0] == "ID"]
            assert len(id_calls) == 1

    def test_fetch_recent_uses_since_not_unseen(self):
        """搜索条件必须是 SINCE 日期窗口而非 UNSEEN——用户先读过回信
        （服务器已置已读标志）时 UNSEEN 永远查不到该邮件。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b""])

            receiver.fetch_recent()
            criteria = mock_conn.search.call_args[0][1]
            assert criteria.startswith("SINCE ")
            assert "UNSEEN" not in criteria
            # 日期格式 dd-Mon-yyyy（英文月份缩写）
            import re as _re
            assert _re.match(r"^SINCE \d{2}-(Jan|Feb|Mar|Apr|May|Jun|"
                             r"Jul|Aug|Sep|Oct|Nov|Dec)-\d{4}$", criteria)

    def test_fetch_recent_select_rejected_raises(self):
        """SELECT 被拒（如 163 未发 ID 时的 Unsafe Login）必须转为
        MailReceiveError——imaplib 对 NO 不抛异常，不自查返回值的话
        错误会延迟到 search 处以晦涩的 'illegal in state AUTH' 出现。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = (
                "NO", [b"SELECT Unsafe Login. Please contact kefu@188.com"])

            with pytest.raises(MailReceiveError, match="打开收件箱失败"):
                receiver.fetch_recent()

    def test_fetch_recent_imap_error(self):
        """IMAP 错误转为 MailReceiveError。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            import imaplib
            mock_imap.side_effect = imaplib.IMAP4.error("认证失败")
            with pytest.raises(MailReceiveError):
                receiver.fetch_recent()


class TestDeleteMessages:
    r"""delete_messages：按 Message-ID 服务器删除（\Deleted + EXPUNGE）。"""

    def test_delete_marks_and_expunges(self):
        r"""命中邮件打 \Deleted 标记并 EXPUNGE。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"3"])

            n = receiver.delete_messages(["abc123@x.com"])

            assert n == 1
            # 按 Message-ID 搜索（子串匹配，无需 <>）
            search_criteria = mock_conn.search.call_args[0][1]
            assert 'HEADER Message-ID "abc123@x.com"' in search_criteria
            # 打了 \Deleted 标记
            store_args = mock_conn.store.call_args[0]
            assert store_args[0] == b"3"
            assert "\\Deleted" in store_args[2]
            mock_conn.expunge.assert_called_once()
            mock_conn.logout.assert_called_once()

    def test_delete_no_match_returns_zero(self):
        """服务器上找不到该 Message-ID 时返回 0（不报错）。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b""])

            assert receiver.delete_messages(["notexist@x.com"]) == 0
            mock_conn.store.assert_not_called()

    def test_delete_select_rejected_raises(self):
        """SELECT 被拒转 MailReceiveError（与 fetch_recent 同守卫）。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("NO", [b"Unsafe Login"])

            with pytest.raises(MailReceiveError, match="打开收件箱失败"):
                receiver.delete_messages(["abc@x.com"])

    def test_delete_empty_mid_skipped(self):
        r"""空 Message-ID 跳过删除（`'' in 任意串` 恒 True，会误删整箱）。"""
        receiver = MailReceiver("imap.test.com", "user", "pass")
        with patch("shadowtalk.core.mail_receiver.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1 2 3"])

            # 空 mid（旧数据）与纯空白 mid 都必须被跳过
            assert receiver.delete_messages(["", "   "]) == 0
            mock_conn.store.assert_not_called()


def _make_gitlab_like_email():
    """构造 GitLab 日报式邮件：HTML 正文 + .html/.md 文本附件。

    真实结构（IMAP 实测）：
    multipart/mixed [
        text/html（无文件名，真正文）,
        text/html attachment（.html 报告）,
        text/plain attachment（.md 报告）,
    ]
    """
    import email.mime.multipart
    import email.mime.text
    from email.mime.application import MIMEApplication

    msg = email.mime.multipart.MIMEMultipart("mixed")
    body = email.mime.text.MIMEText(
        "<html><body><p>Code Review 摘要</p><p>3 commits</p></body></html>",
        "html", "utf-8")
    msg.attach(body)

    html_att = email.mime.text.MIMEText("# 完整报告 HTML", "html", "utf-8")
    html_att.add_header(
        "Content-Disposition", "attachment",
        filename="daily_report.html")
    msg.attach(html_att)

    md_att = email.mime.text.MIMEText("# Code Review Report 完整版", "plain", "utf-8")
    md_att.add_header(
        "Content-Disposition", "attachment",
        filename="daily_report.md")
    msg.attach(md_att)
    return msg


class TestExtractBody:
    """_extract_body：正文绝不取自附件 part。"""

    def test_gitlab_style_html_body_with_text_attachments(self):
        """HTML 正文 + .md 附件 → 正文是 HTML 去标签，不是 .md 附件内容。"""
        body = _extract_body(_make_gitlab_like_email())
        assert "Code Review 摘要" in body
        assert "3 commits" in body
        # 附件内容绝不能混进正文（此前 .md 附件被当正文显示）
        assert "完整版" not in body
        assert "完整报告" not in body

    def test_plain_body_preferred_over_html(self):
        """multipart/alternative（plain + html）→ 优先纯文本。"""
        import email.mime.multipart
        import email.mime.text
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg.attach(email.mime.text.MIMEText("纯文本正文", "plain", "utf-8"))
        msg.attach(email.mime.text.MIMEText("<p>HTML 正文</p>", "html", "utf-8"))
        assert _extract_body(msg) == "纯文本正文"

    def test_non_multipart_text_email(self):
        """单 part 纯文本邮件照常提取。"""
        import email.mime.text
        msg = email.mime.text.MIMEText("普通正文", "plain", "utf-8")
        assert _extract_body(msg) == "普通正文"


class TestExtractAttachments:
    """extract_attachments：文本类附件（.md/.html/.txt）必须提取。"""

    def test_gitlab_style_text_attachments_extracted(self):
        """GitLab 日报的 .html/.md 附件 → 2 个附件，正文不算附件。"""
        atts = extract_attachments(_make_gitlab_like_email())
        names = {a["filename"] for a in atts}
        assert names == {"daily_report.html", "daily_report.md"}
        # 都是非内联普通附件（阅读窗格附件栏可下载）
        assert all(a["is_inline"] == 0 for a in atts)
        # 附件带 payload（可落盘）
        assert all(a["size"] > 0 for a in atts)

    def test_plain_body_not_attachment(self):
        """无文件名的 text/plain 正文 → 不进附件列表。"""
        import email.mime.text
        msg = email.mime.text.MIMEText("正文而已", "plain", "utf-8")
        assert extract_attachments(msg) == []


class TestHtmlToText:
    """_html_to_text：块级标签换行、script/style 剔除。"""

    def test_basic_conversion(self):
        assert _html_to_text("<p>第一段</p><p>第二段</p>") == "第一段\n\n第二段"

    def test_script_style_skipped(self):
        result = _html_to_text(
            "<style>.a{color:red}</style><p>正文</p>"
            "<script>alert(1)</script>")
        assert "正文" in result
        assert "color" not in result
        assert "alert" not in result


class TestExtractBodies:
    """_extract_bodies：同时返回纯文本与 HTML 原文正文。"""

    def test_gitlab_style_returns_html_body(self):
        """HTML 正文邮件 → html 返回原文（含 <table> 标记），plain 为去标签文本。"""
        plain, html = _extract_bodies(_make_gitlab_like_email())
        assert "<p>" in html and "Code Review 摘要" in html
        assert "Code Review 摘要" in plain and "<" not in plain

    def test_plain_email_html_empty(self):
        """纯文本邮件 → html 为空串。"""
        import email.mime.text
        msg = email.mime.text.MIMEText("纯文本", "plain", "utf-8")
        plain, html = _extract_bodies(msg)
        assert plain == "纯文本"
        assert html == ""


class TestSanitizeEmailHtml:
    """_sanitize_email_html：剔除脚本/事件/js 协议（防御纵深）。"""

    def test_strips_script_and_style(self):
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            "<style>.x{}</style><p>正文</p>"
            "<script>alert(1)</script><iframe src='x'></iframe>")
        assert "正文" in result
        assert "script" not in result.lower()
        assert "iframe" not in result.lower()

    def test_strips_event_handlers(self):
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            '<p onclick="evil()" onmouseover=\'x\'>正文</p>')
        assert "onclick" not in result
        assert "onmouseover" not in result
        assert "正文" in result

    def test_neutralizes_javascript_urls(self):
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            '<a href="javascript:alert(1)">点我</a>')
        assert "javascript:" not in result
        assert "点我" in result

    def test_normal_html_preserved(self):
        """普通内容标签不变，仅注入表格居中对齐。"""
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        table = '<table><tr><td>项目</td><td>值</td></tr></table>'
        result = _sanitize_email_html(table)
        # 内容与结构保留，表格被注入 align="center"（居中布局惯例）
        assert '<tr><td>项目</td><td>值</td></tr>' in result
        assert '<table align="center">' in result

    def test_caps_oversized_pixel_widths(self):
        """超窗格像素宽度收敛为卡片宽（防撑爆），小宽度保留。"""
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            '<table width="100%"><tr><td align="center">'
            '<table width="700"><tr><td width="20">x</td>'
            '</tr></table></td></tr></table>',
            max_width=500, fill_px=480)
        # 700 > 500 → 收敛为卡片宽 480
        assert 'width="700"' not in result
        assert 'width="480"' in result
        # 20 < 500 → 保留原值
        assert 'width="20"' in result

    def test_full_width_percent_converted_to_fill_px(self):
        """表格 100% 宽 → 卡片像素宽（Qt 嵌套表格不吃百分比会缩到内容宽）。"""
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            '<table width="100%"><tr><td align="center">'
            '<table width="700"><tr><td>卡片</td></tr></table>'
            '</td></tr></table>',
            max_width=741, fill_px=700)
        # 表格的 100% → 700px（撑满居中容器）
        assert 'width="100%"' not in result
        assert result.count('width="700"') == 2  # 外层转换 + 内层保留

    def test_small_pixel_width_kept_when_wide_pane(self):
        """窗格够宽时 700px 卡片原样保留（网页版居中效果）。"""
        from shadowtalk.ui.widgets.mail_widget import _sanitize_email_html
        result = _sanitize_email_html(
            '<table width="700"><tr><td>卡片</td></tr></table>',
            max_width=741, fill_px=700)
        assert 'width="700"' in result


class TestMailReceiveWorkerSelfSent:
    """回归：自己发给自己的邮件（sender == IMAP 账号）必须跳过，防死循环。"""

    @staticmethod
    def _make_worker(imap_user="me@test.com"):
        return MailReceiveWorker({
            "host": "imap.test.com", "user": imap_user, "password": "pass",
            "port": 993, "use_ssl": True,
        })

    @staticmethod
    def _mock_fetch(raw_emails):
        """返回一个替换 MailReceiver 的 mock 类。"""
        class MockReceiver:
            def __init__(self, *a, **kw):
                pass
            def fetch_recent(self, days=7):
                return raw_emails
        return MockReceiver

    def test_self_sent_skipped_no_human_reply(self, monkeypatch):
        """sender 为自己的邮件 → 不触发 human_reply，仅记录已处理。"""
        from shadowtalk.core.mail_receiver import RawEmail
        raw = RawEmail(
            message_id="self-1@external.com",
            sender="me@test.com",  # == imap_user
            subject="[ShadowTalk-sess1234] 聊天记录",
            in_reply_to="<sess1234567890ab@shadowtalk.local>",
            references="", body_text="这是聊天记录摘要",
            date="Wed, 19 Aug 2026 10:00:00 +0800",
        )
        worker = self._make_worker("me@test.com")
        monkeypatch.setattr(
            "shadowtalk.ui.threads.mail_receive_worker.MailReceiver",
            self._mock_fetch([raw]),
        )
        # 好友列表非空（否则提前 return），但 self_sent 检查在匹配之前
        from shadowtalk.data.repositories import FriendRepository
        monkeypatch.setattr(FriendRepository, "get_all", lambda: [])

        replies = []
        worker.human_reply.connect(lambda *a: replies.append(a))
        worker.run()

        assert replies == []  # 未触发 human_reply
        from shadowtalk.data.repositories import ProcessedEmailRepository
        assert ProcessedEmailRepository.exists("self-1@external.com")

    def test_external_sender_still_processed(self, monkeypatch):
        """sender 非自己 → 正常走匹配流程（对照：确保只过滤自己）。"""
        # _make_friend_with_session 固定设 session_id = a1b2c3d4e5f6a7b8
        fid = _make_friend_with_session()
        from shadowtalk.core.mail_receiver import RawEmail
        raw = RawEmail(
            message_id="ext-1@external.com",
            sender="author@test.com",  # 非自己
            subject="[ShadowTalk-a1b2c3d4] 聊天记录",
            in_reply_to="<a1b2c3d4e5f6a7b8@shadowtalk.local>",
            references="", body_text="这是回信",
            date="Wed, 19 Aug 2026 10:00:00 +0800",
        )
        worker = self._make_worker("me@test.com")
        monkeypatch.setattr(
            "shadowtalk.ui.threads.mail_receive_worker.MailReceiver",
            self._mock_fetch([raw]),
        )
        from shadowtalk.data.repositories import FriendRepository
        monkeypatch.setattr(FriendRepository, "get_all",
                            lambda: [FriendRepository.get_by_id(fid)])

        replies = []
        worker.human_reply.connect(lambda *a: replies.append(a))
        worker.run()

        assert len(replies) == 1  # 正常触发 human_reply
        assert replies[0][0] == fid
