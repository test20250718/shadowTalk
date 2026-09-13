# Task 8: Archiver

**Files:**
- Create: `shadowtalk/core/archiver.py`
- Create: `tests/test_archiver.py`

## Interfaces
- Consumes: `MessageRepository`, `SummaryRepository`, `summarizer`, `Settings`
- Produces:
  - `check_and_archive(friend_id: int) -> None`

## Implementation

```python
# shadowtalk/core/archiver.py
from shadowtalk.data.repositories import MessageRepository, SummaryRepository
from shadowtalk.config.settings import Settings
from shadowtalk.core import summarizer


def check_and_archive(friend_id: int):
    """检查是否需要打包归档"""
    raw_keep_max = Settings.get_int("raw_keep_max")
    batch_size = Settings.get_int("summary_batch_size")

    raw_count = MessageRepository.count_unarchived_rounds(friend_id)

    if raw_count <= raw_keep_max:
        return

    overflow = raw_count - raw_keep_max
    buffer = MessageRepository.get_oldest_unarchived(friend_id, overflow)

    if len(buffer) < batch_size:
        return

    to_archive = buffer[:batch_size]
    summarizer.generate_batch_summary(friend_id, to_archive)
```

## Tests

```python
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
    for i in range(60):
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
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement archiver.py
4. Run to verify PASS
5. Commit
