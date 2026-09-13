# Task 2: Core — english_exercise.py (stats and progress helpers)

**Files to create:**
- `shadowtalk/core/english_exercise.py`
- `tests/test_english_exercise.py`

**What to do:**

Create `shadowtalk/core/english_exercise.py` with these functions and constants:

1. **`PRESENT_EXERCISE_TOOL`** — dict, the OpenAI-format tool definition for `present_exercise`:
```python
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
                    "enum": ["sentence_build", "cloze", "match", "translate_assemble", "story"],
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
```

2. **`record_exercise(friend_id, word, exercise_type, correct, attempts=1, time_used=0.0, is_bonus=False)`** — INSERT a row into `english_exercise_stats`.

3. **`upsert_progress(friend_id, word_range, word, correct)`** — INSERT or UPDATE `english_progress`. Returns current row as dict. Logic:
   - Not exists → INSERT with status='learning', times_correct/times_wrong based on correct
   - Exists → UPDATE: increment times_correct or times_wrong; if times_correct >= 3 and times_wrong == 0 → status='mastered'; if wrong → set review_at based on wrong streak (1→1 day, 2→3 days, 3+→7 days from now)

4. **`get_next_word(friend_id, word_range)`** — returns word string or None. Priority: review_at <= now → status='learning' → status='new'.

5. **`get_stats(friend_id)`** — returns dict with streak, today_count, accuracy:
   - streak: count consecutive correct=true from most recent (is_bonus=0 only)
   - today_count: count where date(created_at) = today and is_bonus=0
   - accuracy: percentage correct from last 50 non-bonus rows

**Module-level constants:**
- `EXERCISE_TYPES = ("sentence_build", "cloze", "match", "translate_assemble", "story")`
- Use `Database.get_connection()` and `Database.transaction()` from `shadowtalk.data.database`
- Import `datetime` and `json` as needed
- Chinese comments, English identifiers, 4-space indent

**Tests for `tests/test_english_exercise.py`:**

```python
import datetime
import pytest
from shadowtalk.core.english_exercise import (
    record_exercise, upsert_progress, get_next_word, get_stats,
    PRESENT_EXERCISE_TOOL,
)


def test_record_exercise_inserts_row(test_database):
    record_exercise(1, "perseverance", "sentence_build", True, 1, 5.2, False)
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT * FROM english_exercise_stats WHERE friend_id=1 AND word=?",
        ("perseverance",)).fetchone()
    assert row is not None
    assert row["correct"] == 1


def test_upsert_progress_creates_new(test_database):
    result = upsert_progress(1, "CET-4", "abandon", True)
    assert result["status"] == "learning"
    assert result["times_correct"] == 1


def test_upsert_progress_updates_existing(test_database):
    upsert_progress(1, "CET-4", "abandon", True)
    result = upsert_progress(1, "CET-4", "abandon", False)
    assert result["times_correct"] == 1
    assert result["times_wrong"] == 1


def test_get_next_word_priority(test_database):
    past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
    from shadowtalk.data.database import Database
    conn = Database.get_connection()
    conn.execute(
        "INSERT INTO english_progress (friend_id, word_range, word, status, review_at) "
        "VALUES (1, 'CET-4', 'abandon', 'review', ?)", (past,))
    conn.execute(
        "INSERT INTO english_progress (friend_id, word_range, word, status) "
        "VALUES (1, 'CET-4', 'benefit', 'new')")
    word = get_next_word(1, "CET-4")
    assert word == "abandon"


def test_get_stats_streak(test_database):
    for _ in range(5):
        record_exercise(1, "w", "cloze", True, 1, 1.0, False)
    stats = get_stats(1)
    assert stats["streak"] == 5


def test_present_exercise_tool_schema(test_database):
    tool = PRESENT_EXERCISE_TOOL
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "present_exercise"
    assert "type" in tool["function"]["parameters"]["properties"]
```

**Verification:**
- `pytest tests/test_english_exercise.py -v` → all pass
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: add english exercise engine with stats and progress tracking`

**Note:** The `test_database` fixture is already available from `tests/conftest.py` — it provides an isolated temp DB per test.
