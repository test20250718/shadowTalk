# Task 5: Memory Layers (L0-L3)

**Files:**
- Create: `shadowtalk/core/layers/__init__.py`
- Create: `shadowtalk/core/layers/l3_persona.py`
- Create: `shadowtalk/core/layers/l2_summary.py`
- Create: `shadowtalk/core/layers/l1_summary.py`
- Create: `shadowtalk/core/layers/l0_raw.py`
- Create: `tests/test_layers.py`

## Interfaces
- Consumes: `FriendRepository`, `SummaryRepository`, `MessageRepository`
- Produces:
  - `l3.extract(friend_id) -> list[dict]` — returns [{"role": "system", "content": "...", "layer": "L3"}]
  - `l2.extract(friend_id) -> list[dict]`
  - `l1.extract(friend_id) -> list[dict]`
  - `l0.extract(friend_id) -> list[dict]`

## Implementation

```python
# shadowtalk/core/layers/l3_persona.py
from shadowtalk.data.repositories import FriendRepository


def extract(friend_id: int) -> list[dict]:
    friend = FriendRepository.get_by_id(friend_id)
    if not friend:
        return []
    return [{
        "role": "system",
        "content": friend["system_prompt"],
        "layer": "L3"
    }]
```

```python
# shadowtalk/core/layers/l2_summary.py
from shadowtalk.data.repositories import SummaryRepository


def extract(friend_id: int) -> list[dict]:
    summaries = SummaryRepository.get_all_high_level_summaries(friend_id)
    return [
        {"role": "system", "content": s["content"], "layer": "L2"}
        for s in summaries
    ]
```

```python
# shadowtalk/core/layers/l1_summary.py
from shadowtalk.data.repositories import SummaryRepository
from shadowtalk.config.settings import Settings


def extract(friend_id: int) -> list[dict]:
    valid_days = Settings.get_int("summary_valid_days")
    summaries = SummaryRepository.get_valid_summaries(friend_id, valid_days)
    return [
        {"role": "system", "content": s["content"], "layer": "L1"}
        for s in summaries
    ]
```

```python
# shadowtalk/core/layers/l0_raw.py
from shadowtalk.data.repositories import MessageRepository


def extract(friend_id: int) -> list[dict]:
    messages = MessageRepository.get_unarchived(friend_id)
    return [
        {"role": m["sender_type"], "content": m["content"], "layer": "L0"}
        for m in messages
    ]
```

## Tests

```python
# tests/test_layers.py
import pytest
from shadowtalk.core.layers import l3, l2, l1, l0
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)


class TestLayers:
    def test_l3_returns_persona(self):
        fid = FriendRepository.insert("好友", "", "你是一个热情的助手")
        result = l3.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L3"
        assert "热情的助手" in result[0]["content"]

    def test_l3_empty_persona(self):
        fid = FriendRepository.insert("好友", "", "")
        result = l3.extract(fid)
        assert len(result) == 1
        assert result[0]["content"] == ""

    def test_l2_returns_high_level(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_high_level_summary(fid, "高阶摘要内容")
        result = l2.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L2"
        assert result[0]["content"] == "高阶摘要内容"

    def test_l2_empty(self):
        fid = FriendRepository.insert("好友", "", "")
        result = l2.extract(fid)
        assert len(result) == 0

    def test_l1_returns_valid_summaries(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_batch_summary(fid, "批次摘要", 1, 30)
        result = l1.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L1"
        assert result[0]["content"] == "批次摘要"

    def test_l1_excludes_expired(self):
        fid = FriendRepository.insert("好友", "", "")
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        conn.execute(
            "INSERT INTO batch_summary "
            "(friend_id, content, start_round, end_round, create_time) "
            "VALUES (?, ?, ?, ?, datetime('now', '-40 days'))",
            (fid, "过期摘要", 1, 30)
        )
        conn.commit()
        result = l1.extract(fid)
        assert len(result) == 0

    def test_l0_returns_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "你好", 1)
        MessageRepository.insert(fid, "ai", "你好！", 1)
        result = l0.extract(fid)
        assert len(result) == 2
        assert all(m["layer"] == "L0" for m in result)

    def test_l0_excludes_archived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息", 1)
        msgs = MessageRepository.get_unarchived(fid)
        MessageRepository.mark_archived([msgs[0]["id"]])
        result = l0.extract(fid)
        assert len(result) == 0
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement all 4 layer files
4. Run to verify PASS
5. Commit
