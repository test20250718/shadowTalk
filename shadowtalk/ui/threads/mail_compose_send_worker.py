# shadowtalk/ui/threads/mail_compose_send_worker.py
"""
通用邮件发送线程（QThread）。

独立于分身同步的 MailSendWorker，用于邮箱客户端的写信发送。
支持带附件的 MailMessage（通过 mime_message 字段）。
"""
import logging

from PySide6.QtCore import QThread, Signal

from shadowtalk.core.mail_sender import MailSender

logger = logging.getLogger(__name__)


class MailComposeSendWorker(QThread):
    """通用邮件发送线程。"""

    sent = Signal()              # 发送成功
    failed = Signal(str)         # 失败原因

    def __init__(self, mail_msg, mail_config: dict, parent=None):
        super().__init__(parent)
        self.mail_msg = mail_msg
        self.mail_config = mail_config
        self._cancelled = False

    def cancel(self):
        """请求取消（SMTP 无法中断，仅设标志跳过结果处理）。"""
        self._cancelled = True

    def run(self):
        try:
            # 构造发送器；mail_message 带附件时 MailSender.send() 直接发送 MIME
            # 透传 mail_config（支持 host/port 或 smtp_host/smtp_port 命名）
            config = dict(self.mail_config)
            if "port" in config:
                config["port"] = int(config["port"])
            sender = MailSender(**config)
            sender.send(self.mail_msg)
            if not self._cancelled:
                self.sent.emit()
        except Exception as e:
            logger.error("邮件发送失败：%s", e)
            if not self._cancelled:
                self.failed.emit(str(e))
