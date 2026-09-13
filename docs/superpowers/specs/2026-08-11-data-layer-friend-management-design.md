# ShadowTalk 影聊 — 数据层 + 好友管理设计规格

> 日期：2026-08-11
> 版本：V1.0 第二轮
> 状态：待审核
> 范围：SQLite 数据访问层、好友管理、配置管理、启动初始化

---

## 1. 概述

本轮设计覆盖 ShadowTalk 的数据基础设施，包括：
- SQLite 数据库表结构（最终版）
- 数据库连接与事务管理
- 仓库层（CRUD 封装）
- 好友管理业务逻辑
- 全局配置管理
- 软件启动初始化流程

### 1.1 设计原则

- **原生 SQL**：零依赖、完全控制、SQLite 场景下 SQL 简单
- **单连接 + 写锁**：全局一个 SQLite 连接，写操作通过 `threading.Lock` 串行化
- **本地文件夹存头像**：数据库只存路径，文件复制到 `data/avatars/{friend_id}/`
- **上下文管理器封装事务**：`with db.transaction() as conn:` 原子化写操作

---

## 2. 数据库表结构

### 2.1 friends（好友表）

```sql
CREATE TABLE friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 chat_messages（消息表）

```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    sender_type TEXT NOT NULL CHECK(sender_type IN ('user', 'ai')),
    content TEXT NOT NULL,
    round_index INTEGER NOT NULL,
    is_archived INTEGER DEFAULT 0,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_friend_round ON chat_messages(friend_id, round_index);
CREATE INDEX idx_messages_archived ON chat_messages(friend_id, is_archived);
```

### 2.3 batch_summary（批次摘要表 L1）

```sql
CREATE TABLE batch_summary (
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
CREATE INDEX idx_batch_friend_time ON batch_summary(friend_id, create_time);
CREATE INDEX idx_batch_expired ON batch_summary(friend_id, is_archived, create_time);
```

### 2.4 high_level_summary（高阶聚合摘要表 L2）

```sql
CREATE TABLE high_level_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
CREATE INDEX idx_high_friend_time ON high_level_summary(friend_id, create_time);
```

### 2.5 app_config（全局配置表）

```sql
CREATE TABLE app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.6 相比需求文档的改进

| 改进点 | 说明 |
|---|---|
| `is_truncated` 标记 | 摘要截断时写入标记位，排查记忆异常 |
| 外键 + ON DELETE CASCADE | 删好友自动清理关联数据 |
| 索引优化 | 按查询模式加覆盖索引，避免全表扫描 |
| `CHECK` 约束 | `sender_type` 只允许 user/ai，数据库层防错 |

---

## 3. 数据库连接管理

### 3.1 database.py

```python
import sqlite3
import threading
from contextlib import contextmanager

class Database:
    _instance = None
    _write_lock = threading.Lock()
    _conn = None
    
    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        if cls._conn is None:
            cls._conn = sqlite3.connect(
                "shadowtalk.db",
                check_same_thread=False,
                isolation_level=None
            )
            cls._conn.execute("PRAGMA journal_mode=WAL")
            cls._conn.execute("PRAGMA foreign_keys=ON")
            cls._init_tables()
        return cls._conn
    
    @classmethod
    @contextmanager
    def transaction(cls):
        """事务上下文管理器，自动 BEGIN/COMMIT/ROLLBACK"""
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

### 3.2 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| WAL 模式 | ✅ | 读写并发性能更好，QTimer 后台写不阻塞 UI 读 |
| 手动事务 | ✅ | 打包时"写摘要 + 标记归档"必须原子化 |
| 外键级联删除 | ✅ | 删好友自动清理消息/摘要 |
| 写锁粒度 | 写操作全局串行 | SQLite 单文件场景下最安全 |

---

## 4. 仓库层

### 4.1 MessageRepository

```python
class MessageRepository:
    @staticmethod
    def insert(friend_id, sender_type, content, round_index):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) VALUES (?, ?, ?, ?)",
                (friend_id, sender_type, content, round_index)
            )
    
    @staticmethod
    def get_unarchived(friend_id):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT id, friend_id, sender_type, content, round_index, is_archived, create_time FROM chat_messages WHERE friend_id=? AND is_archived=0 ORDER BY round_index",
            (friend_id,)
        ).fetchall()
    
    @staticmethod
    def get_oldest_unarchived(friend_id, limit):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM chat_messages WHERE friend_id=? AND is_archived=0 ORDER BY round_index LIMIT ?",
            (friend_id, limit)
        ).fetchall()
    
    @staticmethod
    def count_unarchived_rounds(friend_id):
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT COUNT(DISTINCT round_index) FROM chat_messages WHERE friend_id=? AND is_archived=0",
            (friend_id,)
        ).fetchone()
        return row[0]
    
    @staticmethod
    def mark_archived(message_ids: list[int]):
        with Database.transaction() as conn:
            placeholders = ",".join("?" * len(message_ids))
            conn.execute(
                f"UPDATE chat_messages SET is_archived=1 WHERE id IN ({placeholders})",
                message_ids
            )
```

### 4.2 SummaryRepository

```python
class SummaryRepository:
    @staticmethod
    def save_batch_summary(friend_id, content, start_round, end_round, is_truncated=0):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT INTO batch_summary (friend_id, content, start_round, end_round, is_truncated) VALUES (?, ?, ?, ?, ?)",
                (friend_id, content, start_round, end_round, is_truncated)
            )
    
    @staticmethod
    def get_valid_summaries(friend_id, valid_days):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM batch_summary WHERE friend_id=? AND is_archived=0 AND create_time >= datetime('now', ? || ' days') ORDER BY create_time",
            (friend_id, f"-{valid_days}")
        ).fetchall()
    
    @staticmethod
    def get_expired_summaries(friend_id, valid_days):
        conn = Database.get_connection()
        return conn.execute(
            "SELECT * FROM batch_summary WHERE friend_id=? AND is_archived=0 AND create_time < datetime('now', ? || ' days') ORDER BY create_time",
            (friend_id, f"-{valid_days}")
        ).fetchall()
    
    @staticmethod
    def mark_summaries_archived(summary_ids: list[int]):
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
```

### 4.3 FriendRepository

```python
class FriendRepository:
    @staticmethod
    def insert(name, remark, system_prompt, avatar_path=""):
        with Database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO friends (name, remark, system_prompt, avatar_path) VALUES (?, ?, ?, ?)",
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

---

## 5. 好友管理

### 5.1 friend_service.py

```python
import shutil
import os

class FriendService:
    AVATAR_DIR = "data/avatars"
    
    @staticmethod
    def create(name: str, remark: str, system_prompt: str, avatar_source_path: str = "") -> int:
        avatar_path = ""
        if avatar_source_path and os.path.exists(avatar_source_path):
            os.makedirs(FriendService.AVATAR_DIR, exist_ok=True)
            temp_path = f"{FriendService.AVATAR_DIR}/temp/{os.path.basename(avatar_source_path)}"
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
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
        
        # 清理 temp
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

### 5.2 好友实体

```python
@dataclass
class Friend:
    id: int
    name: str
    remark: str
    system_prompt: str
    avatar_path: str
    create_time: str
```

---

## 6. 配置管理

### 6.1 config/settings.py

```python
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
            cls._cache[key] = row[0] if row else cls.DEFAULTS.get(key, "")
        return cls._cache[key]
    
    @classmethod
    def set(cls, key: str, value: str):
        with Database.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value, update_time) VALUES (?, ?, datetime('now'))",
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

---

## 7. 启动初始化

### 7.1 启动流程

```
main.py 启动
  ↓
Database.get_connection()     ← 建立连接 + 建表（IF NOT EXISTS）
  ↓
Settings.init_defaults()      ← 写入默认配置（首次运行）
  ↓
BackgroundScanner.start()     ← 启动 QTimer 后台扫描
  ↓
加载好友列表 → 显示 UI
```

### 7.2 运行时目录结构

```
shadowtalk/
├── shadowtalk.db
├── data/
│   ├── avatars/
│   │   ├── 1/
│   │   │   └── avatar.png
│   │   └── 2/
│   │       └── avatar.jpg
│   └── logs/
│       └── shadowtalk.log
```

---

## 8. 待后续轮次覆盖

本轮**不涉及**：
- 聊天界面如何调用好友管理（第三轮）
- 设置面板如何修改配置（第四轮）
- AI 客户端封装（第三轮）
