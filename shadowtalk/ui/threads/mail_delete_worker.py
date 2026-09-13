# shadowtalk/ui/threads/mail_delete_worker.py
"""
邮件删除线程（QThread）。

服务器端删除（IMAP \Deleted + EXPUNGE）成功后发 deleted 信号，
由调用方清本地缓存并刷新列表；失败发 failed 信号（本地不删，可重试）。
"""
import logging

from PySide6.QtCore import QThread, Signal

from shadowtalk.core.mail_receiver import MailReceiver

logger = logging.getLogger(__name__)


class MailDeleteWorker(QThread):
    """按 Message-ID 在服务器删除邮件。"""

    deleted = Signal(int)       # 实际删除数
    failed = Signal(str)        # 失败原因

    def __init__(self, imap_config: dict, message_ids: list[str], parent=None):
        super().__init__(parent)
        self.imap_config = imap_config
        self.message_ids = message_ids

    def run(self):
        try:
            receiver = MailReceiver(
                imap_host=self.imap_config["host"],
                imap_user=self.imap_config["user"],
                imap_password=self.imap_config["password"],
                imap_port=self.imap_config.get("port", 993),
                use_ssl=self.imap_config.get("use_ssl", True),
            )
            logger.info("邮件删除：尝试删除 %d 条 Message-ID", len(self.message_ids))
            n = receiver.delete_messages(self.message_ids)
            if n == 0:
                # 服务器未匹配到任何邮件 — 记录 Message-ID 供排查
                logger.warning(
                    "邮件删除：服务器未找到匹配邮件（Message-IDs: %s）",
                    self.message_ids)
            self.deleted.emit(n)
        except Exception as e:
            logger.error("邮件删除失败：%s", e)
            self.failed.emit(str(e))
