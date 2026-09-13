import pytest
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication

from shadowtalk.core.mail_receiver import extract_attachments


def _make_multipart_email(with_attachment=True, with_inline=True):
    msg = MIMEMultipart('mixed')
    msg['Subject'] = '测试'
    msg['From'] = 'sender@test.com'
    body = MIMEText('<p>Hello</p>', 'html', 'utf-8')
    msg.attach(body)
    if with_attachment:
        att = MIMEApplication(b'file content', Name='报告.pdf')
        att['Content-Disposition'] = 'attachment; filename="报告.pdf"'
        msg.attach(att)
    if with_inline:
        img = MIMEImage(b'\x89PNG\r\n\x13\n' + b'\x00' * 100, 'png')
        img['Content-ID'] = '<image001@shadowtalk.local>'
        img['Content-Disposition'] = 'inline; filename="logo.png"'
        msg.attach(img)
    return msg


class TestExtractAttachments:
    def test_extracts_regular_attachment(self):
        msg = _make_multipart_email(with_attachment=True, with_inline=False)
        attachments = extract_attachments(msg)
        assert len(attachments) == 1
        assert attachments[0]['filename'] == '报告.pdf'
        assert attachments[0]['is_inline'] == 0
        assert attachments[0]['size'] > 0

    def test_extracts_inline_image(self):
        msg = _make_multipart_email(with_attachment=False, with_inline=True)
        attachments = extract_attachments(msg)
        assert len(attachments) == 1
        assert attachments[0]['filename'] == 'logo.png'
        assert attachments[0]['is_inline'] == 1
        assert attachments[0]['content_id'] == '<image001@shadowtalk.local>'

    def test_extracts_both(self):
        msg = _make_multipart_email(with_attachment=True, with_inline=True)
        attachments = extract_attachments(msg)
        assert len(attachments) == 2

    def test_no_attachments(self):
        msg = _make_multipart_email(with_attachment=False, with_inline=False)
        attachments = extract_attachments(msg)
        assert len(attachments) == 0

    def test_payload_is_bytes(self):
        msg = _make_multipart_email(with_attachment=True, with_inline=False)
        attachments = extract_attachments(msg)
        assert isinstance(attachments[0]['payload'], bytes)
