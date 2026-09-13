# shadowtalk/ui/threads/mail_receive_worker.py
"""
邮件接收线程（QThread，镜像 AIWorker 生命周期）。

在后台线程执行 IMAP 拉取 + 会话匹配 + 授权判断，结果经信号回主线程。
"""
import logging

from PySide6.QtCore import QThread, Signal

from shadowtalk.core.mail_receiver import MailReceiver, extract_reply_body, match_session_id
from shadowtalk.core.revocation_service import RevocationService
from shadowtalk.data.repositories import FriendRepository, ProcessedEmailRepository

logger = logging.getLogger(__name__)


class MailReceiveWorker(QThread):
    """邮件接收线程。"""

    human_reply = Signal(int, str, str)   # friend_id, text, message_id
    asset_revoked = Signal(int)            # friend_id
    failed = Signal(str)                   # reason

    def __init__(self, imap_config: dict, ai_client=None, parent=None):
        """
        Args:
            imap_config: IMAP 配置字典（host/user/password/use_ssl）
            ai_client: AI 客户端（用于授权意图兜底判断，None 则跳过 AI 兜底）
        """
        super().__init__(parent)
        self.imap_config = imap_config
        self.ai_client = ai_client
        self._cancelled = False

    def cancel(self):
        """请求取消。"""
        self._cancelled = True

    def run(self):
        try:
            # 拉取最近邮件（含已读：见 MailReceiver.fetch_recent 的说明）
            receiver = MailReceiver(
                imap_host=self.imap_config["host"],
                imap_user=self.imap_config["user"],
                imap_password=self.imap_config["password"],
                imap_port=self.imap_config.get("port", 993),
                use_ssl=self.imap_config.get("use_ssl", True),
            )
            raw_emails = receiver.fetch_recent()

            if not raw_emails:
                return

            # 获取所有有 session_id 的好友（用于匹配）
            all_friends = [
                f for f in FriendRepository.get_all() if f["email_session_id"]
            ]

            # 用户自己的 SMTP/IMAP 账号：自己发给自己的邮件（sender == 自己的邮箱）
            # 必须跳过，否则会被当作"真人回信"插回聊天 → 新消息再触发发送 → 死循环。
            # 邮件仍会留在收件箱作为备份，只是不再回灌到聊天。
            own_email = (self.imap_config.get("user") or "").lower()

            for raw in raw_emails:
                if self._cancelled:
                    break

                # 去重：已处理则跳过
                if ProcessedEmailRepository.exists(raw.message_id):
                    continue

                # 自己发给自己的邮件 → 仅记录已处理，不插入聊天、不触发后续
                if own_email and raw.sender.lower() == own_email:
                    logger.info("跳过自己发给自己的邮件（防循环）：sender=%s subject=%s",
                                raw.sender, raw.subject[:50])
                    ProcessedEmailRepository.record(
                        raw.message_id, None, "self_sent"
                    )
                    continue

                # 匹配会话
                friend = match_session_id(raw, all_friends)
                if not friend:
                    # 无匹配（已删除好友的旧邮件、用户自己的普通邮件等）：
                    # 记录为 unmatched 并标记已处理，避免每轮重复拉取日志刷屏
                    logger.info("邮件未匹配到分身会话，跳过：subject=%s",
                                raw.subject[:50])
                    ProcessedEmailRepository.record(
                        raw.message_id, None, "unmatched"
                    )
                    continue

                # 过滤引用历史
                reply_body = extract_reply_body(raw.body_text)

                # 评估意图
                action = RevocationService.evaluate(raw, friend, self.ai_client)

                # 记录已处理
                ProcessedEmailRepository.record(
                    raw.message_id, friend["id"], action
                )

                if action == "revoke":
                    if not self._cancelled:
                        self.asset_revoked.emit(friend["id"])
                elif action == "human_reply" and reply_body:
                    if not self._cancelled:
                        self.human_reply.emit(
                            friend["id"], reply_body, raw.message_id
                        )
                # action == "ignore" -> 仅记录，不发信号

        except Exception as e:
            logger.error("邮件接收线程异常：%s", e)
            if not self._cancelled:
                self.failed.emit(str(e))
