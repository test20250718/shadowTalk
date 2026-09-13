# shadowtalk/core/background_scanner.py
import logging

from shadowtalk.data.repositories import SummaryRepository
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings
from shadowtalk.core import summarizer


logger = logging.getLogger(__name__)


class BackgroundScanner:
    """过期摘要扫描合并（QTimer 驱动，此处为逻辑层，UI 层负责定时调用）"""

    def __init__(self):
        pass

    def scan_now(self):
        """立即执行一次扫描"""
        conn = Database.get_connection()
        friends = conn.execute("SELECT id FROM friends").fetchall()

        for friend_row in friends:
            friend_id = friend_row["id"]
            self._scan_friend(friend_id)

        logger.info("摘要扫描完成: %d 个好友", len(friends))

    def _scan_friend(self, friend_id: int):
        valid_days = Settings.get_int("summary_valid_days")
        expired = SummaryRepository.get_expired_summaries(friend_id, valid_days)

        if not expired:
            return

        l2_text = summarizer.generate_high_level_summary(expired)

        summary_ids = [s["id"] for s in expired]
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO high_level_summary (friend_id, content) VALUES (?, ?)",
                (friend_id, l2_text)
            )
            if summary_ids:
                placeholders = ",".join("?" * len(summary_ids))
                conn.execute(
                    f"UPDATE batch_summary SET is_archived=1 WHERE id IN ({placeholders})",
                    summary_ids
                )

        self._enforce_l2_limit(friend_id)

    def _enforce_l2_limit(self, friend_id: int):
        limit = Settings.get_int("l2_limit")
        l2_list = SummaryRepository.get_all_high_level_summaries(friend_id)

        if len(l2_list) <= limit:
            return

        to_merge = l2_list[:len(l2_list) - limit + 1]
        merged = summarizer.merge_high_level_summaries(to_merge)

        to_merge_ids = [s["id"] for s in to_merge]
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO high_level_summary (friend_id, content) VALUES (?, ?)",
                (friend_id, merged)
            )
            if to_merge_ids:
                placeholders = ",".join("?" * len(to_merge_ids))
                conn.execute(
                    f"DELETE FROM high_level_summary WHERE id IN ({placeholders})",
                    to_merge_ids
                )
