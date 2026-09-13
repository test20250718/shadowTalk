# tests/test_archiver.py
from unittest.mock import patch
from shadowtalk.core.archiver import check_and_archive
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)


def test_no_archive_when_under_threshold():
    fid = FriendRepository.insert("好友", "", "")
    for i in range(10):
        MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        MessageRepository.insert(fid, "ai", f"回复{i}", i + 1)

    with patch("shadowtalk.core.archiver.summarizer") as mock_sum:
        check_and_archive(fid)
        mock_sum.generate_batch_summary.assert_not_called()

def test_archive_when_over_threshold():
    fid = FriendRepository.insert("好友", "", "")
    for i in range(80):  # 80 rounds: overflow=30 >= batch_size=30
        MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        MessageRepository.insert(fid, "ai", f"回复{i}", i + 1)

    with patch("shadowtalk.core.archiver.summarizer") as mock_sum:
        mock_sum.generate_batch_summary.return_value = "摘要"
        check_and_archive(fid)
        assert mock_sum.generate_batch_summary.call_count >= 1

def test_no_archive_buffer_too_small():
    fid = FriendRepository.insert("好友", "", "")
    for i in range(55):
        MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        MessageRepository.insert(fid, "ai", f"回复{i}", i + 1)

    with patch("shadowtalk.core.archiver.summarizer") as mock_sum:
        check_and_archive(fid)
        mock_sum.generate_batch_summary.assert_not_called()
