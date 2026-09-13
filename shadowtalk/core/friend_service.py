# shadowtalk/core/friend_service.py
import shutil
import os
from pathlib import Path

from shadowtalk.config.paths import get_base_dir
from shadowtalk.data.repositories import FriendRepository, MessageRepository
from shadowtalk.data.database import Database


class FriendService:
    AVATAR_DIR = str(get_base_dir() / "data" / "avatars")

    @staticmethod
    def create(name: str, remark: str, system_prompt: str,
               avatar_source_path: str = "",
               ai_role: str = "", user_role: str = "", work_dir: str = "",
               voice: str = "") -> int:
        avatar_path = ""
        if avatar_source_path and os.path.exists(avatar_source_path):
            os.makedirs(FriendService.AVATAR_DIR, exist_ok=True)
            temp_dir = f"{FriendService.AVATAR_DIR}/temp"
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = f"{temp_dir}/{os.path.basename(avatar_source_path)}"
            shutil.copy2(avatar_source_path, temp_path)
            avatar_path = temp_path

        friend_id = FriendRepository.insert(
            name, remark, system_prompt, avatar_path,
            ai_role=ai_role, user_role=user_role, work_dir=work_dir,
            voice=voice
        )

        if avatar_path:
            ext = os.path.splitext(avatar_path)[1]
            final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
            final_path = f"{final_dir}/avatar{ext}"
            os.makedirs(final_dir, exist_ok=True)
            shutil.move(avatar_path, final_path)
            FriendRepository.update(friend_id, avatar_path=final_path)

        temp_dir = f"{FriendService.AVATAR_DIR}/temp"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        return friend_id

    @staticmethod
    def delete(friend_id: int, keep_messages: bool = False):
        if not keep_messages:
            with Database.transaction() as conn:
                # processed_emails 有 ON DELETE CASCADE，friends 删除时
                # 关联行会自动清理；此处显式删除作为双保险（兼容旧库
                # 外键约束未生效或 friend_id=NULL 的未匹配记录）
                conn.execute(
                    "DELETE FROM processed_emails WHERE friend_id=?", (friend_id,)
                )
                conn.execute("DELETE FROM chat_messages WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM batch_summary WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM high_level_summary WHERE friend_id=?", (friend_id,))
                conn.execute("DELETE FROM friends WHERE id=?", (friend_id,))
        else:
            FriendRepository.delete(friend_id)

        avatar_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
        if os.path.exists(avatar_dir):
            shutil.rmtree(avatar_dir, ignore_errors=True)

    @staticmethod
    def update_avatar(friend_id: int, new_avatar_path: str):
        friend = FriendRepository.get_by_id(friend_id)
        if not friend:
            return
        old_path = friend["avatar_path"]
        ext = os.path.splitext(new_avatar_path)[1]
        final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
        final_path = f"{final_dir}/avatar{ext}"
        os.makedirs(final_dir, exist_ok=True)
        shutil.copy2(new_avatar_path, final_path)
        FriendRepository.update(friend_id, avatar_path=final_path)
        # 同扩展名时 final_path 与 old_path 相同 —— 不能删（会删掉刚复制的新头像）
        if old_path and old_path != final_path and os.path.exists(old_path):
            os.remove(old_path)


def persist_avatar(friend_id: int, avatar_bytes: bytes, ext: str) -> str:
    """把头像字节落盘到 <AVATAR_DIR>/<friend_id>/avatar<ext>，并更新数据库。

    供 FriendService.create 与 AssetImportService 共用（避免重复落盘逻辑）。
    返回最终头像绝对路径。
    """
    final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
    final_path = f"{final_dir}/avatar{ext}"
    os.makedirs(final_dir, exist_ok=True)
    with open(final_path, "wb") as f:
        f.write(avatar_bytes)
    FriendRepository.update(friend_id, avatar_path=final_path)
    return final_path


def resolve_avatar(stored: str) -> str:
    """头像路径解析（迁移容错）。

    数据库存的是设置头像时的绝对路径；整个应用目录搬家/换机器后
    旧绝对路径失效（用户报告：换新版后头像全丢）。此时按当前应用
    头像目录 <AVATAR_DIR>/<好友id>/avatar.ext 同名回退；都没有返回
    空串（UI 自动回落名字首字模式）。
    """
    if not stored:
        return ""
    if os.path.isfile(stored):
        return stored
    p = Path(stored)
    alt = Path(FriendService.AVATAR_DIR) / p.parent.name / p.name
    return str(alt) if alt.is_file() else ""
