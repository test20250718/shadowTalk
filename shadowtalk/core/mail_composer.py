# shadowtalk/core/mail_composer.py
"""
邮件组装：把聊天记录拼成邮件正文/标题/头部。

主题嵌入 [ShadowTalk-<短码>] 供回信匹配；尾部附 #作废授权# 提示。
"""
import uuid
from dataclasses import dataclass


REVOCATION_FOOTER = (
    "——\n"
    "此邮件由 ShadowTalk 影聊自动发送，包含您授权的数字分身聊天记录。\n"
    "如需取消该分身的授权，请直接回复 #作废授权#。"
)


@dataclass
class MailMessage:
    """组装好的邮件数据结构。"""
    subject: str
    body_text: str
    message_id: str           # <uuid@shadowtalk.local>
    extra_headers: dict       # X-ShadowTalk-Session 等
    to: str
    mime_message: object = None  # V1.4-Add: 预构建 MIME 对象（带附件时使用）


class MailComposer:
    """把聊天记录组装成邮件。"""

    @staticmethod
    def _short_code(session_id: str) -> str:
        """取 session_id 前 8 位作为主题短码。"""
        return session_id[:8] if session_id else "unknown"

    @staticmethod
    def compose(friend, messages: list, session_id: str) -> MailMessage:
        """组装邮件。

        Args:
            friend: 好友 Row 对象（含 name, mail_receiver_address 等）
            messages: 聊天记录 Row 列表（按 round_index 升序）
            session_id: 该好友的邮件会话 UUID
        Returns:
            MailMessage
        """
        short_code = MailComposer._short_code(session_id)
        friend_name = friend["remark"] or friend["name"]

        # 主题嵌入短码，回信时可匹配
        subject = f"[ShadowTalk-{short_code}] {friend_name} 与影聊分身的聊天记录"

        # 正文：逐条拼接
        lines = [
            f"以下是您授权的数字分身【{friend_name}】最近的聊天记录：",
            "",
            "——",
            "",
        ]
        for msg in messages:
            role = "我" if msg["sender_type"] == "user" else "AI分身"
            time_str = msg["create_time"]
            lines.append(f"[{time_str}] {role}：")
            lines.append(msg["content"])
            lines.append("")

        lines.append("——")
        lines.append(REVOCATION_FOOTER)

        body_text = "\n".join(lines)

        # Message-ID：用 session_id 构造，回信时可通过 In-Reply-To 匹配
        message_id = f"{session_id}@shadowtalk.local"

        extra_headers = {
            "X-ShadowTalk-Session": session_id,
            "X-ShadowTalk-Friend-Id": str(friend["id"]),
        }

        return MailMessage(
            subject=subject,
            body_text=body_text,
            message_id=message_id,
            extra_headers=extra_headers,
            to=friend["mail_receiver_address"],
        )
