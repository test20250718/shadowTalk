# Task 10: Background Scanner

**Files:**
- Create: `shadowtalk/core/background_scanner.py`
- Create: `tests/test_background_scanner.py`

## Interfaces
- Consumes: `SummaryRepository`, `summarizer`, `FriendRepository`, `Database`
- Produces:
  - `BackgroundScanner` class with `.start()` and `.scan_now()` methods

## Implementation

```python
# shadowtalk/core/background_scanner.py
from shadowtalk.data.repositories import SummaryRepository, FriendRepository
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings
from shadowtalk.core import summarizer


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

    def _scan_friend(self, friend_id: int):
        valid_days = Settings.get_int("summary_valid_days")
        expired = SummaryRepository.get_expired_summaries(friend_id, valid_days)
        
        if not expired:
            return
        
        l2_text = summarizer.generate_high_level_summary(expired)
        
        with Database.transaction() as conn:
            SummaryRepository.save_high_level_summary(friend_id, l2_text)
            SummaryRepository.mark_summaries_archived([s["id"] for s in expired])
        
        self._enforce_l2_limit(friend_id)

    def _enforce_l2_limit(self, friend_id: int):
        limit = Settings.get_int("l2_limit")
        l2_list = SummaryRepository.get_all_high_level_summaries(friend_id)
        
        if len(l2_list) <= limit:
            return
        
        to_merge = l2_list[:len(l2_list) - limit + 1]
        merged = summarizer.merge_high_level_summaries(to_merge)
        
        with Database.transaction() as conn:
            SummaryRepository.save_high_level_summary(friend_id, merged)
            SummaryRepository.mark_summaries_archived([s["id"] for s in to_merge])
```

## Tests

```python
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
```

## TDD Steps
1. Write failing test
2. Run to verify FAIL
3. Implement background_scanner.py
4. Run to verify PASS
5. Commit
