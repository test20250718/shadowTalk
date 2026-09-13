# Task 1: Database — new tables and room seed

**Files to modify:**
- `shadowtalk/data/database.py`
- `tests/test_database.py` (add new tests)

**What to do:**

1. Add two new table definitions to the `SCHEMA` string in `shadowtalk/data/database.py`, after the `reading_progress` table:

```sql

CREATE TABLE IF NOT EXISTS english_exercise_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    exercise_type TEXT NOT NULL,
    correct BOOLEAN NOT NULL,
    attempts INTEGER DEFAULT 1,
    time_used REAL,
    is_bonus BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS english_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    word_range TEXT NOT NULL,
    word TEXT NOT NULL,
    status TEXT NOT NULL,
    review_at TEXT,
    times_correct INTEGER DEFAULT 0,
    times_wrong INTEGER DEFAULT 0,
    last_exercise_at DATETIME,
    UNIQUE(friend_id, word_range, word),
    FOREIGN KEY (friend_id) REFERENCES friends(id) ON DELETE CASCADE
);
```

2. Add room seed and migration to `_migrate()` method, after the reading room seed block:

```python
        conn.execute(
            "INSERT OR IGNORE INTO rooms (key, name, scene_prompt) "
            "VALUES ('english', '英语教室', ?)",
            (_ENGLISH_SCENE_PROMPT,)
        )
        conn.execute("UPDATE rooms SET scene_prompt=? WHERE key='english'",
                     (_ENGLISH_SCENE_PROMPT,))
```

3. Add `_ENGLISH_SCENE_PROMPT` constant near the top of `database.py` (after the existing `_READING_SCENE_PROMPT`):

```python
_ENGLISH_SCENE_PROMPT = """你是一位专业的英语一对一教师。

教学原则：
- 系统性：按词库范围有计划地推进，确保覆盖核心词汇
- 间隔重复：根据答题记录，在快要遗忘时安排复习
- 难度递进：先词义辨识，再填空，再组句，最后翻译拼装
- 自由对话是语境补充：从上下文了解学生兴趣和表达水平
- 用 present_exercise 工具出题，等学生答题后再讲解
- 讲解简洁有力，1-3 句话
- 偶尔可以超纲出 1-2 道拓展题（标注为 bonus），但不影响进度统计"""
```

4. Add tests to `tests/test_database.py`:

```python
def test_english_tables_exist():
    """英语教室答题记录表和进度表应在 _migrate 后存在"""
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    tables = {row[1] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "english_exercise_stats" in tables
    assert "english_progress" in tables


def test_english_room_seeded():
    """英语教室房间应在 _migrate 后存在"""
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT name FROM rooms WHERE key='english'").fetchone()
    assert row is not None
    assert row["name"] == "英语教室"
```

**Verification:**
- Run: `pytest tests/test_database.py::test_english_tables_exist tests/test_database.py::test_english_room_seeded -v` → PASS
- Run full suite: `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: add english classroom tables and room seed`
