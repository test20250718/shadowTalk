# tests/test_mail_compose_send_worker.py
"""
MailComposeSendWorker 测试。

验证：成功发送 MailSender 构造正确、失败时捕获异常、取消标志生效。
"""
import pytest
from unittest.mock import patch, MagicMock

from shadowtalk.core.mail_composer import MailMessage
from shadowtalk.core.mail_sender import MailSendError
from shadowtalk.ui.threads.mail_compose_send_worker import MailComposeSendWorker


class TestMailComposeSendWorker:
    MAIL_MSG = MailMessage(
        subject="测试主题",
        body_text="测试正文",
        message_id="test@shadowtalk.local",
        extra_headers={},
        to="to@test.com",
    )
    MAIL_CONFIG = {
        "host": "smtp.test.com", "port": 587,
        "use_tls": True, "username": "user", "password": "pass",
    }

    def test_emits_sent_on_success(self):
        """成功发送时 MailSender 以正确参数构造。"""
        worker = MailComposeSendWorker(self.MAIL_MSG, self.MAIL_CONFIG)
        with patch("shadowtalk.ui.threads.mail_compose_send_worker.MailSender") as MockSender:
            worker.run()
        MockSender.assert_called_once_with(**self.MAIL_CONFIG)

    def test_emits_failed_on_error(self):
        """发送失败时捕获 MailSendError，不抛异常。"""
        worker = MailComposeSendWorker(self.MAIL_MSG, self.MAIL_CONFIG)
        with patch("shadowtalk.ui.threads.mail_compose_send_worker.MailSender") as MockSender:
            MockSender.return_value.send.side_effect = MailSendError("连接失败")
            # run() 不应抛异常（异常转为 failed 信号）
            worker.run()
        MockSender.return_value.send.assert_called_once_with(self.MAIL_MSG)

    def test_cancel_flag(self):
        """cancel() 设置取消标志。"""
        worker = MailComposeSendWorker(self.MAIL_MSG, self.MAIL_CONFIG)
        assert worker._cancelled is False
        worker.cancel()
        assert worker._cancelled is True
