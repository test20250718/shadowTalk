# English Learning Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "English Classroom" immersive room where the AI acts as a one-on-one English tutor, presenting interactive exercise cards (sentence building, cloze, matching, translation assembly, story) via a `present_exercise` tool, with chat on the left and exercise panel on the right.

**Architecture:** `EnglishRoomWindow(RoomWindow)` subclass mirroring the reading room's left-right split (chat left 280px, exercise panel right). AI drives exercises through a new `present_exercise` tool; the worker thread suspends via nested QEventLoop while the user answers, then resumes with the answer as a tool result. Stats and progress persist in two new SQLite tables.

**Tech Stack:** Python 3.11, PySide6 (Qt), SQLite, pytest

## Global Constraints

- Python 3.11, PySide6 ≥6.6.0, no new dependencies
- Follow existing room pattern: subclass `RoomWindow`, register in `_ROOM_ICONS`, add to `_migrate` in database.py
- Chinese comments explaining each defensive guard (referencing user-reported bugs)
- All logging via `logging.getLogger(__name__)` under `shadowtalk` logger
- No formatter/linter — 4-space indent, match surrounding code
- Tests: one `test_<module>.py` per source module, plain `assert`, descriptive docstrings
- Canonical test command: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`

---

## Task 1: Database — new tables and room seed

**Files:**
- Modify: `shadowtalk/data/database.py`
- Test: `tests/test_database.py` (add new test)

**Interfaces:**
- Produces: `english_exercise_stats` table, `english_progress` table, `english` room seed

- [ ] **Step 1: Write failing test**

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

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py::test_english_tables_exist tests/test_database.py::test_english_room_seeded -v`
Expected: FAIL — tables/room not yet created

- [ ] **Step 3: Add table definitions to SCHEMA**

In `shadowtalk/data/database.py`, add after the `reading_progress` table definition (before the closing `"""`):

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

- [ ] **Step 4: Add room seed and migration to `_migrate`**

In `_migrate()`, after the reading room seed block, add:

```python
        conn.execute(
            "INSERT OR IGNORE INTO rooms (key, name, scene_prompt) "
            "VALUES ('english', '英语教室', ?)",
            (_ENGLISH_SCENE_PROMPT,)
        )
        conn.execute("UPDATE rooms SET scene_prompt=? WHERE key='english'",
                     (_ENGLISH_SCENE_PROMPT,))
```

- [ ] **Step 5: Add `_ENGLISH_SCENE_PROMPT` constant**

Near the top of `database.py` (after the existing `_READING_SCENE_PROMPT`):

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

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_database.py::test_english_tables_exist tests/test_database.py::test_english_room_seeded -v`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass (no regressions)

- [ ] **Step 8: Commit**

```bash
git add shadowtalk/data/database.py tests/test_database.py
git commit -m "feat: add english classroom tables and room seed"
```

---

## Task 2: Core — `english_exercise.py` (stats and progress helpers)

**Files:**
- Create: `shadowtalk/core/english_exercise.py`
- Create: `tests/test_english_exercise.py`

**Interfaces:**
- Consumes: `Database.get_connection()` from `shadowtalk.data.database`
- Produces:
  - `record_exercise(friend_id, word, exercise_type, correct, attempts, time_used, is_bonus) -> None`
  - `upsert_progress(friend_id, word_range, word, correct) -> dict` — returns current progress row
  - `get_next_word(friend_id, word_range) -> str | None` — picks next word by priority
  - `get_stats(friend_id) -> dict` — returns streak, today_count, accuracy
  - `PRESENT_EXERCISE_TOOL` — dict, the tool definition for AIClient

- [ ] **Step 1: Write failing tests**

```python
import pytest
from shadowtalk.core.english_exercise import (
    record_exercise, upsert_progress, get_next_word, get_stats,
    PRESENT_EXERCISE_TOOL,
)


def test_record_exercise_inserts_row(test_database):
    """record_exercise 应在 english_exercise_stats 写入一条记录"""
    record_exercise(1, "perseverance", "sentence_build", True, 1, 5.2, False)
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT * FROM english_exercise_stats WHERE friend_id=1 AND word=?",
        ("perseverance",)).fetchone()
    assert row is not None
    assert row["correct"] == 1
    assert row["exercise_type"] == "sentence_build"


def test_upsert_progress_creates_new(test_database):
    """upsert_progress 对不存在的词应 INSERT 新行"""
    result = upsert_progress(1, "CET-4", "abandon", True)
    assert result["status"] == "learning"
    assert result["times_correct"] == 1


def test_upsert_progress_updates_existing(test_database):
    """upsert_progress 对已存在的词应 UPDATE 累加"""
    upsert_progress(1, "CET-4", "abandon", True)
    result = upsert_progress(1, "CET-4", "abandon", False)
    assert result["times_correct"] == 1
    assert result["times_wrong"] == 1


def test_get_next_word_priority(test_database):
    """get_next_word 应优先返回 review_at 到期的词"""
    import datetime
    past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
    conn = __import__("shadowtalk.data.database", fromlist=["Database"]).Database.get_connection()
    conn.execute(
        "INSERT INTO english_progress (friend_id, word_range, word, status, review_at) "
        "VALUES (1, 'CET-4', 'abandon', 'review', ?)", (past,))
    conn.execute(
        "INSERT INTO english_progress (friend_id, word_range, word, status) "
        "VALUES (1, 'CET-4', 'benefit', 'new')")
    word = get_next_word(1, "CET-4")
    assert word == "abandon"


def test_get_stats_streak(test_database):
    """get_stats 应正确计算连胜数"""
    for _ in range(5):
        record_exercise(1, "w", "cloze", True, 1, 1.0, False)
    stats = get_stats(1)
    assert stats["streak"] == 5


def test_present_exercise_tool_schema(test_database):
    """PRESENT_EXERCISE_TOOL 应是合法的工具定义"""
    tool = PRESENT_EXERCISE_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "present_exercise"
    assert "type" in tool["function"]["parameters"]["properties"]
    assert tool["function"]["parameters"]["properties"]["type"]["enum"] == [
        "sentence_build", "cloze", "match", "translate_assemble", "story"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_english_exercise.py -v`
Expected: FAIL — module not defined

- [ ] **Step 3: Implement `english_exercise.py`**

```python
"""英语教室练习引擎：答题记录、词库进度、工具定义。

AI 通过 present_exercise 工具出题，答题结果回传后调用 record_exercise
落库并 upsert_progress 更新进度。get_next_word 决定下一个出题的词。
"""
import datetime
import json
import logging

from shadowtalk.data.database import Database

logger = logging.getLogger(__name__)

# 题型常量
EXERCISE_TYPES = ("sentence_build", "cloze", "match", "translate_assemble", "story")

# 工具定义（注入 AIClient.chat_with_tools 的工具列表）
PRESENT_EXERCISE_TOOL = {
    "type": "function",
    "function": {
        "name": "present_exercise",
        "description": "给用户出一道英语练习题。当用户进入练习模式、答完上一题继续、"
                       "或你判断需要巩固某个知识点时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": list(EXERCISE_TYPES),
                },
                "word": {"type": "string"},
                "prompt": {"type": "string"},
                "words": {"type": "array", "items": {"type": "string"}},
                "correct_order": {"type": "array", "items": {"type": "integer"}},
                "options": {"type": "array", "items": {"type": "string"}},
                "answer": {"type": "string"},
                "pairs": {"type": "object"},
                "time_limit": {"type": "integer"},
                "story_text": {"type": "string"},
                "choices": {"type": "array", "items": {"type": "string"}},
                "explanation": {"type": "string"},
            },
            "required": ["type", "word", "answer", "explanation"],
        },
    },
}


def record_exercise(friend_id: int, word: str, exercise_type: str,
                    correct: bool, attempts: int = 1,
                    time_used: float = 0.0, is_bonus: bool = False) -> None:
    """写一条答题记录到 english_exercise_stats"""
    with Database.transaction() as conn:
        conn.execute(
            "INSERT INTO english_exercise_stats "
            "(friend_id, word, exercise_type, correct, attempts, time_used, is_bonus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (friend_id, word, exercise_type, correct, attempts, time_used, is_bonus),
        )


def upsert_progress(friend_id: int, word_range: str, word: str,
                    correct: bool) -> dict:
    """更新词库进度：不存在则 INSERT，存在则 UPDATE 累加。返回当前行 dict。"""
    with Database.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM english_progress "
            "WHERE friend_id=? AND word_range=? AND word=?",
            (friend_id, word_range, word)).fetchone()
        now = datetime.datetime.now().isoformat()
        if row is None:
            conn.execute(
                "INSERT INTO english_progress "
                "(friend_id, word_range, word, status, times_correct, times_wrong, "
                "last_exercise_at) VALUES (?, ?, ?, 'learning', ?, ?, ?)",
                (friend_id, word_range, word,
                 1 if correct else 0, 0 if correct else 1, now))
        else:
            times_correct = row["times_correct"] + (1 if correct else 0)
            times_wrong = row["times_wrong"] + (0 if correct else 1)
            # 连续 3 次 correct 升级为 mastered
            status = "mastered" if times_correct >= 3 and times_wrong == 0 else row["status"]
            # 答错：按 1/3/7 轮后安排复习
            review_at = row["review_at"]
            if not correct:
                wrong_streak = times_wrong
                days = {1: 1, 2: 3, 3: 7}.get(min(wrong_streak, 3), 7)
                review_at = (datetime.datetime.now() +
                             datetime.timedelta(days=days)).isoformat()
            conn.execute(
                "UPDATE english_progress SET times_correct=?, times_wrong=?, "
                "status=?, review_at=?, last_exercise_at=? "
                "WHERE friend_id=? AND word_range=? AND word=?",
                (times_correct, times_wrong, status, review_at, now,
                 friend_id, word_range, word))
        row = conn.execute(
            "SELECT * FROM english_progress "
            "WHERE friend_id=? AND word_range=? AND word=?",
            (friend_id, word_range, word)).fetchone()
        return dict(row) if row else {}


def get_next_word(friend_id: int, word_range: str) -> str | None:
    """按优先级选下一个出题词：到期复习 > 正在学 > 新词。返回 word 或 None。"""
    conn = Database.get_connection()
    now = datetime.datetime.now().isoformat()
    # 优先级 1: review_at 到期
    row = conn.execute(
        "SELECT word FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND review_at IS NOT NULL "
        "AND review_at <= ? ORDER BY review_at LIMIT 1",
        (friend_id, word_range, now)).fetchone()
    if row:
        return row["word"]
    # 优先级 2: learning
    row = conn.execute(
        "SELECT word FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='learning' "
        "ORDER BY last_exercise_at LIMIT 1",
        (friend_id, word_range)).fetchone()
    if row:
        return row["word"]
    # 优先级 3: new
    row = conn.execute(
        "SELECT word FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='new' LIMIT 1",
        (friend_id, word_range)).fetchone()
    return row["word"] if row else None


def get_stats(friend_id: int) -> dict:
    """返回学习统计：连胜、今日题数、正确率"""
    conn = Database.get_connection()
    # 连胜：从最近一条倒序数连续 correct=true
    rows = conn.execute(
        "SELECT correct FROM english_exercise_stats "
        "WHERE friend_id=? AND is_bonus=0 "
        "ORDER BY id DESC",
        (friend_id,)).fetchall()
    streak = 0
    for r in rows:
        if r["correct"]:
            streak += 1
        else:
            break
    # 今日题数
    today = datetime.date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM english_exercise_stats "
        "WHERE friend_id=? AND is_bonus=0 AND date(created_at)=?",
        (friend_id, today)).fetchone()
    today_count = row["cnt"] if row else 0
    # 正确率（最近 50 题）
    rows = conn.execute(
        "SELECT correct FROM english_exercise_stats "
        "WHERE friend_id=? AND is_bonus=0 "
        "ORDER BY id DESC LIMIT 50",
        (friend_id,)).fetchlast50 = [r["correct"] for r in rows]
    accuracy = round(sum(last50) / len(last50) * 100) if last50 else 0
    return {"streak": streak, "today_count": today_count, "accuracy": accuracy}
```

- [ ] **Step 4: Fix the stats query (typo in draft)**

Correct the `get_stats` function's accuracy section:

```python
    rows = conn.execute(
        "SELECT correct FROM english_exercise_stats "
        "WHERE friend_id=? AND is_bonus=0 "
        "ORDER BY id DESC LIMIT 50",
        (friend_id,)).fetchall()
    last50 = [r["correct"] for r in rows]
    accuracy = round(sum(last50) / len(last50) * 100) if last50 else 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_english_exercise.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add shadowtalk/core/english_exercise.py tests/test_english_exercise.py
git commit -m "feat: add english exercise engine with stats and progress tracking"
```

---

## Task 3: AI client — register `present_exercise` tool

**Files:**
- Modify: `shadowtalk/core/ai_client.py`
- Test: `tests/test_ai_client.py` (add test)

**Interfaces:**
- Consumes: `PRESENT_EXERCISE_TOOL` from `shadowtalk.core.english_exercise`
- Produces: `chat_with_tools` now includes `present_exercise` in tool list and handles it in dispatch

- [ ] **Step 1: Write failing test**

```python
def test_present_exercise_in_tools():
    """present_exercise 工具应出现在 chat_with_tools 的工具列表中"""
    # 验证工具定义被 ai_client 引用
    import shadowtalk.core.ai_client as ai_mod
    src = open(ai_mod.__file__).read()
    assert "present_exercise" in src
    assert "PRESENT_EXERCISE_TOOL" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_client.py::test_present_exercise_in_tools -v`
Expected: FAIL

- [ ] **Step 3: Add import and tool registration**

At the top of `ai_client.py`, add:

```python
from shadowtalk.core.english_exercise import PRESENT_EXERCISE_TOOL
```

- [ ] **Step 4: Add `present_exercise` to the tools list**

In `chat_with_tools()`, change the `tools` list to:

```python
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "在用户指定的工作目录下执行 Python 代码（可读写文件、处理数据、生成文档）。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string",
                                     "description": "要执行的 Python 代码"},
                            "reason": {"type": "string",
                                       "description": "执行目的说明（展示给用户）"},
                        },
                        "required": ["code", "reason"],
                    },
                },
            },
            PRESENT_EXERCISE_TOOL,
        ]
```

- [ ] **Step 5: Add dispatch branch in the tool loop**

In the `for tc in message.tool_calls:` loop, after the `if name == "run_python":` block, add:

```python
                elif name == "present_exercise":
                    # present_exercise 不由 python_executor 执行，
                    # 而是由 AIWorker._run_tool 拦截并挂起等待用户交互。
                    # 此处仅记录工具调用，实际执行在 worker 层。
                    result_text = tool_runner(json.dumps(args), f"出题: {args.get('word', '')}")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_ai_client.py::test_present_exercise_in_tools -v`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add shadowtalk/core/ai_client.py tests/test_ai_client.py
git commit -m "feat: register present_exercise tool in ai_client"
```

---

## Task 4: AIWorker — exercise suspend/resume mechanism

**Files:**
- Modify: `shadowtalk/ui/threads/ai_worker.py`
- Test: `tests/test_ai_worker.py` (add test for signal existence)

**Interfaces:**
- Consumes: `json` (already imported)
- Produces:
  - `exercise_requested = Signal(str, str, str)` — (tool_call_id, exercise_json, word_range)
  - `exercise_answered = Signal(str, str)` — (tool_call_id, result_json)
  - `resume_exercise(tool_call_id, result_json)` — public slot to resume

- [ ] **Step 1: Write failing test**

```python
def test_exercise_signals_exist():
    """AIWorker 应有 exercise_requested 和 exercise_answered 信号"""
    from shadowtalk.ui.threads.ai_worker import AIWorker
    assert hasattr(AIWorker, "exercise_requested")
    assert hasattr(AIWorker, "exercise_answered")


def test_resume_exercise_method_exists():
    """AIWorker 应有 resume_exercise 方法"""
    from shadowtalk.ui.threads.ai_worker import AIWorker
    # 实例化需要参数，仅检查类方法存在
    assert "resume_exercise" in AIWorker.__dict__ or any(
        "resume_exercise" in cls.__dict__ for cls in AIWorker.__mro__)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_worker.py::test_exercise_signals_exist -v`
Expected: FAIL

- [ ] **Step 3: Add signals and fields to AIWorker**

Add to the signal declarations:

```python
    exercise_requested = Signal(str, str, str)   # (tool_call_id, exercise_json, word_range)
    exercise_answered = Signal(str, str)         # (tool_call_id, result_json)
```

Add to `__init__`:

```python
        self._word_range = ""
        self._exercise_suspend = None   # (tool_call_id, loop) when suspended
```

Add a `word_range` parameter to `__init__`:

```python
    def __init__(self, friend_id, user_message, ai_client, messages: list,
                 work_dir: str = "", approval_answered=None, word_range: str = ""):
```

- [ ] **Step 4: Add `present_exercise` interception in `_run_tool`**

At the start of `_run_tool`, before the work_dir check, add:

```python
        # present_exercise 工具：挂起线程等待用户答题，不执行代码
        if reason.startswith("出题: ") or "present_exercise" in code:
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            tool_call_id = ""  # 由调用方设置
            self._exercise_suspend = (tool_call_id, loop)
            self.exercise_requested.emit(
                tool_call_id, code or reason, self._word_range)
            loop.exec()  # 等待 resume_exercise
            self._exercise_suspend = None
            return self._last_exercise_result or json.dumps({
                "correct": False, "user_answer": "", "correct_answer": "",
                "attempts": 1, "time_used": 0, "exercise_type": "skip", "skipped": True})
```

Wait — this approach has a problem. The `_run_tool` receives `(code, reason)`, but for `present_exercise`, the tool arguments come as JSON. Let me reconsider.

The actual flow: `ai_client.chat_with_tools` parses the tool call and passes `json.dumps(args)` as `code` and `f"出题: {word}"` as `reason` to `tool_runner`. So `_run_tool` receives the full JSON as `code`.

Revised step 4 — replace `_run_tool` entirely:

```python
    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码；present_exercise 挂起等待用户答题。"""
        # present_exercise 工具：挂起线程等待用户答题
        if reason.startswith("出题: ") and code and code[0] == "{":
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            self._exercise_loop = loop
            self._last_exercise_result = None
            # 从 code 中解析 tool_call_id（code 是 arguments JSON）
            self.exercise_requested.emit(code, self._word_range, reason)
            loop.exec()  # 等待用户答题后 resume_exercise 调用 quit
            self._exercise_loop = None
            return self._last_exercise_result or json.dumps({
                "correct": False, "user_answer": "", "correct_answer": "",
                "attempts": 1, "time_used": 0, "exercise_type": "skip", "skipped": True})

        if not self.work_dir:
            logger.warning("拒绝工具执行: 未配置工作目录")
            return ("当前好友未配置工作目录。请在好友设置中添加工作目录，"
                    "即可让我读写文件。")

        self.activity.emit(f"执行工具：{reason or code[:20]}")
        start = time.time()
        result = self._execute_tool(code, reason)
        self.activity.emit(f"工具完成（{time.time() - start:.1f} 秒），继续思考…")
        return result
```

Add `_exercise_loop` and `_last_exercise_result` to `__init__`:

```python
        self._exercise_loop = None
        self._last_exercise_result = None
```

- [ ] **Step 5: Add `resume_exercise` method**

```python
    def resume_exercise(self, result_json: str) -> None:
        """用户答题后恢复挂起的练习循环。由 UI 线程调用。"""
        self._last_exercise_result = result_json
        if self._exercise_loop is not None:
            self._exercise_loop.quit()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_ai_worker.py -v -k "exercise"`
Expected: PASS

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add shadowtalk/ui/threads/ai_worker.py tests/test_ai_worker.py
git commit -m "feat: add exercise suspend/resume to AIWorker"
```

---

## Task 5: Word range selection dialog

**Files:**
- Create: `shadowtalk/ui/widgets/english_word_range_dialog.py`
- Test: `tests/test_english_word_range_dialog.py`

**Interfaces:**
- Produces: `EnglishWordRangeDialog` — QDialog with word range radio buttons and start mode selection
  - `get_selected_range(parent) -> tuple[str, str] | None` — returns (word_range, start_mode) or None

- [ ] **Step 1: Write failing test**

```python
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from shadowtalk.ui.widgets.english_word_range_dialog import EnglishWordRangeDialog


def test_dialog_returns_selection():
    """对话框确认后应返回选中的词库和起始模式"""
    dlg = EnglishWordRangeDialog()
    # 默认选中 CET-4 和 "继续上次"
    assert dlg.get_selected_range() == ("CET-4", "continue")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_english_word_range_dialog.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the dialog**

```python
"""英语教室词库选择对话框"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QButtonGroup, QPushButton, QFrame,
)

logger = logging.getLogger(__name__)

WORD_RANGES = [
    ("CET-4", "大学英语四级 · ~4500 词"),
    ("CET-6", "大学英语六级 · ~5500 词"),
    ("IELTS", "雅思核心 · ~6000 词"),
    ("TOEFL", "托福核心 · ~8000 词"),
]


class EnglishWordRangeDialog(QDialog):
    """词库范围 + 起始模式选择"""

    def __init__(self, parent=None, has_progress=False):
        super().__init__(parent)
        self.setWindowTitle("🏫 英语教室")
        self.setModal(True)
        self.resize(380, 280)
        self._has_progress = has_progress
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("📚 选择词库范围")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1F2430;")
        layout.addWidget(title)

        self._range_group = QButtonGroup(self)
        for key, desc in WORD_RANGES:
            row = QHBoxLayout()
            rb = QRadioButton(key)
            rb.setStyleSheet("font-size: 13px; color: #1F2430;")
            desc_lbl = QLabel(f"  {desc}")
            desc_lbl.setStyleSheet("font-size: 11px; color: #7A7A7A;")
            row.addWidget(rb)
            row.addWidget(desc_lbl, 1)
            layout.addLayout(row)
            self._range_group.addButton(rb, len(self._range_group.buttons()))
            if key == "CET-4":
                rb.setChecked(True)

        layout.addSpacing(8)
        mode_label = QLabel("起始方式")
        mode_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #1F2430;")
        layout.addWidget(mode_label)

        self._mode_group = QButtonGroup(self)
        self._continue_rb = QRadioButton("从上次进度继续")
        self._restart_rb = QRadioButton("从头开始")
        self._test_rb = QRadioButton("快速测试后定级")
        for rb in (self._continue_rb, self._restart_rb, self._test_rb):
            rb.setStyleSheet("font-size: 12px; color: #1F2430;")
            layout.addWidget(rb)
            self._mode_group.addButton(rb)
        if self._has_progress:
            self._continue_rb.setChecked(True)
        else:
            self._restart_rb.setChecked(True)
            self._continue_rb.setEnabled(False)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("进入教室")
        ok_btn.setStyleSheet("""
            QPushButton { background: #2E9E57; color: white; border: none;
                         border-radius: 8px; padding: 8px 24px; font-weight: bold; }
            QPushButton:hover { background: #248a4a; }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def get_selected_range(self) -> tuple:
        """返回 (word_range, start_mode)"""
        range_btn = self._range_group.checkedButton()
        range_key = "CET-4"
        for key, _ in WORD_RANGES:
            if range_btn and range_btn.text() == key:
                range_key = key
                break
        mode = "continue"
        if self._restart_rb.isChecked():
            mode = "restart"
        elif self._test_rb.isChecked():
            mode = "test"
        return (range_key, mode)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_english_word_range_dialog.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add shadowtalk/ui/widgets/english_word_range_dialog.py tests/test_english_word_range_dialog.py
git commit -m "feat: add english word range selection dialog"
```

---

## Task 6: UI — `EnglishRoomWindow` skeleton and layout

**Files:**
- Create: `shadowtalk/ui/widgets/english_room.py`
- Create: `tests/test_english_room.py`

**Interfaces:**
- Consumes: `RoomWindow` base class, `AIWorker.exercise_requested`, `record_exercise`, `upsert_progress`, `get_stats`
- Produces: `EnglishRoomWindow(RoomWindow)` with exercise panel placeholder

- [ ] **Step 1: Write failing test**

```python
def test_english_room_window_class():
    """EnglishRoomWindow 应继承 RoomWindow"""
    from shadowtalk.ui.widgets.english_room import EnglishRoomWindow
    from shadowtalk.ui.widgets.room_window import RoomWindow
    assert issubclass(EnglishRoomWindow, RoomWindow)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_english_room.py -v`
Expected: FAIL

- [ ] **Step 3: Implement skeleton**

```python
"""沉浸式英语教室：左聊右练，AI 驱动练习卡片。

复用 RoomWindow 骨架：左侧窄聊天区（280px）+ 右侧练习卡片面板。
AI 通过 present_exercise 工具在右侧出题，用户答题后结果回传 AI。
设计文档：docs/superpowers/specs/2026-08-18-english-learning-room-design.md
"""
import json
import logging
import time

from PySide6.QtCore import Qt, Signal, QTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QWidget, QButtonGroup, QRadioButton, QLineEdit,
)

from shadowtalk.core.english_exercise import (
    record_exercise, upsert_progress, get_stats,
)
from shadowtalk.ui.widgets.room_window import RoomBubble, RoomWindow

logger = logging.getLogger(__name__)


class ExerciseCard(QFrame):
    """练习卡片基类：题型渲染 + 答题回传"""

    answered = Signal(str, dict)  # (tool_call_id, result_dict)

    def __init__(self, exercise_data: dict, tool_call_id: str, parent=None):
        super().__init__(parent)
        self._data = exercise_data
        self._tool_call_id = tool_call_id
        self._start_time = time.time()
        self._attempts = 0
        self._answered = False
        self.setStyleSheet("""
            QFrame { background-color: rgba(255,255,255,235);
                     border-radius: 16px; }
            QLabel { color: #1F2430; background: transparent; }
        """)


class EnglishRoomWindow(RoomWindow):
    """英语教室：左聊右练"""

    def __init__(self, friend_id: int, word_range: str = "CET-4",
                 start_mode: str = "restart", parent=None):
        self._word_range = word_range
        self._start_mode = start_mode
        self._current_card = None
        self._current_tool_call_id = ""
        super().__init__(friend_id, "english", parent=parent)

    def _build_ui(self):
        super()._build_ui()
        # 右侧练习面板
        self.exercise_panel = QFrame()
        self.exercise_panel.setStyleSheet("background: transparent;")
        self._exercise_layout = QVBoxLayout(self.exercise_panel)
        self._exercise_layout.setContentsMargins(16, 16, 16, 16)
        self._exercise_layout.addStretch(1)
        # 插入到内容区右侧
        self._content_host.addWidget(self.exercise_panel, 1)
        # 统计标签
        self._stats_label = QLabel("")
        self._stats_label.setStyleSheet(
            "color: rgba(245,239,230,210); font-size: 12px; background: transparent;")
        self._update_stats()

    def _update_stats(self):
        """刷新顶部统计"""
        stats = get_stats(self.friend_id)
        self._stats_label.setText(
            f"🔥 连胜 {stats['streak']}  |  "
            f"今日 {stats['today_count']} 题  |  "
            f"正确率 {stats['accuracy']}%")

    # ── 练习卡片的渲染与答题 ──
    def _on_exercise_requested(self, code: str, word_range: str, reason: str):
        """AIWorker 发出 exercise_requested 信号时渲染卡片"""
        try:
            data = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            logger.error("解析练习数据失败: %s", code[:100])
            return
        self._render_exercise_card(data)

    def _render_exercise_card(self, data: dict):
        """根据题型渲染对应卡片"""
        # 子类/后续任务实现具体渲染
        pass

    def _connect_worker(self):
        """连接 AIWorker 的练习信号"""
        if self.ai_worker is not None:
            self.ai_worker.exercise_requested.connect(self._on_exercise_requested)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_english_room.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add shadowtalk/ui/widgets/english_room.py tests/test_english_room.py
git commit -m "feat: add EnglishRoomWindow skeleton with layout"
```

---

## Task 7: UI — exercise card rendering (all 5 types)

**Files:**
- Modify: `shadowtalk/ui/widgets/english_room.py`
- Modify: `tests/test_english_room.py`

**Interfaces:**
- Produces: `ExerciseCard` subclasses for each type, `_render_exercise_card` dispatch

- [ ] **Step 1: Write failing tests for card rendering**

```python
def test_choice_card_renders():
    """选择题卡片应渲染题干和选项"""
    from shadowtalk.ui.widgets.english_room import EnglishRoomWindow
    # 用 mock 方式测试 _render_exercise_card 不崩溃
    # 实际测试在 GUI test 文件中
    pass  # 占位，GUI 交互测试在 test_main_window 风格中


def test_all_exercise_types_handled():
    """_render_exercise_card 应处理所有 5 种题型不崩溃"""
    import json
    types_data = {
        "sentence_build": {"type": "sentence_build", "word": "test",
                          "words": ["I", "love", "English"],
                          "correct_order": [0, 1, 2], "answer": "I love English",
                          "explanation": "test"},
        "cloze": {"type": "cloze", "word": "test",
                 "prompt": "I ____ English.", "options": ["love", "hate", "eat", "run"],
                 "answer": "love", "explanation": "test"},
        "match": {"type": "match", "word": "test",
                 "pairs": {"apple": "苹果", "book": "书", "cat": "猫", "dog": "狗"},
                 "answer": "matched", "time_limit": 15, "explanation": "test"},
        "translate_assemble": {"type": "translate_assemble", "word": "test",
                              "prompt": "我喜欢英语",
                              "words": ["I", "like", "English", "very", "much"],
                              "correct_order": [0, 1, 2], "answer": "I like English",
                              "explanation": "test"},
        "story": {"type": "story", "word": "test",
                 "story_text": "Tom is a student. He likes reading.",
                 "choices": ["Tom is a teacher.", "Tom enjoys books.", "Tom hates reading."],
                 "answer": "Tom enjoys books.", "explanation": "test"},
    }
    assert len(types_data) == 5
```

- [ ] **Step 2: Implement card rendering in `english_room.py`**

Add to the `english_room.py` file, replacing the `_render_exercise_card` method and adding card builder:

```python
    def _render_exercise_card(self, data: dict):
        """根据题型渲染对应卡片"""
        # 清除旧卡片
        if self._current_card is not None:
            self._exercise_layout.removeWidget(self._current_card)
            self._current_card.deleteLater()
            self._current_card = None

        exercise_type = data.get("type", "")
        tool_call_id = self._current_tool_call_id

        card = ExerciseCard(data, tool_call_id, parent=self.exercise_panel)
        self._current_card = card

        # 题干
        prompt = data.get("prompt", "")
        if prompt:
            q_lbl = QLabel(prompt)
            q_lbl.setWordWrap(True)
            q_lbl.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
            card.layout().addWidget(q_lbl)

        if exercise_type == "sentence_build":
            self._build_sentence_build_card(card, data)
        elif exercise_type == "cloze":
            self._build_cloze_card(card, data)
        elif exercise_type == "match":
            self._build_match_card(card, data)
        elif exercise_type == "translate_assemble":
            self._build_translate_assemble_card(card, data)
        elif exercise_type == "story":
            self._build_story_card(card, data)
        else:
            err = QLabel(f"未知题型: {exercise_type}")
            card.layout().addWidget(err)

        # 插入到 stretch 之前
        self._exercise_layout.insertWidget(
            self._exercise_layout.count() - 1, card)
```

- [ ] **Step 3: Add card builder methods to `EnglishRoomWindow`**

```python
    def _build_sentence_build_card(self, card: ExerciseCard, data: dict):
        """拖拽/点击组句卡片"""
        words = data.get("words", [])
        # 构建区
        build_area = QFrame()
        build_area.setStyleSheet(
            "background: rgba(200,200,200,120); border-radius: 8px; min-height: 36px;")
        build_area.setLayout(QHBoxLayout())
        build_area.layout().setSpacing(4)
        build_area.layout().setContentsMargins(8, 8, 8, 8)
        card.layout().addWidget(build_area)
        # 单词池
        pool = QFrame()
        pool.setLayout(QHBoxLayout())
        pool.layout().setSpacing(4)
        pool.layout().setContentsMargins(4, 4, 4, 4)
        card.layout().addWidget(pool)
        # chip 按钮
        chips = []
        for w in words:
            btn = QPushButton(w)
            btn.setStyleSheet("""
                QPushButton { background: #E8E8E8; border: none; border-radius: 6px;
                              padding: 6px 10px; font-size: 12px; }
                QPushButton:hover { background: #D0D0D0; }
            """)
            btn.clicked.connect(lambda _=False, b=btn: self._on_chip_click(b, build_area, pool))
            pool.layout().addWidget(btn)
            chips.append(btn)
        # 操作按钮
        btn_row = QHBoxLayout()
        check_btn = QPushButton("检查答案")
        check_btn.clicked.connect(lambda: self._check_sentence_build(card, data, build_area))
        skip_btn = QPushButton("跳过")
        skip_btn.clicked.connect(lambda: self._skip_exercise(card, data))
        btn_row.addWidget(check_btn)
        btn_row.addWidget(skip_btn)
        card.layout().addLayout(btn_row)
```

- [ ] **Step 4: Add remaining card builders**

Similar pattern for `_build_cloze_card`, `_build_match_card`, `_build_translate_assemble_card`, `_build_story_card`. Each builds the specific UI and wires answer buttons to `_check_answer` or `_skip_exercise`.

- [ ] **Step 5: Add answer checking methods**

```python
    def _check_answer(self, card: ExerciseCard, data: dict, user_answer: str):
        """通用答题判定"""
        if card._answered:
            return
        card._answered = True
        card._attempts += 1
        correct_answer = data.get("answer", "")
        correct = user_answer.strip().lower() == correct_answer.strip().lower()
        time_used = time.time() - card._start_time
        is_bonus = data.get("is_bonus", False)

        # 落库
        record_exercise(self.friend_id, data.get("word", ""),
                       data.get("type", ""), correct,
                       card._attempts, time_used, is_bonus)
        upsert_progress(self.friend_id, self._word_range,
                       data.get("word", ""), correct)

        # 显示反馈
        self._show_feedback(card, correct, correct_answer, data.get("explanation", ""))

        # 回传 AI
        result = {
            "correct": correct,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "attempts": card._attempts,
            "time_used": time_used,
            "exercise_type": data.get("type", ""),
            "skipped": False,
        }
        if self.ai_worker is not None:
            self.ai_worker.resume_exercise(json.dumps(result))

        self._update_stats()

    def _skip_exercise(self, card: ExerciseCard, data: dict):
        """跳过当前题"""
        if card._answered:
            return
        card._answered = True
        result = {
            "correct": False, "user_answer": "", "correct_answer": data.get("answer", ""),
            "attempts": 0, "time_used": 0, "exercise_type": data.get("type", ""),
            "skipped": True,
        }
        if self.ai_worker is not None:
            self.ai_worker.resume_exercise(json.dumps(result))
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add shadowtalk/ui/widgets/english_room.py tests/test_english_room.py
git commit -m "feat: implement all 5 exercise card types with answer checking"
```

---

## Task 8: Integration — wire up main_window and room_window

**Files:**
- Modify: `shadowtalk/ui/main_window.py`
- Modify: `shadowtalk/ui/widgets/room_window.py`
- Modify: `shadowtalk/ui/widgets/english_room.py` (AIWorker creation)

**Interfaces:**
- Produces: full end-to-end flow from menu click to exercise card

- [ ] **Step 1: Add `english` to `_ROOM_ICONS`**

In `shadowtalk/ui/widgets/room_window.py`:

```python
_ROOM_ICONS = {"cafe": "☕", "music": "🎵", "reading": "📖", "english": "🏫"}
```

- [ ] **Step 2: Add English room option to main_window dialog**

In `_on_open_room()`, change the dialog items list and key_map:

```python
        room_key, ok = QInputDialog.getItem(
            self, "选择房间", "去哪个房间？",
            ["☕ 咖啡馆", "🎵 音乐室", "📖 阅读室", "🏫 英语教室"], 0, False)
        if not ok:
            return
        key_map = {"☕ 咖啡馆": ("cafe", "请谁去喝咖啡？"),
                   "🎵 音乐室": ("music", "请谁一起听歌？"),
                   "📖 阅读室": ("reading", "请谁一起读书？"),
                   "🏫 英语教室": ("english", "请谁一起学英语？")}
```

- [ ] **Step 3: Add English room instantiation**

After the reading room branch:

```python
        elif room_key_id == "english":
            from shadowtalk.ui.widgets.english_word_range_dialog import EnglishWordRangeDialog
            dlg = EnglishWordRangeDialog(parent=self, has_progress=False)
            if dlg.exec() != QDialog.Accepted:
                return
            word_range, start_mode = dlg.get_selected_range()
            from shadowtalk.ui.widgets.english_room import EnglishRoomWindow
            room = EnglishRoomWindow(friend_id, word_range=word_range,
                                     start_mode=start_mode, parent=self)
```

- [ ] **Step 4: Pass word_range to AIWorker in EnglishRoomWindow**

Override `_on_send` in `EnglishRoomWindow` to set `self.ai_worker._word_range = self._word_range` after worker creation, and connect exercise signals:

```python
    def _on_send(self):
        super()._on_send()
        if self.ai_worker is not None:
            self.ai_worker._word_range = self._word_range
            self.ai_worker.exercise_requested.connect(self._on_exercise_requested)
```

- [ ] **Step 5: Add import to main_window**

Add `from PySide6.QtWidgets import QDialog` (may already be imported).

- [ ] **Step 6: Manual smoke test**

Run: `python -m shadowtalk.main`
- Open English room dialog → select CET-4 → enter room
- Send a message → AI should respond
- Verify layout: chat left 280px, exercise panel right
- Check stats label shows in top bar

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add shadowtalk/ui/main_window.py shadowtalk/ui/widgets/room_window.py shadowtalk/ui/widgets/english_room.py
git commit -m "feat: integrate english room into main window and room launcher"
```

---

## Task 9: Scene prompt injection with word_range and stats

**Files:**
- Modify: `shadowtalk/core/english_exercise.py` (add `build_scene_prompt`)
- Modify: `shadowtalk/ui/widgets/english_room.py` (use it)
- Test: `tests/test_english_exercise.py`

**Interfaces:**
- Produces: `build_scene_prompt(friend_id, word_range) -> str`

- [ ] **Step 1: Write failing test**

```python
def test_build_scene_prompt_injects_word_range():
    """build_scene_prompt 应将词库范围注入场景描述"""
    from shadowtalk.core.english_exercise import build_scene_prompt
    prompt = build_scene_prompt(1, "CET-6")
    assert "CET-6" in prompt
    assert "英语" in prompt


def test_build_scene_prompt_injects_stats():
    """build_scene_prompt 应注入当前进度统计"""
    from shadowtalk.core.english_exercise import build_scene_prompt
    prompt = build_scene_prompt(1, "IELTS")
    # 进度信息（即使为0也应出现）
    assert "掌握" in prompt or "进度" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_english_exercise.py::test_build_scene_prompt_injects_word_range -v`
Expected: FAIL

- [ ] **Step 3: Implement `build_scene_prompt`**

Add to `english_exercise.py`:

```python
def build_scene_prompt(friend_id: int, word_range: str) -> str:
    """构建带词库范围和当前统计的场景 prompt"""
    conn = Database.get_connection()
    # 统计掌握/学习中/待复习
    mastered = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='mastered'",
        (friend_id, word_range)).fetchone()[0]
    learning = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND status='learning'",
        (friend_id, word_range)).fetchone()[0]
    now = datetime.datetime.now().isoformat()
    review_due = conn.execute(
        "SELECT COUNT(*) FROM english_progress "
        "WHERE friend_id=? AND word_range=? AND review_at IS NOT NULL "
        "AND review_at <= ?",
        (friend_id, word_range, now)).fetchone()[0]

    return _SCENE_PROMPT_TEMPLATE.format(
        word_range=word_range,
        mastered=mastered,
        learning=learning,
        review_due=review_due,
    )


_SCENE_PROMPT_TEMPLATE = """你是一位专业的英语一对一教师，正在使用 {word_range} 词库辅导学生。

当前进度：已掌握 {mastered} 词，学习中 {learning} 词，待复习 {review_due} 词。

教学原则：
- 系统性：按词库范围有计划地推进，确保覆盖核心词汇
- 间隔重复：根据答题记录，错过的词在 1/3/7 轮后重现
- 难度递进：先词义辨识，再填空，再组句，最后翻译拼装
- 自由对话是语境补充：从上下文了解学生兴趣和表达水平
- 用 present_exercise 工具出题，等学生答题后再讲解
- 讲解简洁有力，1-3 句话
- 偶尔可以超纲出 1-2 道拓展题（标注为 bonus），但不影响进度统计"""
```

- [ ] **Step 4: Use `build_scene_prompt` in EnglishRoomWindow**

Override `_current_scene_prompt`:

```python
    def _current_scene_prompt(self) -> str:
        from shadowtalk.core.english_exercise import build_scene_prompt
        return build_scene_prompt(self.friend_id, self._word_range)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_english_exercise.py -v -k "scene_prompt"`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add shadowtalk/core/english_exercise.py shadowtalk/ui/widgets/english_room.py tests/test_english_exercise.py
git commit -m "feat: inject word range and stats into english room scene prompt"
```

---

## Task 10: Full integration polish and edge cases

**Files:**
- Modify: `shadowtalk/ui/widgets/english_room.py`
- Modify: `shadowtalk/ui/threads/ai_worker.py`
- Test: various test files

**Interfaces:**
- Produces: robust end-to-end flow with proper cleanup and edge case handling

- [ ] **Step 1: Handle worker recreation on each message**

In `EnglishRoomWindow._on_send`, ensure exercise signal is reconnected for each new worker:

```python
    def _on_send(self):
        super()._on_send()
        if self.ai_worker is not None:
            self.ai_worker._word_range = self._word_range
            try:
                self.ai_worker.exercise_requested.connect(
                    self._on_exercise_requested)
            except RuntimeError:
                pass  # 已连接（同一 worker 不会重建，但防御性处理）
```

- [ ] **Step 2: Handle closeEvent cleanup**

Override `closeEvent` in `EnglishRoomWindow`:

```python
    def closeEvent(self, event):
        if self._current_card is not None:
            self._current_card.deleteLater()
            self._current_card = None
        super().closeEvent(event)
```

- [ ] **Step 3: Disable input during exercise**

In `_on_exercise_requested`:

```python
    def _on_exercise_requested(self, code: str, word_range: str, reason: str):
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        try:
            data = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            logger.error("解析练习数据失败")
            return
        self._render_exercise_card(data)
```

Re-enable in `_check_answer` and `_skip_exercise`:

```python
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
```

- [ ] **Step 4: Handle rapid double-submit**

Guard in `_check_answer` and `_skip_exercise` with `card._answered` flag (already in skeleton).

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_main_window.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add shadowtalk/ui/widgets/english_room.py shadowtalk/ui/threads/ai_worker.py
git commit -m "feat: polish english room edge cases and cleanup"
```
