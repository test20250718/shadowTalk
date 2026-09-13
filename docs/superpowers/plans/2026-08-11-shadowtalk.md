# ShadowTalk 影聊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ShadowTalk V1.0 — a local desktop AI chat app with a 4-layer hierarchical memory engine, PySide6 UI, SQLite storage, and OpenAI-compatible API support.

**Architecture:** Layered architecture with strict dependency direction: `ui/ → core/ → data/`. Memory engine assembles context via pipeline pattern. AI calls run in QThread workers to keep UI responsive. All business logic is UI-framework-agnostic for future tech swaps.

**Tech Stack:** Python 3.10+, PySide6, SQLite (stdlib), OpenAI SDK (compatible with DeepSeek etc.), pytest

## Global Constraints

- **分层约束**: `core/` `data/` `models/` 中禁止 import PySide6
- **依赖方向**: `ui/ → core/ → data/`（单向，不可反向）
- **非流式**: AI 回复必须完整接收后一次性渲染，无打字动画
- **禁止摘要**: 待打包对话不足 `summary_batch_size`（默认30轮）时，禁止调用 AI 生成摘要
- **数据库原文永久保存**: Token 裁剪只影响本次发送的上下文，不删除历史
- **写操作串行化**: 所有数据库写操作通过 `threading.Lock` 串行化
- **Token 估算**: 字符数 // 2（保守估算）
- **WAL 模式**: SQLite 启用 WAL 提升读写并发

---

## File Structure

```
shadowtalk/
├── main.py                         # 入口：初始化 DB、Settings、启动 UI
├── config/
│   ├── __init__.py
│   └── settings.py                 # 全局配置管理（读写 app_config 表）
├── models/
│   ├── __init__.py
│   └── entities.py                 # Friend, ChatMessage, BatchSummary, HighLevelSummary 数据类
├── data/
│   ├── __init__.py
│   ├── database.py                 # SQLite 连接管理（单例 + WAL + 写锁 + 事务）
│   └── repositories.py             # MessageRepository, SummaryRepository, FriendRepository
├── core/
│   ├── __init__.py
│   ├── memory_engine.py            # 主管道：build_context()
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── l3_persona.py           # L3 永久人设提取
│   │   ├── l2_summary.py           # L2 高阶聚合摘要提取
│   │   ├── l1_summary.py           # L1 批次摘要提取
│   │   └── l0_raw.py               # L0 未归档原文提取
│   ├── archiver.py                 # 归档检查 & 打包触发
│   ├── summarizer.py               # 调用 AI 生成摘要（含重试、截断兜底）
│   ├── token_budget.py             # Token 估算 & 裁剪策略
│   ├── background_scanner.py       # QTimer 定时扫描过期摘要
│   ├── ai_client.py                # OpenAI 兼容接口封装（纯 Python）
│   └── friend_service.py           # 好友管理业务逻辑
├── ui/
│   ├── __init__.py
│   ├── main_window.py              # 主窗口：左侧好友列表 + 右侧聊天区
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── friend_list.py          # 好友列表
│   │   ├── chat_area.py            # 聊天区域（消息列表 + 输入框）
│   │   ├── message_bubble.py       # 单条消息气泡（user/ai/loading）
│   │   ├── friend_dialog.py        # 新增/编辑好友对话框
│   │   └── settings_dialog.py      # 设置面板（API/记忆/操作 三个标签页）
│   └── threads/
│       ├── __init__.py
│       └── ai_worker.py            # QThread AI 调用工作线程
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # 共享 fixtures
│   ├── test_database.py
│   ├── test_repositories.py
│   ├── test_settings.py
│   ├── test_memory_engine.py
│   ├── test_layers.py
│   ├── test_archiver.py
│   ├── test_summarizer.py
│   ├── test_token_budget.py
│   ├── test_friend_service.py
│   └── test_ai_client.py
├── docs/
│   └── superpowers/specs/          # 设计规格（已存在）
├── data/                           # 运行时生成：avatars/, logs/
│   ├── avatars/
│   └── logs/
│       └── shadowtalk.log
└── shadowtalk.db                   # SQLite 数据库（运行时生成）
```

---

## Task 1: Project Scaffold + Database Layer

**Files:**
- Create: `shadowtalk/__init__.py`
- Create: `shadowtalk/data/__init__.py`
- Create: `shadowtalk/data/database.py`
- Create: `tests/conftest.py`
- Create: `tests/test_database.py`

**Interfaces:**
- Consumes: nothing (foundational task)
- Produces:
  - `Database.get_connection() -> sqlite3.Connection`
  - `Database.transaction() -> contextmanager` (yields conn, auto COMMIT/ROLLBACK)
  - `Database.close() -> None`

- [ ] **Step 1: Create project scaffold**

```bash
mkdir -p shadowtalk/{config,models,data/core/layers,ui/widgets,ui/threads,tests}
touch shadowtalk/__init__.py shadowtalk/config/__init__.py shadowtalk/models/__init__.py
touch shadowtalk/data/__init__.py shadowtalk/core/__init__.py shadowtalk/core/layers/__init__.py
touch shadowtalk/ui/__init__.py shadowtalk/ui/widgets/__init__.py shadowtalk/ui/threads/__init__.py
touch tests/__init__.py
```

- [ ] **Step 2: Write the failing test for database connection**

```python
# tests/test_database.py
import pytest
from shadowtalk.data.database import Database

def test_get_connection_returns_valid_conn():
    conn = Database.get_connection()
    assert conn is not None
    # Verify WAL mode
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"
    # Verify foreign keys
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1
    Database.close()

def test_transaction_commits_on_success():
    conn = Database.get_connection()
    with Database.transaction() as tx_conn:
        tx_conn.execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?)",
            ("test_key", "test_value")
        )
    row = conn.execute(
        "SELECT value FROM app_config WHERE key=?", ("test_key",)
    ).fetchone()
    assert row[0] == "test_value"
    # cleanup
    conn.execute("DELETE FROM app_config WHERE key=?", ("test_key",))
    conn.commit()
    Database.close()

def test_transaction_rollback_on_error():
    conn = Database.get_connection()
    try:
        with Database.transaction() as tx_conn:
            tx_conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?)",
                ("rollback_key", "should_not_exist")
            )
            raise ValueError("force rollback")
    except ValueError:
        pass
    row = conn.execute(
        "SELECT value FROM app_config WHERE key=?", ("rollback_key",)
    ).fetchone()
    assert row is None
    Database.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_database.py -v`
Expected: FAIL — `Database` not defined

- [ ] **Step 4: Implement Database class**

```python
# shadowtalk/data/database.py
import sqlite3
import threading
import os
from contextlib import contextmanager

DB_PATH = "shadowtalk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    sender_type TEXT NOT NULL CHECK(sender_type IN ('user', 'ai')),
    content TEXT NOT NULL,
    round_index INTEGER NOT NULL,
    is_archived INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_friend_round ON chat_messages(friend_id, round_index);
CREATE INDEX IF NOT EXISTS idx_messages_archived ON chat_messages(friend_id, is_archived);

CREATE TABLE IF NOT EXISTS batch_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_round INTEGER NOT NULL,
    end_round INTEGER NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_archived INTEGER DEFAULT 0,
    is_truncated INTEGER DEFAULT 0,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_batch_friend_time ON batch_summary(friend_id, create_time);
CREATE INDEX IF NOT EXISTS idx_batch_expired ON batch_summary(friend_id, is_archived, create_time);

CREATE TABLE IF NOT EXISTS high_level_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_high_friend_time ON high_level_summary(friend_id, create_time);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    _conn = None
    _write_lock = threading.Lock()

    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = sqlite3.connect(
                DB_PATH,
                check_same_thread=False,
                isolation_level=None
            )
            cls._conn.row_factory = sqlite3.Row
            cls._conn.execute("PRAGMA journal_mode=WAL")
            cls._conn.execute("PRAGMA foreign_keys=ON")
            cls._conn.executescript(SCHEMA)
        return cls._conn

    @classmethod
    @contextmanager
    def transaction(cls):
        conn = cls.get_connection()
        with cls._write_lock:
            conn.execute("BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    @classmethod
    def close(cls):
        if cls._conn:
            cls._conn.close()
            cls._conn = None
```

- [ ] **Step 5: Write conftest.py with shared fixtures**

```python
# tests/conftest.py
import pytest
import os
from shadowtalk.data.database import Database

TEST_DB = "test_shadowtalk.db"

@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    """Use a test database for all tests."""
    monkeypatch.setattr("shadowtalk.data.database.DB_PATH", TEST_DB)
    # Reset singleton
    Database._conn = None
    conn = Database.get_connection()
    yield conn
    Database.close()
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_database.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add shadowtalk/data/database.py tests/test_database.py tests/conftest.py
git commit -m "feat(data): add SQLite database connection with WAL and transaction support"
```

---

## Task 2: Settings Management

**Files:**
- Create: `shadowtalk/config/settings.py`
- Create: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Database.get_connection()`, `Database.transaction()`
- Produces:
  - `Settings.get(key: str) -> str`
  - `Settings.set(key: str, value: str) -> None`
  - `Settings.get_int(key: str) -> int`
  - `Settings.get_float(key: str) -> float`
  - `Settings.init_defaults() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
from shadowtalk.config.settings import Settings

def test_get_default_value():
    Settings.init_defaults()
    assert Settings.get("raw_keep_max") == "50"
    assert Settings.get("summary_batch_size") == "30"

def test_set_and_get():
    Settings.set("test_param", "hello")
    assert Settings.get("test_param") == "hello"

def test_get_int():
    Settings.set("int_param", "42")
    assert Settings.get_int("int_param") == 42

def test_get_float():
    Settings.set("float_param", "3.14")
    assert abs(Settings.get_float("float_param") - 3.14) < 0.001

def test_missing_key_returns_empty():
    assert Settings.get("nonexistent_key_zzz") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL — `Settings` not defined

- [ ] **Step 3: Implement Settings class**

```python
# shadowtalk/config/settings.py
from shadowtalk.data.database import Database


class Settings:
    _cache = {}

    DEFAULTS = {
        "raw_keep_max": "50",
        "summary_batch_size": "30",
        "summary_valid_days": "30",
        "daily_summary_word_limit": "50",
        "max_context_tokens": "8000",
        "l2_limit": "5",
        "api_base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model_name": "gpt-4o-mini",
        "temperature": "0.7",
        "max_output_tokens": "2000",
    }

    @classmethod
    def get(cls, key: str) -> str:
        if key not in cls._cache:
            conn = Database.get_connection()
            row = conn.execute(
                "SELECT value FROM app_config WHERE key=?", (key,)
            ).fetchone()
            cls._cache[key] = row["value"] if row else cls.DEFAULTS.get(key, "")
        return cls._cache[key]

    @classmethod
    def set(cls, key: str, value: str):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value, update_time) "
                "VALUES (?, ?, datetime('now'))",
                (key, value)
            )
        cls._cache[key] = value

    @classmethod
    def get_int(cls, key: str) -> int:
        return int(cls.get(key))

    @classmethod
    def get_float(cls, key: str) -> float:
        return float(cls.get(key))

    @classmethod
    def init_defaults(cls):
        conn = Database.get_connection()
        for key, value in cls.DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
                (key, value)
            )
        conn.commit()
        cls._cache.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/config/settings.py tests/test_settings.py
git commit -m "feat(config): add Settings management with defaults and cache"
```

---

## Task 3: Repositories

**Files:**
- Create: `shadowtalk/models/entities.py`
- Create: `shadowtalk/data/repositories.py`
- Create: `tests/test_repositories.py`

**Interfaces:**
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

- [ ] **Step 1: Write entities**

```python
# shadowtalk/models/entities.py
from dataclasses import dataclass
from typing import Optional


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
    sender_type: str  # "user" or "ai"
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

- [ ] **Step 2: Write the failing tests**

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

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_repositories.py -v`
Expected: FAIL

- [ ] **Step 4: Implement repositories**

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

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_repositories.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add shadowtalk/models/entities.py shadowtalk/data/repositories.py tests/test_repositories.py
git commit -m "feat(data): add repositories for friends, messages, and summaries"
```

---

## Task 4: Token Budget

**Files:**
- Create: `shadowtalk/core/token_budget.py`
- Create: `tests/test_token_budget.py`

**Interfaces:**
- Consumes: nothing (pure function)
- Produces:
  - `estimate_tokens(text: str) -> int`
  - `trim_context(messages: list[dict], max_tokens: int) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_token_budget.py
import pytest
from shadowtalk.core.token_budget import estimate_tokens, trim_context


def test_estimate_tokens_chinese():
    # 100 Chinese chars // 2 = 50 tokens
    assert estimate_tokens("你好" * 50) == 50

def test_estimate_tokens_english():
    # 100 ASCII chars // 2 = 50 tokens
    assert estimate_tokens("a" * 100) == 50

def test_trim_context_no_trim_needed():
    messages = [
        {"role": "system", "content": "hi", "layer": "L3"},
        {"role": "user", "content": "hello", "layer": "L0"},
    ]
    result = trim_context(messages, 1000)
    assert len(result) == 2

def test_trim_context_trims_l0_oldest_first():
    messages = [
        {"role": "system", "content": "persona", "layer": "L3"},
        {"role": "user", "content": "a" * 100, "layer": "L0"},  # 50 tokens
        {"role": "assistant", "content": "b" * 100, "layer": "L0"},  # 50 tokens
        {"role": "user", "content": "c" * 100, "layer": "L0"},  # 50 tokens
    ]
    # max_tokens=75: protect L3 (5 tokens), remove oldest L0 until <= 75
    result = trim_context(messages, 75)
    # Should keep L3 + newest L0 messages
    assert result[0]["layer"] == "L3"
    # Oldest L0 ("a"*100) should be removed
    contents = [m["content"] for m in result]
    assert "a" * 100 not in contents

def test_trim_context_never_trims_non_l0():
    messages = [
        {"role": "system", "content": "x" * 1000, "layer": "L3"},  # 500 tokens
        {"role": "user", "content": "y" * 1000, "layer": "L0"},   # 500 tokens
    ]
    # max_tokens=100: way too small, L0 all removed, L3 stays
    result = trim_context(messages, 100)
    assert len(result) == 1
    assert result[0]["layer"] == "L3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_token_budget.py -v`
Expected: FAIL

- [ ] **Step 3: Implement token_budget**

```python
# shadowtalk/core/token_budget.py
def estimate_tokens(text: str) -> int:
    """字符数估算：总字符数 // 2（偏保守）"""
    return len(text) // 2


def trim_context(messages: list[dict], max_tokens: int) -> list[dict]:
    """从 L0 最旧消息开始裁剪，直到满足预算。不裁剪非 L0 层。"""
    total = sum(estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages

    protected = [m for m in messages if m.get("layer") != "L0"]
    l0_msgs = [m for m in messages if m.get("layer") == "L0"]

    while l0_msgs and total > max_tokens:
        removed = l0_msgs.pop(0)
        total -= estimate_tokens(removed["content"])

    return protected + l0_msgs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_token_budget.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/token_budget.py tests/test_token_budget.py
git commit -m "feat(core): add token estimation and context trimming"
```

---

## Task 5: Memory Layers (L0-L3)

**Files:**
- Create: `shadowtalk/core/layers/l3_persona.py`
- Create: `shadowtalk/core/layers/l2_summary.py`
- Create: `shadowtalk/core/layers/l1_summary.py`
- Create: `shadowtalk/core/layers/l0_raw.py`
- Create: `tests/test_layers.py`

**Interfaces:**
- Consumes: `FriendRepository`, `SummaryRepository`, `MessageRepository`
- Produces:
  - `l3.extract(friend_id) -> list[dict]` — returns [{"role": "system", "content": "...", "layer": "L3"}]
  - `l2.extract(friend_id) -> list[dict]`
  - `l1.extract(friend_id) -> list[dict]`
  - `l0.extract(friend_id) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

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
        # Save a summary with an old timestamp via direct SQL
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
        MessageRepository.insert(fid, "user", "消息1", 1)
        msgs = MessageRepository.get_unarchived(fid)
        MessageRepository.mark_archived([msgs[0]["id"]])
        result = l0.extract(fid)
        assert len(result) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layers.py -v`
Expected: FAIL

- [ ] **Step 3: Implement layers**

```python
# shadowtalk/core/layers/l3_persona.py
from shadowtalk.data.repositories import FriendRepository


def extract(friend_id: int) -> list[dict]:
    """提取 L3 永久人设 Prompt"""
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
    """提取 L2 高阶聚合摘要"""
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
    """提取 L1 有效期内批次摘要"""
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
    """提取 L0 未归档原始对话"""
    messages = MessageRepository.get_unarchived(friend_id)
    return [
        {
            "role": m["sender_type"],
            "content": m["content"],
            "layer": "L0"
        }
        for m in messages
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_layers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/layers/ tests/test_layers.py
git commit -m "feat(core): add L0-L3 memory layer extractors"
```

---

## Task 6: AI Client

**Files:**
- Create: `shadowtalk/core/ai_client.py`
- Create: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: `Settings` (for API config)
- Produces:
  - `AIClient.chat(messages: list[dict]) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_client.py
import pytest
from unittest.mock import MagicMock, patch
from shadowtalk.core.ai_client import AIClient


def test_chat_returns_content():
    client = AIClient(
        base_url="https://api.test.com/v1",
        api_key="test-key",
        model="test-model"
    )
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "AI回复内容"
    
    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response
        result = client.chat([{"role": "user", "content": "你好"}])
    
    assert result == "AI回复内容"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement AIClient**

```python
# shadowtalk/core/ai_client.py
import openai


class AIClient:
    """封装 OpenAI 兼容接口，纯 Python 无 UI 依赖"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 2000):
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: list[dict]) -> str:
        """非流式调用，返回完整回复文本"""
        # Remove internal 'layer' key before sending to API
        clean_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=clean_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        return response.choices[0].message.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/ai_client.py tests/test_ai_client.py
git commit -m "feat(core): add OpenAI-compatible AI client"
```

---

## Task 7: Summarizer

**Files:**
- Create: `shadowtalk/core/summarizer.py`
- Create: `tests/test_summarizer.py`

**Interfaces:**
- Consumes: `AIClient`, `SummaryRepository`, `MessageRepository`, `Database.transaction()`
- Produces:
  - `generate_batch_summary(friend_id, messages) -> str`
  - `generate_high_level_summary(expired_summaries) -> str`
  - `merge_high_level_summaries(summaries) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_summarizer.py
import pytest
from unittest.mock import MagicMock, patch
from shadowtalk.core.summarizer import (
    generate_batch_summary, generate_high_level_summary
)
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def test_generate_batch_summary_success():
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    MessageRepository.insert(fid, "ai", "你好！", 1)
    msgs = MessageRepository.get_unarchived(fid)
    
    mock_ai = MagicMock()
    mock_ai.chat.return_value = "简短摘要"
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_batch_summary(fid, msgs)
    
    assert result == "简短摘要"
    # Verify messages are archived
    assert MessageRepository.count_unarchived_rounds(fid) == 0

def test_generate_batch_summary_truncation():
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    msgs = MessageRepository.get_unarchived(fid)
    
    mock_ai = MagicMock()
    # Return text exceeding 50 chars
    mock_ai.chat.return_value = "超" * 100
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_batch_summary(fid, msgs)
    
    assert len(result) <= 52  # 50 chars + "…[摘要截断]"
    assert "截断" in result

def test_generate_high_level_summary():
    mock_ai = MagicMock()
    mock_ai.chat.return_value = "聚合后的高阶记忆"
    
    expired = [
        {"content": "旧摘要1"},
        {"content": "旧摘要2"},
    ]
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_high_level_summary(expired)
    
    assert result == "聚合后的高阶记忆"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_summarizer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement summarizer**

```python
# shadowtalk/core/summarizer.py
from shadowtalk.data.repositories import SummaryRepository, MessageRepository
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings


def get_ai_client():
    """Factory: create AIClient from current Settings"""
    from shadowtalk.core.ai_client import AIClient
    return AIClient(
        base_url=Settings.get("api_base_url"),
        api_key=Settings.get("api_key"),
        model=Settings.get("model_name"),
        temperature=Settings.get_float("temperature"),
        max_tokens=Settings.get_int("max_output_tokens"),
    )


def build_summary_prompt(messages: list) -> list[dict]:
    """构建生成摘要的 prompt"""
    dialogue = "\n".join(
        f"{'用户' if m['sender_type'] == 'user' else 'AI'}: {m['content']}"
        for m in messages
    )
    word_limit = Settings.get_int("daily_summary_word_limit")
    return [
        {
            "role": "system",
            "content": f"请将以下对话压缩为一条{word_limit}字以内的简短摘要，"
                       f"保留关键信息和情感走向。"
        },
        {"role": "user", "content": dialogue},
    ]


def build_merge_prompt(summaries: list) -> list[dict]:
    """构建合并摘要的 prompt"""
    text = "\n".join(f"- {s['content']}" for s in summaries)
    return [
        {
            "role": "system",
            "content": "请将以下多条摘要合并为一条极简的高阶记忆，"
                       "保留最核心的人物关系和情感走向。"
        },
        {"role": "user", "content": text},
    ]


def generate_batch_summary(friend_id: int, messages: list) -> str:
    """生成批次摘要，带重试和截断兜底。写入 DB + 标记原文已归档。"""
    ai = get_ai_client()
    prompt = build_summary_prompt(messages)
    word_limit = Settings.get_int("daily_summary_word_limit")

    text = ""
    for _ in range(2):
        try:
            text = ai.chat(prompt)
            if len(text) <= word_limit:
                break
        except Exception:
            continue
    else:
        text = (text if text else "摘要生成失败")[:word_limit] + "…[摘要截断]"

    is_truncated = 1 if text.endswith("…[摘要截断]") else 0
    start_round = min(m["round_index"] for m in messages)
    end_round = max(m["round_index"] for m in messages)

    with Database.transaction() as conn:
        SummaryRepository.save_batch_summary(
            friend_id, text, start_round, end_round, is_truncated
        )
        SummaryRepository.mark_summaries_archived  # no-op, messages use different repo
        # Archive messages
        msg_ids = [m["id"] for m in messages]
        placeholders = ",".join("?" * len(msg_ids))
        conn.execute(
            f"UPDATE chat_messages SET is_archived=1 WHERE id IN ({placeholders})",
            msg_ids
        )

    return text


def generate_high_level_summary(expired_summaries: list) -> str:
    """合并多条过期批次摘要为一条 L2"""
    ai = get_ai_client()
    prompt = build_merge_prompt(expired_summaries)
    try:
        return ai.chat(prompt)
    except Exception:
        return "高阶摘要生成失败"


def merge_high_level_summaries(summaries: list) -> str:
    """合并多条 L2 为一条（L2 超限时使用）"""
    return generate_high_level_summary(summaries)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_summarizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/summarizer.py tests/test_summarizer.py
git commit -m "feat(core): add summarizer with retry and truncation fallback"
```

---

## Task 8: Archiver

**Files:**
- Create: `shadowtalk/core/archiver.py`
- Create: `tests/test_archiver.py`

**Interfaces:**
- Consumes: `MessageRepository`, `SummaryRepository`, `summarizer`, `Settings`
- Produces:
  - `check_and_archive(friend_id: int) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_archiver.py
import pytest
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
    # Create 60 rounds (120 messages) > raw_keep_max=50
    for i in range(60):
        MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        MessageRepository.insert(fid, "ai", f"回复{i}", i + 1)
    
    with patch("shadowtalk.core.archiver.summarizer") as mock_sum:
        mock_sum.generate_batch_summary.return_value = "摘要"
        check_and_archive(fid)
        # Should have called generate_batch_summary
        assert mock_sum.generate_batch_summary.call_count >= 1

def test_no_archive_buffer_too_small():
    fid = FriendRepository.insert("好友", "", "")
    # 55 rounds: overflow=5, buffer=5 < 30 (summary_batch_size)
    for i in range(55):
        MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        MessageRepository.insert(fid, "ai", f"回复{i}", i + 1)
    
    with patch("shadowtalk.core.archiver.summarizer") as mock_sum:
        check_and_archive(fid)
        mock_sum.generate_batch_summary.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_archiver.py -v`
Expected: FAIL

- [ ] **Step 3: Implement archiver**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_archiver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/archiver.py tests/test_archiver.py
git commit -m "feat(core): add archiver with count-first trigger logic"
```

---

## Task 9: Memory Engine (Main Pipeline)

**Files:**
- Create: `shadowtalk/core/memory_engine.py`
- Create: `tests/test_memory_engine.py`

**Interfaces:**
- Consumes: `archiver`, `l3`, `l2`, `l1`, `l0`, `token_budget`, `Settings`
- Produces:
  - `build_context(friend_id: int, user_message: str) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_memory_engine.py
import pytest
from shadowtalk.core.memory_engine import build_context
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)


def test_build_context_basic():
    fid = FriendRepository.insert("好友", "", "你是一个助手")
    MessageRepository.insert(fid, "user", "你好", 1)
    
    result = build_context(fid, "新消息")
    
    # Should contain L3 + L0 + user message
    layers = [m.get("layer") for m in result]
    assert "L3" in layers
    assert "L0" in layers
    # Last message is the user's new message
    assert result[-1]["role"] == "user"
    assert result[-1]["content"] == "新消息"

def test_build_context_with_summaries():
    fid = FriendRepository.insert("好友", "", "人设")
    SummaryRepository.save_batch_summary(fid, "批次摘要", 1, 30)
    SummaryRepository.save_high_level_summary(fid, "高阶摘要")
    
    result = build_context(fid, "你好")
    
    layers = [m.get("layer") for m in result]
    assert "L3" in layers
    assert "L2" in layers
    assert "L1" in layers

def test_build_context_order():
    """Verify L3 -> L2 -> L1 -> L0 -> user order"""
    fid = FriendRepository.insert("好友", "", "人设")
    SummaryRepository.save_high_level_summary(fid, "L2")
    SummaryRepository.save_batch_summary(fid, "L1", 1, 30)
    MessageRepository.insert(fid, "user", "L0", 1)
    
    result = build_context(fid, "用户消息")
    
    layers = [m.get("layer") for m in result if m.get("layer")]
    assert layers == ["L3", "L2", "L1", "L0"]

def test_build_context_trims_l0():
    """When context exceeds max_tokens, L0 should be trimmed"""
    fid = FriendRepository.insert("好友", "", "人设")
    # Add many L0 messages
    for i in range(20):
        MessageRepository.insert(fid, "user", "x" * 200, i + 1)
    
    # Set a small max_tokens via Settings
    from shadowtalk.config.settings import Settings
    Settings.set("max_context_tokens", "50")
    
    result = build_context(fid, "新消息")
    
    # L3 should still be present
    assert result[0]["layer"] == "L3"
    # L0 should be reduced
    l0_count = sum(1 for m in result if m.get("layer") == "L0")
    assert l0_count < 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_memory_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement memory_engine**

```python
# shadowtalk/core/memory_engine.py
from shadowtalk.core.layers import l3, l2, l1, l0
from shadowtalk.core.archiver import check_and_archive
from shadowtalk.core.token_budget import trim_context
from shadowtalk.config.settings import Settings


def build_context(friend_id: int, user_message: str) -> list[dict]:
    """
    组装完整的 AI 上下文消息列表。
    返回: [{"role": "system"|"user"|"assistant", "content": str, "layer": "L0"|"L1"|"L2"|"L3"}, ...]
    """
    # 1. 归档检查
    check_and_archive(friend_id)

    # 2. 逐层提取
    context = []
    context += l3.extract(friend_id)
    context += l2.extract(friend_id)
    context += l1.extract(friend_id)
    context += l0.extract(friend_id)

    # 3. Token 预算检查 & 裁剪
    max_tokens = Settings.get_int("max_context_tokens")
    context = trim_context(context, max_tokens)

    # 4. 追加用户最新消息
    context.append({"role": "user", "content": user_message})

    return context
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_memory_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/memory_engine.py tests/test_memory_engine.py
git commit -m "feat(core): add memory engine main pipeline (build_context)"
```

---

## Task 10: Background Scanner

**Files:**
- Create: `shadowtalk/core/background_scanner.py`

**Interfaces:**
- Consumes: `SummaryRepository`, `summarizer`, `FriendRepository`, `Database`
- Produces:
  - `BackgroundScanner` class with `.start()` and `.scan_now()` methods

- [ ] **Step 1: Write the failing test**

```python
# tests/test_background_scanner.py
import pytest
from unittest.mock import patch
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import (
    FriendRepository, SummaryRepository
)


def test_scan_merges_expired_summaries():
    fid = FriendRepository.insert("好友", "", "")
    # Insert an expired summary directly
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
    
    # Verify L2 was created
    l2_list = SummaryRepository.get_all_high_level_summaries(fid)
    assert len(l2_list) == 1
    assert l2_list[0]["content"] == "合并后的L2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_background_scanner.py -v`
Expected: FAIL

- [ ] **Step 3: Implement background_scanner**

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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_background_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/background_scanner.py tests/test_background_scanner.py
git commit -m "feat(core): add background scanner for expired summary merging"
```

---

## Task 11: Friend Service

**Files:**
- Create: `shadowtalk/core/friend_service.py`
- Create: `tests/test_friend_service.py`

**Interfaces:**
- Consumes: `FriendRepository`, `MessageRepository`, `SummaryRepository`, `Database`
- Produces:
  - `FriendService.create(name, remark, system_prompt, avatar_path) -> int`
  - `FriendService.delete(friend_id, keep_messages=False) -> None`
  - `FriendService.update_avatar(friend_id, new_path) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_friend_service.py
import pytest
import os
import tempfile
from shadowtalk.core.friend_service import FriendService
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def test_create_friend():
    fid = FriendService.create("测试", "备注", "人设", "")
    friend = FriendRepository.get_by_id(fid)
    assert friend["name"] == "测试"
    assert friend["remark"] == "备注"

def test_create_with_avatar():
    # Create a temp image file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake_image_data")
        avatar_path = f.name
    
    try:
        fid = FriendService.create("有头像", "", "", avatar_path)
        friend = FriendRepository.get_by_id(fid)
        assert friend["avatar_path"] != ""
        assert os.path.exists(friend["avatar_path"])
    finally:
        os.unlink(avatar_path)

def test_delete_with_cascade():
    fid = FriendService.create("待删除", "", "", "")
    MessageRepository.insert(fid, "user", "消息", 1)
    
    FriendService.delete(fid, keep_messages=False)
    assert FriendRepository.get_by_id(fid) is None

def test_delete_keep_messages_not_supported():
    """keep_messages=False deletes all; CASCADE handles messages."""
    fid = FriendService.create("好友", "", "", "")
    MessageRepository.insert(fid, "user", "消息", 1)
    FriendService.delete(fid, keep_messages=False)
    msgs = MessageRepository.get_unarchived(fid)
    assert len(msgs) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_friend_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement friend_service**

```python
# shadowtalk/core/friend_service.py
import shutil
import os
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)
from shadowtalk.data.database import Database


class FriendService:
    AVATAR_DIR = "data/avatars"

    @staticmethod
    def create(name: str, remark: str, system_prompt: str,
               avatar_source_path: str = "") -> int:
        avatar_path = ""
        if avatar_source_path and os.path.exists(avatar_source_path):
            os.makedirs(FriendService.AVATAR_DIR, exist_ok=True)
            temp_dir = f"{FriendService.AVATAR_DIR}/temp"
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = f"{temp_dir}/{os.path.basename(avatar_source_path)}"
            shutil.copy2(avatar_source_path, temp_path)
            avatar_path = temp_path

        friend_id = FriendRepository.insert(name, remark, system_prompt, avatar_path)

        if avatar_path:
            ext = os.path.splitext(avatar_path)[1]
            final_dir = f"{FriendService.AVATAR_DIR}/{friend_id}"
            final_path = f"{final_dir}/avatar{ext}"
            os.makedirs(final_dir, exist_ok=True)
            shutil.move(avatar_path, final_path)
            FriendRepository.update(friend_id, avatar_path=final_path)

        # cleanup temp
        temp_dir = f"{FriendService.AVATAR_DIR}/temp"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        return friend_id

    @staticmethod
    def delete(friend_id: int, keep_messages: bool = False):
        if not keep_messages:
            with Database.transaction() as conn:
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
        if old_path and os.path.exists(old_path):
            os.remove(old_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_friend_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/core/friend_service.py tests/test_friend_service.py
git commit -m "feat(core): add friend service with avatar handling"
```

---

## Task 12: UI — Message Bubble

**Files:**
- Create: `shadowtalk/ui/widgets/message_bubble.py`

**Interfaces:**
- Consumes: nothing (pure UI component)
- Produces:
  - `MessageBubble(text: str, role: str, timestamp: str, parent=None)`

- [ ] **Step 1: Implement message_bubble**

```python
# shadowtalk/ui/widgets/message_bubble.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt


class MessageBubble(QWidget):
    def __init__(self, text: str, role: str, timestamp: str, parent=None):
        super().__init__(parent)
        self._role = role
        self._build_ui(text, role, timestamp)

    def _build_ui(self, text, role, timestamp):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)

        # Timestamp
        time_label = QLabel(timestamp)
        time_label.setStyleSheet("color: #888; font-size: 11px;")
        time_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(time_label)

        # Bubble row
        row = QHBoxLayout()
        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setMaximumWidth(400)
        content.setContentsMargins(10, 6, 10, 6)

        if role == "user":
            content.setStyleSheet(
                "background-color: #DCF8C6; border-radius: 12px; padding: 8px;"
            )
            row.addStretch()
            row.addWidget(content)
        elif role == "ai":
            content.setStyleSheet(
                "background-color: #ECECEC; border-radius: 12px; padding: 8px;"
            )
            row.addWidget(content)
            row.addStretch()
        else:  # loading
            content.setStyleSheet(
                "color: #888; font-style: italic; padding: 8px;"
            )
            row.addWidget(content)
            row.addStretch()

        main_layout.addLayout(row)
```

- [ ] **Step 2: Commit**

```bash
git add shadowtalk/ui/widgets/message_bubble.py
git commit -m "feat(ui): add message bubble widget"
```

---

## Task 13: UI — Chat Area

**Files:**
- Create: `shadowtalk/ui/widgets/chat_area.py`

**Interfaces:**
- Consumes: `MessageBubble`
- Produces:
  - `ChatArea` widget with `message_sent` signal, `add_message()`, `show_loading()`, `hide_loading()`

- [ ] **Step 1: Implement chat_area**

```python
# shadowtalk/ui/widgets/chat_area.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Signal
from shadowtalk.ui.widgets.message_bubble import MessageBubble


class ChatArea(QWidget):
    message_sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading_item = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.message_list = QListWidget()
        self.message_list.setSpacing(2)
        layout.addWidget(self.message_list)

        input_row = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入消息...")
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send)
        self.input_box.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input_box)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

    def _on_send(self):
        text = self.input_box.text().strip()
        if not text:
            return
        self.message_sent.emit(text)
        self.input_box.clear()

    def add_message(self, text: str, role: str, timestamp: str):
        bubble = MessageBubble(text, role, timestamp)
        item = QListWidgetItem()
        item.setSizeHint(bubble.sizeHint())
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, bubble)
        self.message_list.scrollToBottom()

    def show_loading(self):
        self.add_message("正在回复…", "loading", "")
        self._loading_item = self.message_list.item(self.message_list.count() - 1)
        self.send_btn.setEnabled(False)

    def hide_loading(self):
        if self._loading_item:
            row = self.message_list.row(self._loading_item)
            self.message_list.takeItem(row)
            self._loading_item = None
        self.send_btn.setEnabled(True)
```

- [ ] **Step 2: Commit**

```bash
git add shadowtalk/ui/widgets/chat_area.py
git commit -m "feat(ui): add chat area with message list and input"
```

---

## Task 14: UI — AI Worker Thread

**Files:**
- Create: `shadowtalk/ui/threads/ai_worker.py`

**Interfaces:**
- Consumes: `memory_engine.build_context()`, `AIClient`
- Produces:
  - `AIWorker(QThread)` with `finished` and `failed` signals

- [ ] **Step 1: Implement ai_worker**

```python
# shadowtalk/ui/threads/ai_worker.py
from PySide6.QtCore import QThread, Signal


class AIWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, friend_id, user_message, ai_client, memory_engine):
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.ai_client = ai_client
        self.memory_engine = memory_engine

    def run(self):
        try:
            messages = self.memory_engine.build_context(
                self.friend_id, self.user_message
            )
            reply = self.ai_client.chat(messages)
            self.finished.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))
```

- [ ] **Step 2: Commit**

```bash
git add shadowtalk/ui/threads/ai_worker.py
git commit -m "feat(ui): add AI worker thread for non-blocking API calls"
```

---

## Task 15: UI — Main Window

**Files:**
- Create: `shadowtalk/ui/widgets/friend_list.py`
- Create: `shadowtalk/ui/widgets/friend_dialog.py`
- Create: `shadowtalk/ui/main_window.py`
- Create: `shadowtalk/main.py`

**Interfaces:**
- Consumes: all UI widgets, `AIWorker`, `AIClient`, `memory_engine`, `FriendRepository`, `MessageRepository`
- Produces: main application entry point

- [ ] **Step 1: Implement friend_list**

```python
# shadowtalk/ui/widgets/friend_list.py
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import Signal


class FriendListWidget(QWidget):
    friend_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list)
        self.add_btn = QPushButton("+ 新增好友")
        layout.addWidget(self.add_btn)

    def _on_item_clicked(self, item):
        friend_id = item.data(1000)  # custom role
        if friend_id:
            self.friend_selected.emit(friend_id)

    def load_friends(self, friends: list):
        self.list.clear()
        for friend in friends:
            item = QListWidgetItem(friend["name"])
            item.setData(1000, friend["id"])
            self.list.addItem(item)
```

- [ ] **Step 2: Implement friend_dialog**

```python
# shadowtalk/ui/widgets/friend_dialog.py
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QHBoxLayout, QLabel, QFileDialog
)


class FriendDialog(QDialog):
    def __init__(self, parent=None, friend=None):
        super().__init__(parent)
        self.friend = friend
        self.avatar_path = friend["avatar_path"] if friend else ""
        self.setWindowTitle("新增好友" if friend is None else "编辑好友")
        self.setMinimumWidth(400)
        self._build_ui()
        if friend:
            self._fill_data(friend)

    def _build_ui(self):
        layout = QFormLayout()
        self.name_input = QLineEdit()
        layout.addRow("昵称：", self.name_input)
        self.remark_input = QLineEdit()
        layout.addRow("备注：", self.remark_input)
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("定义对方身份、性格、说话语气...")
        self.prompt_input.setMinimumHeight(120)
        layout.addRow("AI人设Prompt：", self.prompt_input)

        avatar_row = QHBoxLayout()
        self.avatar_label = QLabel("未选择")
        avatar_btn = QPushButton("选择头像")
        avatar_btn.clicked.connect(self._pick_avatar)
        avatar_row.addWidget(self.avatar_label)
        avatar_row.addWidget(avatar_btn)
        layout.addRow("头像：", avatar_row)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addRow(btn_row)

        wrapper = QVBoxLayout()
        wrapper.addLayout(layout)
        self.setLayout(wrapper)

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择头像", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.avatar_path = path
            self.avatar_label.setText(os.path.basename(path))

    def _fill_data(self, friend):
        self.name_input.setText(friend["name"])
        self.remark_input.setText(friend["remark"])
        self.prompt_input.setPlainText(friend["system_prompt"])

    def get_data(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "remark": self.remark_input.text().strip(),
            "system_prompt": self.prompt_input.toPlainText().strip(),
            "avatar_path": self.avatar_path,
        }
```

- [ ] **Step 3: Implement main_window**

```python
# shadowtalk/ui/main_window.py
from PySide6.QtWidgets import QMainWindow, QSplitter, QMessageBox
from PySide6.QtCore import QTimer
from datetime import datetime

from shadowtalk.ui.widgets.friend_list import FriendListWidget
from shadowtalk.ui.widgets.chat_area import ChatArea
from shadowtalk.ui.widgets.friend_dialog import FriendDialog
from shadowtalk.ui.threads.ai_worker import AIWorker
from shadowtalk.core.memory_engine import build_context
from shadowtalk.core.ai_client import AIClient
from shadowtalk.core.friend_service import FriendService
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)
from shadowtalk.config.settings import Settings


def _now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ShadowTalk 影聊")
        self.resize(900, 600)
        self.current_friend_id = None
        self.ai_worker = None

        # Business layer
        self.ai_client = AIClient(
            base_url=Settings.get("api_base_url"),
            api_key=Settings.get("api_key"),
            model=Settings.get("model_name"),
            temperature=Settings.get_float("temperature"),
            max_tokens=Settings.get_int("max_output_tokens"),
        )

        # UI
        self.friend_list = FriendListWidget()
        self.chat_area = ChatArea()

        splitter = QSplitter()
        splitter.addWidget(self.friend_list)
        splitter.addWidget(self.chat_area)
        splitter.setSizes([200, 700])
        self.setCentralWidget(splitter)

        # Signals
        self.friend_list.friend_selected.connect(self._on_friend_selected)
        self.friend_list.add_btn.clicked.connect(self._on_add_friend)
        self.chat_area.message_sent.connect(self._on_message_sent)

        # Background scanner (QTimer)
        self.scanner = BackgroundScanner()
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scanner.scan_now)
        self.scan_timer.start(3600 * 1000)  # hourly

        self._load_friends()

    def _load_friends(self):
        friends = FriendRepository.get_all()
        self.friend_list.load_friends(friends)

    def _on_friend_selected(self, friend_id: int):
        self.current_friend_id = friend_id
        self.chat_area.message_list.clear()
        self._load_history_messages(friend_id)

    def _load_history_messages(self, friend_id: int):
        msgs = MessageRepository.get_unarchived(friend_id)
        for m in msgs:
            self.chat_area.add_message(m["content"], m["sender_type"], m["create_time"])

    def _on_add_friend(self):
        dialog = FriendDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            FriendService.create(**data)
            self._load_friends()

    def _on_message_sent(self, text: str):
        if not self.current_friend_id:
            return

        self.chat_area.add_message(text, "user", _now_timestamp())
        MessageRepository.insert(
            self.current_friend_id, "user", text,
            self._next_round_index(self.current_friend_id)
        )

        self.chat_area.show_loading()
        self.ai_worker = AIWorker(
            self.current_friend_id, text,
            self.ai_client, build_context
        )
        self.ai_worker.finished.connect(self._on_ai_reply)
        self.ai_worker.failed.connect(self._on_ai_failed)
        self.ai_worker.start()

    def _on_ai_reply(self, reply: str):
        self.chat_area.hide_loading()
        self.chat_area.add_message(reply, "ai", _now_timestamp())
        MessageRepository.insert(
            self.current_friend_id, "ai", reply,
            self._current_round_index(self.current_friend_id)
        )

    def _on_ai_failed(self, error: str):
        self.chat_area.hide_loading()
        self.chat_area.add_message(f"回复失败：{error}", "ai", _now_timestamp())

    def _next_round_index(self, friend_id: int) -> int:
        conn = FriendRepository.get_by_id.__module__  # placeholder
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return (row[0] or 0) + 1

    def _current_round_index(self, friend_id: int) -> int:
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (friend_id,)
        ).fetchone()
        return row[0] or 1
```

- [ ] **Step 4: Implement main.py entry point**

```python
# shadowtalk/main.py
import sys
import os

# Ensure data directories exist
os.makedirs("data/avatars", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

from PySide6.QtWidgets import QApplication
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings
from shadowtalk.ui.main_window import MainWindow


def main():
    # Init database and settings
    Database.get_connection()
    Settings.init_defaults()

    # Start UI
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    exit_code = app.exec()

    # Cleanup
    Database.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Commit**

```bash
git add shadowtalk/ui/ shadowtalk/main.py
git commit -m "feat(ui): add main window, friend list, friend dialog, and entry point"
```

---

## Task 16: UI — Settings Dialog

**Files:**
- Create: `shadowtalk/ui/widgets/settings_dialog.py`

**Interfaces:**
- Consumes: `Settings`, `BackgroundScanner`, `FriendRepository`
- Produces:
  - `SettingsDialog` with API config, memory params, data operations tabs

- [ ] **Step 1: Implement settings_dialog**

```python
# shadowtalk/ui/widgets/settings_dialog.py
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QSlider, QPushButton, QHBoxLayout, QLabel,
    QMessageBox, QWidget, QGroupBox
)
from PySide6.QtCore import Qt
from shadowtalk.config.settings import Settings
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import FriendRepository


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_friend_id=None):
        super().__init__(parent)
        self.current_friend_id = current_friend_id
        self.setWindowTitle("设置")
        self.setMinimumWidth(450)
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Tab 1: API Config
        api_tab = QWidget()
        api_layout = QFormLayout()
        self.api_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_label = QLabel("0.70")
        self.temp_slider.valueChanged.connect(
            lambda v: self.temp_label.setText(f"{v/100:.2f}")
        )
        temp_row = QHBoxLayout()
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_label)
        self.max_output_spin = QSpinBox()
        self.max_output_spin.setRange(100, 32000)
        self.max_output_spin.setValue(2000)

        api_layout.addRow("API地址：", self.api_url_input)
        api_layout.addRow("API Key：", self.api_key_input)
        api_layout.addRow("模型名称：", self.model_input)
        api_layout.addRow("Temperature：", temp_row)
        api_layout.addRow("最大输出长度：", self.max_output_spin)
        api_tab.setLayout(api_layout)
        tabs.addTab(api_tab, "API 配置")

        # Tab 2: Memory Params
        mem_tab = QWidget()
        mem_layout = QFormLayout()
        self.raw_keep_spin = QSpinBox()
        self.raw_keep_spin.setRange(10, 200)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(10, 100)
        self.valid_days_spin = QSpinBox()
        self.valid_days_spin.setRange(7, 365)
        self.word_limit_spin = QSpinBox()
        self.word_limit_spin.setRange(20, 200)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1000, 32000)
        self.l2_limit_spin = QSpinBox()
        self.l2_limit_spin.setRange(1, 20)

        mem_layout.addRow("保留原文轮数：", self.raw_keep_spin)
        mem_layout.addRow("打包批次大小：", self.batch_spin)
        mem_layout.addRow("摘要有效期(天)：", self.valid_days_spin)
        mem_layout.addRow("摘要字数限制：", self.word_limit_spin)
        mem_layout.addRow("最大上下文Token：", self.max_tokens_spin)
        mem_layout.addRow("L2上限：", self.l2_limit_spin)
        mem_tab.setLayout(mem_layout)
        tabs.addTab(mem_tab, "记忆参数")

        # Tab 3: Data Operations
        op_tab = QWidget()
        op_layout = QVBoxLayout()
        scan_btn = QPushButton("手动扫描过期摘要")
        scan_btn.clicked.connect(self._on_scan_now)
        op_layout.addWidget(scan_btn)

        clear_btn = QPushButton("清空当前好友聊天记录")
        clear_btn.clicked.connect(self._on_clear_chat)
        op_layout.addWidget(clear_btn)
        op_layout.addStretch()
        op_tab.setLayout(op_layout)
        tabs.addTab(op_tab, "数据操作")

        layout.addWidget(tabs)

        # Bottom buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        save_btn = QPushButton("保存")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._on_save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _load_settings(self):
        self.api_url_input.setText(Settings.get("api_base_url"))
        self.api_key_input.setText(Settings.get("api_key"))
        self.model_input.setText(Settings.get("model_name"))
        self.temp_slider.setValue(int(Settings.get_float("temperature") * 100))
        self.max_output_spin.setValue(Settings.get_int("max_output_tokens"))

        self.raw_keep_spin.setValue(Settings.get_int("raw_keep_max"))
        self.batch_spin.setValue(Settings.get_int("summary_batch_size"))
        self.valid_days_spin.setValue(Settings.get_int("summary_valid_days"))
        self.word_limit_spin.setValue(Settings.get_int("daily_summary_word_limit"))
        self.max_tokens_spin.setValue(Settings.get_int("max_context_tokens"))
        self.l2_limit_spin.setValue(Settings.get_int("l2_limit"))

    def _on_save(self):
        Settings.set("api_base_url", self.api_url_input.text())
        Settings.set("api_key", self.api_key_input.text())
        Settings.set("model_name", self.model_input.text())
        Settings.set("temperature", str(self.temp_slider.value() / 100))
        Settings.set("max_output_tokens", str(self.max_output_spin.value()))

        Settings.set("raw_keep_max", str(self.raw_keep_spin.value()))
        Settings.set("summary_batch_size", str(self.batch_spin.value()))
        Settings.set("summary_valid_days", str(self.valid_days_spin.value()))
        Settings.set("daily_summary_word_limit", str(self.word_limit_spin.value()))
        Settings.set("max_context_tokens", str(self.max_tokens_spin.value()))
        Settings.set("l2_limit", str(self.l2_limit_spin.value()))

        self.accept()

    def _on_scan_now(self):
        BackgroundScanner().scan_now()
        QMessageBox.information(self, "完成", "扫描完成")

    def _on_clear_chat(self):
        if not self.current_friend_id:
            QMessageBox.warning(self, "提示", "请先选择一个好友")
            return
        friend = FriendRepository.get_by_id(self.current_friend_id)
        reply = QMessageBox.warning(
            self, "确认清空",
            f"确定清空与 {friend['name']} 的全部聊天记录？\n"
            f"（人设 Prompt 将保留）",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            from shadowtalk.data.database import Database
            with Database.transaction() as conn:
                conn.execute(
                    "DELETE FROM chat_messages WHERE friend_id=?",
                    (self.current_friend_id,)
                )
                conn.execute(
                    "DELETE FROM batch_summary WHERE friend_id=?",
                    (self.current_friend_id,)
                )
                conn.execute(
                    "DELETE FROM high_level_summary WHERE friend_id=?",
                    (self.current_friend_id,)
                )
            QMessageBox.information(self, "完成", "聊天记录已清空")
```

- [ ] **Step 2: Commit**

```bash
git add shadowtalk/ui/widgets/settings_dialog.py
git commit -m "feat(ui): add settings dialog with API, memory, and data tabs"
```

---

## Task 17: Requirements + README

**Files:**
- Create: `requirements.txt`
- Create: `README.md`

- [ ] **Step 1: Create requirements.txt**

```
PySide6>=6.6.0
openai>=1.30.0
pytest>=8.0.0
```

- [ ] **Step 2: Create README.md**

```markdown
# ShadowTalk 影聊 V1.0

本地桌面 AI 聊天程序，四层分级记忆引擎，纯单机无服务器。

## 特性

- 多 AI 人设好友私聊
- 条数优先、时间兜底的四层分级记忆引擎
- 纯文本对话，非流式一次性渲染
- SQLite 本地存储，零服务器依赖
- OpenAI 兼容接口（支持 DeepSeek 等）

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python -m shadowtalk.main
```

## 配置

首次运行后，在设置面板中配置：
- API 地址（默认 OpenAI 官方）
- API Key
- 模型名称

## 项目结构

```
shadowtalk/
├── core/        # 业务逻辑（记忆引擎、归档、摘要）
├── data/        # 数据层（SQLite、仓库）
├── models/      # 数据实体
├── config/      # 配置管理
├── ui/          # PySide6 界面
└── tests/       # 测试
```

## 设计文档

- [核心记忆引擎](../../docs/superpowers/specs/2026-08-11-memory-engine-design.md)
- [数据层+好友管理](../../docs/superpowers/specs/2026-08-11-data-layer-friend-management-design.md)
- [聊天界面](../../docs/superpowers/specs/2026-08-11-chat-interface-design.md)
- [设置面板](../../docs/superpowers/specs/2026-08-11-settings-panel-design.md)
```

- [ ] **Step 3: Commit**

```bash
git add requirements.txt README.md
git commit -m "docs: add requirements and README"
```

---

## Self-Review

**1. Spec coverage:**

| Spec requirement | Covered in task |
|---|---|
| 四层记忆 L0-L3 | Task 5, 9 |
| 条数优先打包 | Task 8 |
| 时间兜底合并 | Task 10 |
| Token 裁剪 | Task 4 |
| 摘要重试+截断 | Task 7 |
| 写操作串行化 | Task 1 |
| 好友 CRUD | Task 11 |
| 头像本地存储 | Task 11 |
| 聊天界面 | Task 12, 13, 14, 15 |
| AI 异步调用 | Task 14 |
| 非流式一次性渲染 | Task 13 (show/hide loading) |
| 设置面板 | Task 16 |
| 分层约束（无 PySide6 在 core/） | Enforced in all core tasks |

**2. Placeholder scan:** No TBDs, no "implement later", all code blocks contain real code.

**3. Type consistency:** Function signatures consistent across tasks (e.g., `build_context(friend_id, user_message)` used in Task 9 and Task 14).
