# shadowtalk/ui/threads/mail_fetch_worker.py
"""
邮箱客户端 IMAP 拉取线程（QThread）。

与分身同步的 MailReceiveWorker 不同：本 worker 拉取指定文件夹的全部邮件，
转换为 dict 列表由 emails_fetched 信号发出，由调用方写入 mail_cache 表。
不匹配 session、不插回聊天。
"""
import logging
import email.utils
from datetime import datetime, timezone

from PySide6.QtCore import QThread, Signal

from shadowtalk.core.mail_receiver import MailReceiver, fallback_message_id
from shadowtalk.data.repositories import MailCacheRepository

logger = logging.getLogger(__name__)


def _fallback_message_id(raw) -> str:
    r"""为缺 Message-ID 头的邮件生成稳定合成 ID（委托 core 实现）。

    部分邮件（如 GitLab Code Review 日报）没有 Message-ID 头，
    入库时 message_id 为空。mail_cache 以 UNIQUE(folder, message_id)
    去重，两封空 mid 的邮件会撞键——后拉取的把先拉取的覆盖，
    用户看到"少收了一封邮件"。

    算法在 core/mail_receiver.py 的 fallback_message_id（单一出处，
    删除时用同一规则反推匹配服务器上的无 Message-ID 邮件）。
    """
    return fallback_message_id(
        raw.sender, raw.subject, raw.date, raw.body_text)


def _normalize_imap_date(raw_date: str) -> str:
    """将 IMAP Date 头标准化为 ISO 格式 'YYYY-MM-DD HH:MM:SS'（可字典序排序）。

    IMAP 原始格式如 'Thu, 27 Aug 2026 10:00:00 +0800'，含时区偏移；
    直接按字符串排序会因星期前缀导致乱序（Sun > Mon 但时间更晚）。
    解析后统一转为 UTC ISO 字符串，保证 ORDER BY received_at DESC 正确。
    """
    if not raw_date:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(raw_date)
        if dt is None:
            return raw_date  # 解析失败时保留原值，不丢数据
        # 统一转 UTC 再格式化为可排序的 ISO 字符串（去掉时区后缀）
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return raw_date


class MailFetchWorker(QThread):
    """邮箱客户端 IMAP 拉取线程。"""

    emails_fetched = Signal(list)   # list[dict]
    failed = Signal(str)            # reason

    def __init__(self, imap_config: dict, folder: str = "INBOX", parent=None):
        super().__init__(parent)
        self.imap_config = imap_config
        self.folder = folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            receiver = MailReceiver(
                imap_host=self.imap_config["host"],
                imap_user=self.imap_config["user"],
                imap_password=self.imap_config["password"],
                imap_port=self.imap_config.get("port", 993),
                use_ssl=self.imap_config.get("use_ssl", True),
            )
            raw_emails = receiver.fetch_recent()
            if self._cancelled:
                return

            # 跳过用户已删除的邮件（墓碑），防止服务器删除失败后重新同步回来
            deleted_ids = MailCacheRepository.get_deleted_ids()
            results = []
            for raw in raw_emails:
                if raw.message_id in deleted_ids:
                    continue
                # 解析发件人姓名和地址（RawEmail.sender 是 "Name <addr>" 格式）
                parsed = email.utils.parseaddr(raw.sender)
                sender_name = parsed[0] or parsed[1]
                sender_addr = parsed[1]

                results.append({
                    # 缺 Message-ID 头的邮件用内容哈希合成 ID，
                    # 避免多封空 mid 邮件在缓存表 UNIQUE 键上互相覆盖
                    "message_id": raw.message_id or _fallback_message_id(raw),
                    "sender": sender_name,
                    "sender_addr": sender_addr,
                    "subject": raw.subject,
                    "body_text": raw.body_text,
                    # V1.5：HTML 原文正文（阅读窗格渲染富文本/表格用）
                    "body_html": raw.body_html,
                    # 日期标准化为 ISO 格式（可字典序排序），避免原始 IMAP Date 头的
                    # 星期前缀导致排序混乱（Sun > Mon 但时间更晚 → 新邮件被压到下面）
                    "received_at": _normalize_imap_date(raw.date),
                    # V1.4 邮箱增强：附件与 HTML 标记（供缓存与详情展示）
                    "content_type": raw.content_type,
                    "has_html": raw.has_html,
                    "attachments": raw.attachments,
                })

            if not self._cancelled:
                self.emails_fetched.emit(results)

        except Exception as e:
            logger.error("邮箱拉取失败：%s", e)
            if not self._cancelled:
                self.failed.emit(str(e))
