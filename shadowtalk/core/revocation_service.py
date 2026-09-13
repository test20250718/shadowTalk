# shadowtalk/core/revocation_service.py
"""
授权作废服务

两层兜底识别授权作废意图：
1. 精确匹配：正文包含 "#作废授权#"
2. AI 语义兜底：调 AI 判断 YES/NO（口语化回复如"取消吧""别用了"）

判断对象是剥离引用后的本人正文（extract_reply_body）：我们发出的每封
邮件尾部都带"回复 #作废授权# 可取消授权"提示，回信若原样引用原文，
对全文做精确匹配会把每封普通回信都误判成撤销（用户报告：刚收到回信
分身就被冻结）。

安全校验：仅授权方邮箱（mail_receiver_address）发来的作废指令有效。
"""
import re
import logging

from shadowtalk.core.mail_receiver import RawEmail, extract_reply_body

logger = logging.getLogger(__name__)

REVOCATION_TAG = "#作废授权#"

# AI 意图判断 system prompt
_REVOCATION_CLASSIFY_SYSTEM = (
    "判断用户是否意在终止/撤销对此分身的授权。"
    "只回答 YES 或 NO，不要解释。"
)
_REVOCATION_CLASSIFY_USER_TEMPLATE = "用户回复内容：\n{body}"


class RevocationService:
    """授权作废识别服务。"""

    @staticmethod
    def is_exact_tag(body: str) -> bool:
        """精确匹配：正文包含 #作废授权#。"""
        return REVOCATION_TAG in body

    @staticmethod
    def classify_by_ai(body: str, ai_client) -> bool:
        """AI 语义兜底：判断用户是否意在终止授权。

        AI 返回 YES -> True（撤销），NO / 其他 / 失败 -> False（保守不撤销）。
        """
        try:
            messages = [
                {"role": "system", "content": _REVOCATION_CLASSIFY_SYSTEM},
                {"role": "user", "content": _REVOCATION_CLASSIFY_USER_TEMPLATE.format(body=body)},
            ]
            reply = ai_client.chat(messages).strip().upper()
            # 提取 YES/NO（容错：AI 可能多回答几个字）
            if reply.startswith("YES"):
                return True
            return False
        except Exception as e:
            logger.error("AI 授权意图判断失败：%s", e)
            # 失败保守视为 NO（不误冻结）
            return False

    @staticmethod
    def authorized_sender(sender: str, friend) -> bool:
        """校验发件人是否为该分身的授权方邮箱。"""
        expected = friend["mail_receiver_address"]
        if not expected:
            return False
        return sender.lower() == expected.lower()

    @staticmethod
    def evaluate(raw: RawEmail, friend, ai_client=None) -> str:
        """综合评估邮件意图。

        Args:
            raw: 解析后的邮件
            friend: 匹配的好友 Row
            ai_client: AI 客户端（None 时跳过 AI 兜底）
        Returns:
            'revoke' | 'human_reply' | 'ignore'
        """
        # 安全校验：非授权方邮箱 -> 忽略
        if not RevocationService.authorized_sender(raw.sender, friend):
            logger.info("非授权方邮箱发来的回复，忽略：sender=%s", raw.sender)
            return "ignore"

        # 只看剥离引用后的本人正文：引用的原文里必然带
        # "#作废授权#" 提示语，对全文判断会把普通回信误判成撤销
        body = extract_reply_body(raw.body_text)
        if not body:
            # 无本人正文（纯引用/空正文）不构成撤销指令，
            # 按 human_reply 返回（空正文不会被插入聊天）
            return "human_reply"

        # 策略 1：精确匹配
        if RevocationService.is_exact_tag(body):
            return "revoke"

        # 策略 2：AI 兜底（仅当有 AI 客户端时）
        if ai_client and RevocationService.classify_by_ai(body, ai_client):
            return "revoke"

        # 否则视为普通真人回信
        return "human_reply"
