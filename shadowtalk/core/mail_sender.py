# shadowtalk/core/mail_sender.py
"""
SMTP 邮件发送（stdlib smtplib，无新依赖）。

支持 SSL/TLS（生产）与明文（MailHog 测试）。
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate

from shadowtalk.core.mail_composer import MailMessage

logger = logging.getLogger(__name__)


class MailSendError(Exception):
    """邮件发送失败。"""
    pass


class MailSender:
    """SMTP 邮件发送器。"""

    def __init__(self, smtp_host: str = None, smtp_port: int = None,
                 use_tls: bool = None, username: str = None, password: str = None,
                 host: str = None, port: int = None):
        # V1.4-Add: 同时支持 host/port 与 smtp_host/smtp_port 两种命名，
        # 保证 MailSendWorker（用 smtp_host/smtp_port）零修改即可兼容
        self.smtp_host = smtp_host if smtp_host is not None else host
        self.smtp_port = smtp_port if smtp_port is not None else port
        self.use_tls = use_tls
        self.username = username or ""
        self.password = password or ""

    def send(self, msg: MailMessage) -> str:
        """发送邮件，返回 message_id。失败抛 MailSendError。"""
        # V1.4-Add: 如果有预构建的 MIME 消息（带附件），直接发送
        if hasattr(msg, 'mime_message') and msg.mime_message:
            return self._send_mime(msg)

        # 构造 MIME 邮件（纯文本）
        mime_msg = MIMEMultipart("alternative")
        mime_msg["Subject"] = msg.subject
        mime_msg["From"] = self.username
        mime_msg["To"] = msg.to
        mime_msg["Message-ID"] = f"<{msg.message_id}>"
        mime_msg["Date"] = formatdate(localtime=True)

        # 自定义头部（回信匹配用）
        for key, value in msg.extra_headers.items():
            mime_msg[key] = value

        # 正文
        mime_msg.attach(MIMEText(msg.body_text, "plain", "utf-8"))

        try:
            # 连接 SMTP 服务器
            if self.use_tls:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            # 有用户名才登录（MailHog 测试无需认证）
            if self.username:
                server.login(self.username, self.password)
            server.send_message(mime_msg)
            server.quit()
            logger.info("邮件发送成功：to=%s subject=%s", msg.to, msg.subject)
            return msg.message_id
        except smtplib.SMTPException as e:
            logger.error("邮件发送失败：%s", e)
            raise MailSendError(f"邮件发送失败：{e}")
        except Exception as e:
            logger.error("邮件发送异常：%s", e)
            raise MailSendError(f"邮件发送异常：{e}")

    def _send_mime(self, msg: MailMessage) -> str:
        """发送预构建的 MIME 消息（带附件）。

        复用与 send() 相同的连接/登录逻辑，但跳过 MIME 构造，
        直接发送外部传入的完整 MIME 对象。
        """
        try:
            if self.use_tls:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg.mime_message)
            server.quit()
            logger.info("邮件发送成功（含附件）：to=%s subject=%s", msg.to, msg.subject)
            return msg.message_id
        except smtplib.SMTPException as e:
            logger.error("邮件发送失败：%s", e)
            raise MailSendError(f"邮件发送失败：{e}")
        except Exception as e:
            logger.error("邮件发送异常：%s", e)
            raise MailSendError(f"邮件发送异常：{e}")
