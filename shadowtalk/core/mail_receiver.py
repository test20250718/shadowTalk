# shadowtalk/core/mail_receiver.py
"""
IMAP 邮件接收（stdlib imaplib，无新依赖）。

拉取新邮件 -> 解析头部 -> 过滤引用历史 -> 匹配会话。
"""
import imaplib
import email
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


def fallback_message_id(sender: str, subject: str, date: str,
                        body_text: str) -> str:
    """为缺 Message-ID 头的邮件生成稳定合成 ID（no-mid- 前缀）。

    部分邮件（如 GitLab Code Review 日报）没有 Message-ID 头，
    入库时用本函数合成 ID 去重。合成规则：发件人+主题+日期+正文前
    500 字的 MD5。同一封邮件多次拉取生成相同 ID（去重仍有效）；
    删除时用同一规则在服务器邮件上反推比对（无 Message-ID 的邮件
    无法按头搜索，按 Message-ID 删除永远找不到——用户报告：
    GitLab 日报在服务器上永远删不掉）。
    """
    basis = "|".join([
        sender or "",
        subject or "",
        date or "",
        (body_text or "")[:500],
    ])
    return "no-mid-" + hashlib.md5(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class RawEmail:
    """解析后的原始邮件数据结构。"""
    message_id: str
    sender: str
    subject: str
    in_reply_to: str
    references: str
    body_text: str
    date: str
    # V1.4 邮箱增强：附件与 HTML 标记（默认值保证旧调用方兼容）
    content_type: str = ""
    has_html: bool = False
    attachments: list = field(default_factory=list)
    # V1.5：非附件 text/html 正文的原文（供阅读窗格渲染富文本/表格；
    # 默认空串保证旧调用方与旧测试兼容）
    body_html: str = ""


class MailReceiveError(Exception):
    """邮件接收失败。"""
    pass


# IMAP 日期搜索的月份必须用英文缩写（22-Aug-2026）；
# strftime 的 %b 受系统区域影响（zh-CN 输出中文月份会被服务器拒绝）
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(d) -> str:
    """datetime → IMAP 搜索日期 'dd-Mon-yyyy'（区域无关）。"""
    return f"{d.day:02d}-{_MONTHS_EN[d.month - 1]}-{d.year}"


class MailReceiver:
    """IMAP 邮件接收器。"""

    def __init__(self, imap_host: str, imap_user: str, imap_password: str,
                 imap_port: int = 993, use_ssl: bool = True):
        self.imap_host = imap_host
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.imap_port = imap_port
        self.use_ssl = use_ssl

    @staticmethod
    def _send_client_id(mail):
        """登录后发送 IMAP ID 命令（RFC 2971，客户端标识）。

        163 等 NetEase 邮箱强制要求：不发 ID，SELECT 会返回
        'Unsafe Login. Please contact kefu@188.com'（且 imaplib 的
        select 对 NO 不抛异常，连接停在 AUTH 态，后续 search 直接报
        'illegal in state AUTH'——用户报告：163 邮箱一直收不到回信）。
        其他不支持 ID 的服务器会回 BAD，忽略即可，无副作用。
        """
        try:
            imaplib.Commands["ID"] = ("AUTH", "SELECTED")
            typ, dat = mail._simple_command(
                "ID", '("name" "ShadowTalk" "version" "1.0")')
            mail._untagged_response(typ, dat, "ID")
        except Exception:
            pass  # 服务器不支持 ID（非 NetEase）或已断开——不阻塞主流程

    def delete_messages(self, message_ids: list[str]) -> int:
        r"""在服务器按 Message-ID 删除邮件（\Deleted 标记 + EXPUNGE）。

        返回实际删除的邮件数。message_id 用去尖括号后的形式
        （与 mail_cache.message_id 一致）；HEADER 搜索为子串匹配，
        无需还原 <>。

        搜索策略：先搜 INBOX，未匹配时尝试其他常见文件夹（部分邮箱服务商
        会自动归档/移动邮件）。删除是服务器端永久删除（大多数服务器 EXPUNGE
        即真正移除），调用方需先经用户确认。
        """
        deleted = 0
        try:
            if self.use_ssl:
                mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            else:
                mail = imaplib.IMAP4(self.imap_host, self.imap_port)
            mail.login(self.imap_user, self.imap_password)
            self._send_client_id(mail)

            # INBOX 必须先成功打开（否则是登录/权限问题，应报错而非静默跳过）
            status, data = mail.select("INBOX")
            if status != "OK":
                raise MailReceiveError(
                    f"打开收件箱失败：{data[0] if data else status}")

            for mid in message_ids:
                # 空 Message-ID 防护：按空串搜索/匹配会误中所有邮件
                #（`'' in 任意字符串` 恒为 True），绝不能进入删除流程
                if not mid or not mid.strip():
                    logger.warning("邮件删除：跳过空 Message-ID（防止误删整箱）")
                    continue
                logger.debug("邮件删除：搜索 Message-ID=%r", mid)
                # no-mid-* 是本地合成 ID（邮件无 Message-ID 头），
                # HEADER 搜索永远不可能命中，直接走哈希比对分支
                if not mid.startswith("no-mid-"):
                    # 第一遍：HEADER Message-ID 搜索（INBOX + 其他常见文件夹）
                    n = self._search_and_delete(mail, mid)
                    if n > 0:
                        deleted += n
                        continue
                # 备选：拉取 INBOX 邮件逐条对比（真实 ID 比对 Message-ID 头；
                # no-mid-* 比对内容哈希——无 Message-ID 的邮件唯一的定位方式）
                logger.debug(
                    "邮件删除：HEADER 搜索无结果，尝试拉取对比 Message-ID=%r", mid)
                fallback_ids = self._find_seq_by_message_id(mail, mid)
                if fallback_ids:
                    logger.debug(
                        "邮件删除：拉取对比找到 %d 条匹配（seq: %s）",
                        len(fallback_ids), fallback_ids)
                    for eid in fallback_ids:
                        mail.store(eid, '+FLAGS.SILENT', '(\\Deleted)')
                        deleted += 1
                else:
                    logger.warning(
                        "邮件删除：所有方式均未找到 Message-ID=%r", mid)
            mail.expunge()
            mail.logout()
            return deleted
        except imaplib.IMAP4.error as e:
            logger.error("IMAP 删除错误：%s", e)
            raise MailReceiveError(f"IMAP 删除错误：{e}")
        except Exception as e:
            logger.error("IMAP 删除异常：%s", e)
            raise MailReceiveError(f"IMAP 删除异常：{e}")

    def _search_and_delete(self, mail, mid: str) -> int:
        """在多个文件夹中按 HEADER Message-ID 搜索并标记删除。

        返回实际删除的邮件数（0 表示未找到）。
        每个文件夹 select 失败静默跳过（不同服务器文件夹名差异大，BAD 是常态）。
        """
        folders = ["INBOX", "[Gmail]/Trash", "[Gmail]/All Mail",
                   "Sent", "Archive", "Trash", "Drafts", "Junk"]
        for folder in folders:
            try:
                status, data = mail.select(folder)
            except imaplib.IMAP4.error:
                # 服务器不支持该文件夹名（如 BAD 'Select parameters'）→ 跳过
                logger.debug("邮件删除：文件夹 %s 不可用，跳过", folder)
                continue
            except UnicodeEncodeError:
                # 文件夹名含非 ASCII 字符（如中文）且服务器不支持 → 跳过
                logger.debug("邮件删除：文件夹 %s 编码失败，跳过", folder)
                continue
            if status != "OK":
                continue
            status, data = mail.search(
                None, f'(HEADER Message-ID "{mid}")')
            if status != "OK":
                continue
            ids = data[0].split()
            if ids:
                logger.debug(
                    "邮件删除：在 %s 找到 %d 条匹配（seq: %s）",
                    folder, len(ids), ids)
                for eid in ids:
                    mail.store(eid, '+FLAGS.SILENT', '(\\Deleted)')
                return len(ids)
        return 0

    def _find_seq_by_message_id(self, mail, mid: str) -> list:
        """拉取 INBOX 最近邮件，逐条定位匹配（备选搜索）。

        真实 Message-ID：比对邮件头（部分服务器 HEADER 搜索不稳定时的兜底）。
        no-mid-* 合成 ID：拉取完整邮件，用与入库时相同的哈希算法
        （fallback_message_id）反推比对——无 Message-ID 头的邮件
        唯一的定位方式。

        返回匹配的 sequence number 列表。限制最近 200 封，
        避免全量拉取过慢。
        """
        # 空 mid 防护：`'' in 任意串` 恒为 True，会把整箱邮件全部匹配
        if not mid or not mid.strip():
            return []
        try:
            status, data = mail.select("INBOX")
            if status != "OK":
                return []
            status, data = mail.search(None, "ALL")
            if status != "OK":
                return []
            seq_ids = data[0].split()
            # 只检查最近 200 封（倒序，新邮件更可能被删除）
            seq_ids = seq_ids[-200:] if len(seq_ids) > 200 else seq_ids
            matched = []
            for seq in seq_ids:
                if mid.startswith("no-mid-"):
                    # 合成 ID：拉全文 → 解析 → 同规则哈希比对
                    status, msg_data = mail.fetch(seq, "(RFC822)")
                    if status != "OK":
                        continue
                    parsed = email.message_from_bytes(msg_data[0][1])
                    raw = self._parse_message(parsed)
                    if raw is None:
                        continue
                    if fallback_message_id(
                            raw.sender, raw.subject, raw.date,
                            raw.body_text) == mid:
                        matched.append(seq)
                    continue
                status, msg_data = mail.fetch(
                    seq, "(BODY[HEADER.FIELDS (MESSAGE-ID)])")
                if status != "OK":
                    continue
                raw_header = msg_data[0][1] if msg_data[0] else b""
                header_str = raw_header.decode("utf-8", errors="ignore")
                # 提取 Message-ID 值（去尖括号），与 mid 比较
                found_mid = re.search(
                    r"Message-ID:\s*<?([^>\s]+)>?", header_str, re.IGNORECASE)
                if found_mid:
                    found_stripped = found_mid.group(1).strip("<> \n")
                    if (found_stripped == mid
                            or mid in found_stripped
                            or found_stripped in mid):
                        matched.append(seq)
            return matched
        except Exception as e:
            logger.warning("邮件删除：拉取对比失败：%s", e)
            return []

    def fetch_recent(self, days: int = 7) -> list:
        """拉取最近 N 天的收件箱邮件（不区分已读未读），返回 RawEmail 列表。

        失败抛 MailReceiveError。

        不搜 UNSEEN：用户先在网页/手机邮箱里点开过回信后，服务器即把
        该邮件置为已读，UNSEEN 搜索永远查不到它（用户报告：邮箱里明明
        收到了回信，程序却始终收不到）。改为按日期窗口拉取全部邮件，
        重复处理由 processed_emails 表去重（见 MailReceiveWorker）。
        """
        try:
            if self.use_ssl:
                mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            else:
                mail = imaplib.IMAP4(self.imap_host, self.imap_port)
            mail.login(self.imap_user, self.imap_password)
            # 163 兼容：登录后先报客户端身份，否则 SELECT 被"Unsafe Login"拒绝
            self._send_client_id(mail)

            status, data = mail.select("INBOX")
            if status != "OK":
                # imaplib 对 NO 不抛异常（状态停在 AUTH），必须自查返回值，
                # 否则后续 search 报晦涩的 'illegal in state AUTH'
                raise MailReceiveError(
                    f"打开收件箱失败：{data[0] if data else status}")

            # 按日期窗口搜索（如 SINCE 15-Aug-2026）
            since = _imap_date(datetime.now() - timedelta(days=days))
            status, data = mail.search(None, f"SINCE {since}")
            if status != "OK":
                mail.logout()
                return []

            email_ids = data[0].split()
            results = []
            for eid in email_ids:
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue
                raw_email = msg_data[0][1]
                parsed = email.message_from_bytes(raw_email)
                raw = self._parse_message(parsed)
                if raw:
                    results.append(raw)

            mail.logout()
            return results
        except imaplib.IMAP4.error as e:
            logger.error("IMAP 错误：%s", e)
            raise MailReceiveError(f"IMAP 错误：{e}")
        except Exception as e:
            logger.error("IMAP 异常：%s", e)
            raise MailReceiveError(f"IMAP 异常：{e}")

    @staticmethod
    def _parse_message(msg) -> RawEmail | None:
        """解析 email.message.Message 为 RawEmail。"""
        message_id = msg.get("Message-ID", "").strip("<> \n")
        sender = email.utils.parseaddr(msg.get("From", ""))[1]
        subject = _decode_header(msg.get("Subject", ""))
        in_reply_to = msg.get("In-Reply-To", "").strip("<> \n")
        references = msg.get("References", "").strip()
        date = msg.get("Date", "")

        # 提取正文（纯文本 + HTML 原文）
        body_text, body_html = _extract_bodies(msg)
        if not body_text.strip():
            return None

        # V1.4：记录内容类型与附件信息（供邮箱客户端展示）
        content_type = msg.get_content_type()
        has_html = _has_html_part(msg)
        attachments = extract_attachments(msg)

        return RawEmail(
            message_id=message_id,
            sender=sender,
            subject=subject,
            in_reply_to=in_reply_to,
            references=references,
            body_text=body_text,
            date=date,
            content_type=content_type,
            has_html=has_html,
            attachments=attachments,
            body_html=body_html,
        )


def _decode_header(header_value: str) -> str:
    """解码邮件头部（处理编码的中文主题）。"""
    if not header_value:
        return ""
    decoded_parts = email.header.decode_header(header_value)
    parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return "".join(parts)


def _is_attachment_part(part) -> bool:
    """判断 MIME part 是否是附件（而非正文）。

    有文件名或 Content-Disposition 含 attachment 即视为附件。
    GitLab 等系统邮件的正文是 text/html，同时携带 .md/.html 文本附件
    （Content-Type 也是 text/*）——此前只按 Content-Type 区分，
    附件被当成正文、又永远进不了附件栏（用户报告：附件显示成了正文文本）。
    """
    if part.get_filename():
        return True
    disp = str(part.get("Content-Disposition", "")).lower()
    return "attachment" in disp


class _HTMLTextExtractor(HTMLParser):
    """把 HTML 正文转纯文本（块级标签换行，跳过 script/style）。"""

    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "table", "h1", "h2", "h3",
                   "h4", "h5", "h6", "blockquote", "pre"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        # 压缩连续空行，保留段落间换行
        lines = [ln.strip() for ln in "".join(self._parts).splitlines()]
        out = []
        for ln in lines:
            if ln:
                out.append(ln)
            elif out and out[-1] != "":
                out.append("")
        return "\n".join(out).strip()


def _html_to_text(html_str: str) -> str:
    """HTML 字符串 → 纯文本（解析失败回落正则去标签）。"""
    try:
        extractor = _HTMLTextExtractor()
        extractor.feed(html_str)
        extractor.close()
        return extractor.text()
    except Exception:
        return re.sub(r"<[^>]+>", "", html_str)


def _extract_bodies(msg) -> tuple:
    """提取邮件正文（纯文本, HTML 原文）。

    规则：
    1. 跳过附件 part（有文件名 / attachment 处置）——正文只能是
       "裸" text/plain 或 text/html，绝不把 .md/.txt 附件当正文
    2. 纯文本回落：没有 text/plain 正文时用 text/html 去标签生成
       （GitLab 等系统邮件正文只有 HTML）
    """
    plain = ""
    html = ""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if _is_attachment_part(part):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        content_type = part.get_content_type()
        if content_type == "text/plain" and not plain:
            plain = payload.decode(charset, errors="replace")
        elif content_type == "text/html" and not html:
            html = payload.decode(charset, errors="replace")
    if not plain and html:
        plain = _html_to_text(html)
    return plain, html


def _extract_body(msg) -> str:
    """提取邮件纯文本正文（向后兼容包装）。"""
    return _extract_bodies(msg)[0]


def _has_html_part(msg) -> bool:
    """判断邮件是否包含 text/html 部分（用于前端渲染富文本）。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return True
        return False
    return msg.get_content_type() == "text/html"


def extract_attachments(msg) -> list:
    """从邮件消息中提取附件列表。

    判定标准与 _is_attachment_part 一致：有文件名或 Content-Disposition
    含 attachment 即附件。正文 part（裸 text/plain / text/html）跳过；
    文本类附件（.md/.txt/.csv/.html 等）照常提取——此前 text/* 一律
    跳过导致这类附件永远不显示（用户报告：GitLab 日报的 .md/.html
    附件被当正文显示）。inline（含 Content-ID，HTML 内嵌图片）单独标记。
    """
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if not _is_attachment_part(part):
            continue
        content_type = part.get_content_type()
        filename = part.get_filename() or ''
        content_disposition = str(part.get('Content-Disposition', ''))
        content_id = part.get('Content-ID', '').strip('<>')
        # inline 且不含 attachment 关键字 → 内嵌资源（如 HTML 引用图片）
        is_inline = ('inline' in content_disposition.lower() and
                     'attachment' not in content_disposition.lower())
        payload = part.get_payload(decode=True) or b''
        attachments.append({
            "filename": filename,
            "content_type": content_type,
            "size": len(payload),
            "content_id": f"<{content_id}>" if content_id else "",
            "is_inline": 1 if is_inline else 0,
            "payload": payload,
        })
    return attachments


def extract_reply_body(raw_text: str) -> str:
    """过滤引用历史：剥离 '>' 引用行、'On ... wrote:' 之后内容、签名。"""
    lines = raw_text.split("\n")
    reply_lines = []

    for line in lines:
        stripped = line.strip()
        # 引用行（以 > 开头）
        if stripped.startswith(">"):
            continue
        # 引用分隔线
        if stripped == "——" or stripped == "--":
            break
        # "On ... wrote:" 模式（英文客户端自动追加的引用提示）
        if re.match(r"^On\s.+wrote:\s*$", stripped):
            break
        # "在 ... 写道：" 模式（163 等中文网页邮箱的引用提示）
        if re.match(r"^在\s.+写道[:：]\s*$", stripped):
            break
        # 邮件尾部签名分隔线
        if stripped == "--":
            break
        reply_lines.append(line)

    # 去除尾部空行
    while reply_lines and not reply_lines[-1].strip():
        reply_lines.pop()

    return "\n".join(reply_lines).strip()


def match_session_id(raw: RawEmail, friends: list) -> object:
    """按优先级匹配会话：In-Reply-To/References -> 主题短码 -> sender。

    Args:
        raw: 解析后的邮件
        friends: 好友 Row 列表
    Returns:
        匹配的好友 Row，无匹配返回 None
    """
    # 策略 1：In-Reply-To / References 头匹配（最可靠，但客户端可能剥除）
    if raw.in_reply_to:
        session_id = raw.in_reply_to.split("@")[0]  # 去掉 @shadowtalk.local
        for friend in friends:
            if friend["email_session_id"] == session_id:
                return friend

    if raw.references:
        # references 可能包含多个 ID，取第一个
        first_ref = raw.references.split()[0]
        session_id = first_ref.split("@")[0]
        for friend in friends:
            if friend["email_session_id"] == session_id:
                return friend

    # 策略 2：主题短码匹配 [ShadowTalk-xxxxxxxx]
    subject_match = re.search(r"\[ShadowTalk-([a-f0-9]+)\]", raw.subject)
    if subject_match:
        short_code = subject_match.group(1)
        for friend in friends:
            if friend["email_session_id"] and friend["email_session_id"].startswith(short_code):
                return friend

    return None
