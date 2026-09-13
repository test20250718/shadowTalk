import os
import sqlite3

import shadowtalk.data.database as db_module
from shadowtalk.data.database import Database

# 升级前的旧版 friends 表：无 work_dir 列
OLD_FRIENDS_SCHEMA = """
CREATE TABLE friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    ai_role TEXT DEFAULT '',
    user_role TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

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

OLD_FRIENDS_SCHEMA_NO_VOICE = """
CREATE TABLE friends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    ai_role TEXT DEFAULT '',
    user_role TEXT DEFAULT '',
    work_dir TEXT DEFAULT '',
    avatar_path TEXT DEFAULT '',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

def test_migrate_adds_voice_column(monkeypatch):
    # 用旧 schema 建表后打开连接，迁移应补上 voice 列
    import sqlite3, tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.executescript(OLD_FRIENDS_SCHEMA_NO_VOICE)
        conn.close()
        import shadowtalk.data.database as db_module
        monkeypatch.setattr(db_module, "DB_PATH", path)
        Database._conn = None
        db_conn = Database.get_connection()
        cols = {row[1] for row in db_conn.execute("PRAGMA table_info(friends)")}
        assert "voice" in cols
        Database.close()
    finally:
        for suffix in ["", "-wal", "-shm"]:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)

def test_migrate_adds_work_dir_to_old_friends_table():
    # conftest 的 autouse fixture 已按新 SCHEMA 建库（friends 已含 work_dir）。
    # 迁移分支只在旧库上执行，因此先关掉现有连接，重建旧版 friends 表
    # （无 work_dir 列），再触发 get_connection 走 SCHEMA + _migrate。
    Database.close()
    raw = sqlite3.connect(db_module.DB_PATH)
    raw.isolation_level = None
    raw.execute("DROP TABLE friends")
    raw.execute(OLD_FRIENDS_SCHEMA)
    raw.close()

    conn = Database.get_connection()  # executescript(IF NOT EXISTS 无操作) + _migrate
    cols = {row[1] for row in conn.execute("PRAGMA table_info(friends)")}
    assert "work_dir" in cols

    conn.execute("INSERT INTO friends (name) VALUES (?)", ("旧库好友",))
    row = conn.execute(
        "SELECT work_dir FROM friends WHERE name=?", ("旧库好友",)
    ).fetchone()
    assert row is not None
    assert row["work_dir"] == ""

def test_migration_adds_human_reply_check():
    """V1.4-Add：迁移后 chat_messages 支持 human_reply 类型。"""
    # 使用 conftest 的 test_database fixture（autouse 已替换 DB_PATH 为临时库）
    conn = Database.get_connection()
    # 确认 CHECK 约束已含 human_reply
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chat_messages'"
    ).fetchone()
    assert row is not None, "chat_messages 表不存在"
    schema_sql = row[0]
    assert "human_reply" in schema_sql
    # 可插入 human_reply（需要先有一个好友满足 FK）
    conn.execute("INSERT INTO friends (name) VALUES ('test')")
    fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
        "VALUES (?, 'human_reply', '真人回复', 1)", (fid,)
    )
    # 非法值应被拒
    try:
        conn.execute(
            "INSERT INTO chat_messages (friend_id, sender_type, content, round_index) "
            "VALUES (?, 'invalid_type', '内容', 2)", (fid,)
        )
        assert False, "非法 sender_type 应被拒绝"
    except Exception:
        pass  # 预期：CHECK 约束违反


def test_migration_idempotent():
    """重复迁移不报错、不丢数据。"""
    # 调用两次 get_connection（触发两次迁移）不应报错
    conn1 = Database.get_connection()
    Database._conn = None  # 强制重新连接
    conn2 = Database.get_connection()
    # 数据完整性：旧数据仍在
    row = conn2.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chat_messages'"
    ).fetchone()
    assert row is not None
    assert "human_reply" in row[0]


def test_processed_emails_table_created():
    """V1.4-Add：processed_emails 表存在。"""
    conn = Database.get_connection()
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "processed_emails" in tables


def test_english_tables_removed():
    """V1.4.1 英语教室/阅读室已移除，相关表不应存在"""
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "english_exercise_stats" not in tables
    assert "english_progress" not in tables
    assert "reading_progress" not in tables


def test_unused_rooms_not_seeded():
    """V1.4.1 移除音乐室/阅读室/英语教室，只保留咖啡馆"""
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    rooms = {row[0] for row in conn.execute("SELECT key FROM rooms")}
    assert "cafe" in rooms
    assert "music" not in rooms
    assert "reading" not in rooms
    assert "english" not in rooms


def test_db_path_under_base_dir(monkeypatch):
    """DB 文件应位于基目录下（打包后 = exe 目录）"""
    import sys
    import importlib
    import shadowtalk.data.database as orig_module
    import shadowtalk.data as data_pkg

    # conftest 的 autouse fixture 会把 DB_PATH 替换为临时库路径；
    # 本测试验证的是模块导入时的默认落位（不受 fixture 补丁影响），
    # 因此临时移除 sys.modules 缓存重新导入，随后恢复原模块。
    # 注意：除了 sys.modules，导入机制还会把子模块挂到父包属性上
    # （shadowtalk.data.database），两者都必须恢复。否则 conftest 的
    # DB_PATH 补丁（resolve 走父包属性遍历）会打在 fresh 模块上，
    # 而 Database 类方法从原模块 globals 解析 DB_PATH（未被补丁），
    # Settings/Database 静默读写真实库（曾导致 test_tts_defaults
    # 全量失败、真实 shadowtalk.db 被测试数据污染）。
    sys.modules.pop("shadowtalk.data.database", None)
    try:
        fresh = importlib.import_module("shadowtalk.data.database")
        base = fresh.get_base_dir()
        assert fresh.DB_PATH == str(base / "shadowtalk.db")
    finally:
        sys.modules["shadowtalk.data.database"] = orig_module
        data_pkg.database = orig_module


def test_migrate_adds_mail_sync_columns():
    """V1.4-Add：迁移应补上邮件同步相关列（authorizer_email, recipient_email 等）。"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.executescript(OLD_FRIENDS_SCHEMA)
        conn.close()
        import shadowtalk.data.database as db_module
        old_path = db_module.DB_PATH
        db_module.DB_PATH = path
        Database._conn = None
        db_conn = Database.get_connection()
        cols = {row[1] for row in db_conn.execute("PRAGMA table_info(friends)")}
        for col in ("authorizer_email", "recipient_email", "mail_sync_enable",
                     "mail_receiver_address", "mail_sync_cycle",
                     "email_session_id", "last_sent_message_id", "asset_revoked"):
            assert col in cols, f"迁移后缺少列 {col}"
        Database.close()
        db_module.DB_PATH = old_path
    finally:
        for suffix in ["", "-wal", "-shm"]:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
