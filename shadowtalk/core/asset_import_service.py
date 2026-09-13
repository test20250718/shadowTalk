# shadowtalk/core/asset_import_service.py
"""
数字分身资产导入服务

解密 Base64 密文 -> 解析为 AssetBundle -> 落库或覆盖。
同 authorizer_email + recipient_email 已存在且未撤销 -> 覆盖；已撤销 -> 抛 RevokedAssetError。
"""
import json
import base64
from dataclasses import dataclass

from shadowtalk.core.crypto_service import get_cipher, InvalidCipherError
from shadowtalk.core.friend_service import FriendService, persist_avatar
from shadowtalk.data.repositories import FriendRepository


VALID_CYCLES = ("daily", "weekly", "monthly")

# 解密后 JSON 必填字段
REQUIRED_FIELDS = ("nickname", "persona", "authorizer_email", "recipient_email")


class RevokedAssetError(Exception):
    """该分身已被创作者取消授权，无法使用。"""
    pass


@dataclass
class AssetBundle:
    """解密后的数字资产数据结构。"""
    nickname: str
    persona: str                       # 写入 system_prompt
    avatar_bytes: bytes
    avatar_ext: str
    authorizer_email: str
    recipient_email: str
    mail_sync_enable: bool
    mail_receiver_address: str
    mail_sync_cycle: str               # daily/weekly/monthly


class AssetImportService:
    """数字分身资产导入核心逻辑。"""

    @staticmethod
    def decrypt_and_parse(b64_text: str) -> AssetBundle:
        """解密 + 解析密文为 AssetBundle（不落库，供预览用）。"""
        cipher = get_cipher()
        plaintext = cipher.decrypt(b64_text)
        return AssetImportService.parse_bundle(plaintext)

    @staticmethod
    def import_asset(b64_text: str) -> int:
        """解密 -> 解析 -> 落库或覆盖。返回 friend_id。

        同 authorizer+recipient 已存在且未撤销 -> 覆盖；已撤销 -> 抛 RevokedAssetError。
        """
        # 解密 + 解析
        bundle = AssetImportService.decrypt_and_parse(b64_text)

        # 重导入去重：同 authorizer+recipient 已存在？
        existing = FriendRepository.find_by_authorizer_recipient(
            bundle.authorizer_email, bundle.recipient_email
        )
        if existing:
            if existing["asset_revoked"]:
                # 已撤销的分身拒绝重新导入
                raise RevokedAssetError("该分身已被创作者取消授权，无法使用")
            return AssetImportService._overwrite(existing["id"], bundle)

        return AssetImportService._create(bundle)

    @staticmethod
    def parse_bundle(plaintext: bytes) -> AssetBundle:
        """把解密后的明文（JSON）解析为 AssetBundle，校验必填字段。"""
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise InvalidCipherError(f"数字资产密文无效或已损坏：{e}")

        # 校验必填字段
        for field in REQUIRED_FIELDS:
            if not data.get(field):
                raise InvalidCipherError(f"数字资产缺少必填字段：{field}")

        # 校验同步周期
        cycle = data.get("mail_sync_enable", True)
        # mail_sync_enable 兼容 bool 和字符串
        mail_sync_enable = cycle if isinstance(cycle, bool) else str(cycle).lower() in ("1", "true", "yes")

        mail_sync_cycle = data.get("mail_sync_cycle", "daily")
        if mail_sync_cycle not in VALID_CYCLES:
            raise InvalidCipherError(
                f"无效的同步周期 {mail_sync_cycle!r}，应为 {VALID_CYCLES}"
            )

        # 头像：密文内嵌 base64 编码的图片数据（可选）
        avatar_bytes = b""
        avatar_ext = ".png"
        avatar_b64 = data.get("avatar_base64", "")
        if avatar_b64:
            try:
                avatar_bytes = base64.b64decode(avatar_b64)
            except Exception as e:
                raise InvalidCipherError(f"头像数据损坏：{e}")
            avatar_ext = data.get("avatar_ext", ".png")

        return AssetBundle(
            nickname=str(data["nickname"]),
            persona=str(data["persona"]),
            avatar_bytes=avatar_bytes,
            avatar_ext=avatar_ext,
            authorizer_email=str(data["authorizer_email"]),
            recipient_email=str(data["recipient_email"]),
            mail_sync_enable=mail_sync_enable,
            mail_receiver_address=str(data.get("mail_receiver_address", "")),
            mail_sync_cycle=mail_sync_cycle,
        )

    @staticmethod
    def _create(bundle: AssetBundle) -> int:
        """新建好友角色。"""
        # 先建好友（无头像），拿到 friend_id 后再落盘头像
        friend_id = FriendRepository.insert(
            name=bundle.nickname,
            remark="",
            system_prompt=bundle.persona,
            avatar_path="",          # 先占位，落盘后更新
            authorizer_email=bundle.authorizer_email,
            recipient_email=bundle.recipient_email,
            mail_sync_enable=1 if bundle.mail_sync_enable else 0,
            mail_receiver_address=bundle.mail_receiver_address,
            mail_sync_cycle=bundle.mail_sync_cycle,
        )

        # 头像落盘
        if bundle.avatar_bytes:
            persist_avatar(friend_id, bundle.avatar_bytes, bundle.avatar_ext)

        return friend_id

    @staticmethod
    def _overwrite(friend_id: int, bundle: AssetBundle) -> int:
        """重导入覆盖：更新人设、头像、邮件配置；保留 email_session_id 与聊天记录。"""
        # 覆盖人设、昵称、邮件配置
        FriendRepository.update(
            friend_id,
            name=bundle.nickname,
            system_prompt=bundle.persona,
            authorizer_email=bundle.authorizer_email,
            recipient_email=bundle.recipient_email,
            mail_sync_enable=1 if bundle.mail_sync_enable else 0,
            mail_receiver_address=bundle.mail_receiver_address,
            mail_sync_cycle=bundle.mail_sync_cycle,
        )

        # 头像替换
        if bundle.avatar_bytes:
            persist_avatar(friend_id, bundle.avatar_bytes, bundle.avatar_ext)

        return friend_id
