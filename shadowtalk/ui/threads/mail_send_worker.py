# shadowtalk/ui/threads/mail_send_worker.py
"""
邮件发送线程（QThread，镜像 AIWorker 生命周期）。

在后台线程执行 SMTP 发送，避免阻塞 UI。
"""
import logging

from PySide6.QtCore import QThread, Signal

from shadowtalk.core.mail_composer import MailComposer
from shadowtalk.core.mail_sender import MailSender

logger = logging.getLogger(__name__)


class MailSendWorker(QThread):
    """邮件发送线程。"""

    sent = Signal(int, str)      # friend_id, message_id
    failed = Signal(int, str)    # friend_id, reason

    def __init__(self, friend_id: int, messages: list,
                 mail_config: dict, session_id: str, parent=None):
        """
        Args:
            friend_id: 好友 ID
            messages: 待发送的聊天记录 Row 列表
            mail_config: 邮件配置字典（host/port/use_tls/username/password）
            session_id: 该好友的邮件会话 UUID
        """
        super().__init__(parent)
        self.friend_id = friend_id
        self.messages = messages
        self.mail_config = mail_config
        self.session_id = session_id
        self._cancelled = False

    def cancel(self):
        """请求取消（SMTP 无法中断，仅设标志跳过结果处理）。"""
        self._cancelled = True

    def run(self):
        try:
            from shadowtalk.data.repositories import FriendRepository
            friend = FriendRepository.get_by_id(self.friend_id)
            if not friend:
                self.failed.emit(self.friend_id, "好友不存在")
                return

            # 组装邮件
            mail_msg = MailComposer.compose(friend, self.messages, self.session_id)

            # 发送
            sender = MailSender(
                smtp_host=self.mail_config["host"],
                smtp_port=int(self.mail_config["port"]),
                use_tls=self.mail_config.get("use_tls", True),
                username=self.mail_config.get("username", ""),
                password=self.mail_config.get("password", ""),
            )
            message_id = sender.send(mail_msg)

            if not self._cancelled:
                self.sent.emit(self.friend_id, message_id)
        except Exception as e:
            logger.error("邮件发送线程异常：%s", e)
            if not self._cancelled:
                self.failed.emit(self.friend_id, str(e))
