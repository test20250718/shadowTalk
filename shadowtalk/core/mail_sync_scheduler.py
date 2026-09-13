# shadowtalk/core/mail_sync_scheduler.py
"""
邮件同步调度（纯逻辑层，QTimer 驱动——镜像 BackgroundScanner 模式）。

判定哪些好友到达同步周期、收集待发消息、标记已发送。
"""
import uuid
import logging
from datetime import datetime, timedelta

from shadowtalk.data.repositories import FriendRepository, MessageRepository
from shadowtalk.data.database import Database

logger = logging.getLogger(__name__)

# 周期 -> 间隔天数（daily/weekly/monthly；分钟级测试周期见 _cycle_interval）
CYCLE_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


def _cycle_interval(cycle: str) -> timedelta:
    """周期 → 时间间隔。

    支持资产内置的 daily/weekly/monthly，以及手动创建好友可选的
    分钟级测试周期 "Nmin"（如 "5min"）。非法值按每日处理（保守）。
    """
    if cycle.endswith("min"):
        try:
            minutes = int(cycle[:-3])
            if minutes > 0:
                return timedelta(minutes=minutes)
        except ValueError:
            pass  # 非法分钟数按每日处理
    return timedelta(days=CYCLE_DAYS.get(cycle, 1))


class MailSyncScheduler:
    """邮件同步调度器（逻辑层，无 QTimer）。"""

    @staticmethod
    def sync_due_friends() -> list:
        """返回应当发送的好友 id 列表（enable=1、未撤销、距上次发送满足 cycle）。"""
        due = []
        friends = FriendRepository.get_friends_with_mail_sync()
        for friend in friends:
            if MailSyncScheduler._is_due(friend):
                due.append(friend["id"])
        return due

    @staticmethod
    def due_info(friend_id: int) -> dict:
        """返回需发送的消息列表 + session_id。"""
        friend = FriendRepository.get_by_id(friend_id)
        if not friend:
            return {"messages": [], "session_id": ""}

        # 首次发送时生成 session_id
        session_id = friend["email_session_id"]
        if not session_id:
            session_id = uuid.uuid4().hex
            FriendRepository.update(friend_id, email_session_id=session_id)

        messages = MessageRepository.get_messages_since(
            friend_id, friend["last_sent_message_id"]
        )
        return {"messages": messages, "session_id": session_id}

    @staticmethod
    def mark_sent(friend_id: int, last_msg_id: int):
        """更新游标 + 记录发送时间。

        last_sent_at 必须存本地时间：_is_due 用本地 datetime.now() 比较，
        若存 UTC（datetime('now')）会比本地慢数小时，周期判定永远"到期"。
        """
        with Database.transaction() as conn:
            conn.execute(
                "UPDATE friends SET last_sent_message_id=?, "
                "last_sent_at=datetime('now','localtime') WHERE id=?",
                (last_msg_id, friend_id)
            )

    @staticmethod
    def collect_messages_since(friend_id: int, last_sent_msg_id: int):
        """收集 id 大于游标的消息。"""
        return MessageRepository.get_messages_since(friend_id, last_sent_msg_id)

    @staticmethod
    def _is_due(friend) -> bool:
        """判断该好友是否到达同步周期。"""
        # 从未发送：首次满足 mail_sync_enable 即发
        if not friend["last_sent_at"]:
            return True

        # 解析上次发送时间
        try:
            last_sent = datetime.strptime(friend["last_sent_at"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            # 时间格式异常视为到期（避免永远不发）
            return True

        # 周期判定（支持分钟级测试周期）
        cycle = friend["mail_sync_cycle"] or "daily"
        return datetime.now() - last_sent >= _cycle_interval(cycle)
