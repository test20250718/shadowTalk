# Task 1: Project Scaffold + Database Layer

**Files:**
- Create: `shadowtalk/__init__.py`
- Create: `shadowtalk/data/__init__.py`
- Create: `shadowtalk/data/database.py`
- Create: `tests/conftest.py`
- Create: `tests/test_database.py`

## Interfaces
- Consumes: nothing (foundational task)
- Produces:
  - `Database.get_connection() -> sqlite3.Connection`
  - `Database.transaction() -> contextmanager` (yields conn, auto COMMIT/ROLLBACK)
  - `Database.close() -> None`

## Implementation Details

### Database class (`shadowtalk/data/database.py`)

```python
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

### conftest.py

```python
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

### test_database.py

```python
import pytest
from shadowtalk.data.database import Database

def test_get_connection_returns_valid_conn():
    conn = Database.get_connection()
    assert conn is not None
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"
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
    assert row["value"] == "test_value"
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

## TDD Steps
1. Write failing test
2. Run to verify FAIL
3. Implement Database class
4. Run to verify PASS
5. Commit
