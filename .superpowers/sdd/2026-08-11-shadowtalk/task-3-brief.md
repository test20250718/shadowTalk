# Task 3: Repositories

**Files:**
- Create: `shadowtalk/models/__init__.py`
- Create: `shadowtalk/models/entities.py`
- Create: `shadowtalk/data/repositories.py`
- Create: `tests/test_repositories.py`

## Interfaces
- Consumes: `Database.get_connection()`, `Database.transaction()`
- Produces:
  - `MessageRepository.insert(friend_id, sender_type, content, round_index) -> None`
  - `MessageRepository.get_unarchived(friend_id) -> list[Row]`
  - `MessageRepository.get_oldest_unarchived(friend_id, limit) -> list[Row]`
  - `MessageRepository.count_unarchived_rounds(friend_id) -> int`
  - `MessageRepository.mark_archived(message_ids: list[int]) -> None`
  - `SummaryRepository.save_batch_summary(...) -> None`
  - `SummaryRepository.get_valid_summaries(friend_id, valid_days) -> list[Row]`
  - `SummaryRepository.get_expired_summaries(friend_id, valid_days) -> list[Row]`
  - `SummaryRepository.save_high_level_summary(friend_id, content) -> None`
  - `SummaryRepository.get_all_high_level_summaries(friend_id) -> list[Row]`
  - `FriendRepository.insert(name, remark, system_prompt, avatar_path) -> int`
  - `FriendRepository.get_by_id(friend_id) -> Row`
  - `FriendRepository.get_all() -> list[Row]`
  - `FriendRepository.update(friend_id, **kwargs) -> None`
  - `FriendRepository.delete(friend_id) -> None`

## Implementation

```python
# shadowtalk/models/entities.py
from dataclasses import dataclass


@dataclass
class Friend:
    id: int
    name: str
    remark: str = ""
    system_prompt: str = ""
    avatar_path: str = ""
    create_time: str = ""


@dataclass
class ChatMessage:
    id: int
    friend_id: int
    sender_type: str
    content: str
    round_index: int
    is_archived: bool = False
    create_time: str = ""


@dataclass
class BatchSummary:
    id: int
    friend_id: int
    content: str
    start_round: int
    end_round: int
    create_time: str = ""
    is_archived: bool = False
    is_truncated: bool = False


@dataclass
class HighLevelSummary:
    id: int
    friend_id: int
    content: str
    create_time: str = ""
```

```python
# shadowtalk/data/repositories.py
from shadowtalk.data.database import Database


class MessageRepository:
    @staticmethod
    def insert(friend_id, sender_type, content, round_index):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
                "VALUES (?, ?, ?, ?)",
                (friend_id, sender_type, content, round_index)
            )

    @staticmethod
    def get_unarchived(friend_id):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM chat_messages WHERE friend_id=? AND is_archived=0 "
            "ORDER BY round_index",
            (friend_id,)
        ).fetchall()

    @staticmethod
    def get_oldest_unarchived(friend_id, limit):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM chat_messages WHERE friend_id=? AND is_archived=0 "
            "ORDER BY round_index LIMIT ?",
            (friend_id, limit)
        ).fetchall()

    @staticmethod
    def count_unarchived_rounds(friend_id):
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT COUNT(DISTINCT round_index) FROM chat_messages "
            "WHERE friend_id=? AND is_archived=0",
            (friend_id,)
        ).fetchone()
        return row[0]

    @staticmethod
    def mark_archived(message_ids: list[int]):
        if not message_ids:
            return
        with Database.transaction() as conn:
            placeholders = ",".join("?" * len(message_ids))
            conn.execute(
                f"UPDATE chat_messages SET is_archived=1 WHERE id IN ({placeholders})",
                message_ids
            )


class SummaryRepository:
    @staticmethod
    def save_batch_summary(friend_id, content, start_round, end_round, is_truncated=0):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO batch_summary "
                "(friend_id, content, start_round, end_round, is_truncated) "
                "VALUES (?, ?, ?, ?, ?)",
                (friend_id, content, start_round, end_round, is_truncated)
            )

    @staticmethod
    def get_valid_summaries(friend_id, valid_days):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM batch_summary "
            "WHERE friend_id=? AND is_archived=0 "
            "AND create_time >= datetime('now', ? || ' days') "
            "ORDER BY create_time",
            (friend_id, f"-{valid_days}")
        ).fetchall()

    @staticmethod
    def get_expired_summaries(friend_id, valid_days):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM batch_summary "
            "WHERE friend_id=? AND is_archived=0 "
            "AND create_time < datetime('now', ? || ' days') "
            "ORDER BY create_time",
            (friend_id, f"-{valid_days}")
        ).fetchall()

    @staticmethod
    def mark_summaries_archived(summary_ids: list[int]):
        if not summary_ids:
            return
        with Database.transaction() as conn:
            placeholders = ",".join("?" * len(summary_ids))
            conn.execute(
                f"UPDATE batch_summary SET is_archived=1 WHERE id IN ({placeholders})",
                summary_ids
            )

    @staticmethod
    def save_high_level_summary(friend_id, content):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO high_level_summary (friend_id, content) VALUES (?, ?)",
                (friend_id, content)
            )

    @staticmethod
    def get_all_high_level_summaries(friend_id):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM high_level_summary WHERE friend_id=? ORDER BY create_time",
            (friend_id,)
        ).fetchall()


class FriendRepository:
    @staticmethod
    def insert(name, remark, system_prompt, avatar_path=""):
        with Database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO friends (name, remark, system_prompt, avatar_path) "
                "VALUES (?, ?, ?, ?)",
                (name, remark, system_prompt, avatar_path)
            )
            return cursor.lastrowid

    @staticmethod
    def get_by_id(friend_id):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM friends WHERE id=?", (friend_id,)
        ).fetchone()

    @staticmethod
    def get_all():
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM friends ORDER BY create_time"
        ).fetchall()

    @staticmethod
    def update(friend_id, **kwargs):
        allowed = {"name", "remark", "system_prompt", "avatar_path"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [friend_id]
        with Database.transaction() as conn:
            conn.execute(
                f"UPDATE friends SET {set_clause} WHERE id=?",
                values
            )

    @staticmethod
    def delete(friend_id):
        with Database.transaction() as conn:
            conn.execute("DELETE FROM friends WHERE id=?", (friend_id,))
```

## Tests

```python
# tests/test_repositories.py
import pytest
from shadowtalk.data.repositories import (
    MessageRepository, SummaryRepository, FriendRepository
)


class TestFriendRepository:
    def test_insert_and_get(self):
        fid = FriendRepository.insert("测试好友", "备注", "你是一个助手")
        friend = FriendRepository.get_by_id(fid)
        assert friend["name"] == "测试好友"
        assert friend["remark"] == "备注"

    def test_get_all(self):
        FriendRepository.insert("好友A", "", "")
        FriendRepository.insert("好友B", "", "")
        all_friends = FriendRepository.get_all()
        assert len(all_friends) >= 2

    def test_update(self):
        fid = FriendRepository.insert("原名", "", "")
        FriendRepository.update(fid, name="新名", remark="新备注")
        friend = FriendRepository.get_by_id(fid)
        assert friend["name"] == "新名"
        assert friend["remark"] == "新备注"

    def test_delete_cascade(self):
        fid = FriendRepository.insert("待删除", "", "")
        MessageRepository.insert(fid, "user", "hello", 1)
        FriendRepository.delete(fid)
        assert FriendRepository.get_by_id(fid) is None
        msgs = MessageRepository.get_unarchived(fid)
        assert len(msgs) == 0


class TestMessageRepository:
    def test_insert_and_get_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "你好", 1)
        MessageRepository.insert(fid, "ai", "你好！", 1)
        msgs = MessageRepository.get_unarchived(fid)
        assert len(msgs) == 2

    def test_count_unarchived_rounds(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息1", 1)
        MessageRepository.insert(fid, "ai", "回复1", 1)
        MessageRepository.insert(fid, "user", "消息2", 2)
        count = MessageRepository.count_unarchived_rounds(fid)
        assert count == 2

    def test_mark_archived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息", 1)
        msgs = MessageRepository.get_unarchived(fid)
        MessageRepository.mark_archived([msgs[0]["id"]])
        msgs_after = MessageRepository.get_unarchived(fid)
        assert len(msgs_after) == 0

    def test_get_oldest_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        for i in range(5):
            MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        oldest = MessageRepository.get_oldest_unarchived(fid, 2)
        assert len(oldest) == 2
        assert oldest[0]["round_index"] == 1


class TestSummaryRepository:
    def test_save_and_get_valid(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_batch_summary(fid, "摘要内容", 1, 30)
        valid = SummaryRepository.get_valid_summaries(fid, 30)
        assert len(valid) == 1
        assert valid[0]["content"] == "摘要内容"

    def test_save_high_level(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_high_level_summary(fid, "高阶摘要")
        all_l2 = SummaryRepository.get_all_high_level_summaries(fid)
        assert len(all_l2) == 1
        assert all_l2[0]["content"] == "高阶摘要"
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement entities.py and repositories.py
4. Run to verify PASS
5. Commit
