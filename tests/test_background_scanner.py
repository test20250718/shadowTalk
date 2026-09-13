# tests/test_background_scanner.py
from unittest.mock import patch
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import (
    FriendRepository, SummaryRepository
)


def test_scan_merges_expired_summaries():
    fid = FriendRepository.insert("好友", "", "")
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    conn.execute(
        "INSERT INTO batch_summary "
        "(friend_id, content, start_round, end_round, create_time) "
        "VALUES (?, ?, ?, ?, datetime('now', '-40 days'))",
        (fid, "过期批次摘要", 1, 30)
    )
    conn.commit()

    scanner = BackgroundScanner()

    with patch("shadowtalk.core.background_scanner.summarizer") as mock_sum:
        mock_sum.generate_high_level_summary.return_value = "合并后的L2"
        scanner.scan_now()

    l2_list = SummaryRepository.get_all_high_level_summaries(fid)
    assert len(l2_list) == 1
    assert l2_list[0]["content"] == "合并后的L2"
