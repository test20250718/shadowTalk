# Task 1 Report: Database — new tables and room seed

## What I implemented

### `shadowtalk/data/database.py`

1. **Added `_ENGLISH_SCENE_PROMPT` constant** (after `_READING_SCENE_PROMPT`):
   - A Chinese-language system prompt for a one-on-one English teacher persona.
   - Covers teaching principles: systematic progress by word list, spaced repetition, progressive difficulty (recognition → fill-in → sentence → translation), free conversation as context supplement, using `present_exercise` tool, concise 1-3 sentence explanations, and occasional bonus questions.

2. **Added two tables to `SCHEMA`** (after `reading_progress`):
   - `english_exercise_stats` — per-attempt exercise log: word, exercise_type, correct, attempts, time_used, is_bonus, timestamp. FK to friends with CASCADE.
   - `english_progress` — per-word learning state: word_range, word, status, review_at, times_correct/wrong, last_exercise_at. UNIQUE(friend_id, word_range, word). FK to friends with CASCADE.

3. **Added room seed + migration to `_migrate()`** (after the reading room seed block):
   - `INSERT OR IGNORE` then `UPDATE` for key `english`, name `英语教室`, matching the existing pattern for cafe/music/reading rooms.

## What I tested (TDD RED/GREEN)

### RED phase — tests fail before implementation
- `test_english_tables_exist` → FAILED (`IndexError: tuple index out of range`)
- `test_english_room_seeded` → FAILED (`assert None is not None`)

Note: The task-brief test code had a bug — `SELECT name FROM sqlite_master` returns a single-column row, so `row[1]` raises `IndexError`. Fixed to `row[0]` so the test verifies the intended behavior (table existence). This was necessary to reach a meaningful RED state; the original would have failed regardless of implementation.

### GREEN phase — tests pass after implementation
- `test_english_tables_exist` → PASSED
- `test_english_room_seeded` → PASSED

### Full suite verification
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → **280 passed** in 66s

## Files changed

| File | Change |
|------|--------|
| `shadowtalk/data/database.py` | +`_ENGLISH_SCENE_PROMPT` constant, +2 tables in SCHEMA, +english room seed in `_migrate()` |
| `tests/test_database.py` | +`test_english_tables_exist`, `test_english_room_seeded` |

## Self-review findings

- **Spec coverage**: Fully implemented — both tables, the constant, and the seed block match the brief exactly.
- **Edge cases**:
  - `UNIQUE(friend_id, word_range, word)` on `english_progress` prevents duplicate word entries per friend/range — important for upsert logic in later tasks.
  - `ON DELETE CASCADE` on both FKs keeps stats/progress clean when a friend is deleted.
  - The `INSERT OR IGNORE` + `UPDATE` pattern follows the existing convention (scene prompts refresh on every migration; only missing rows are inserted).
- **Code cleanliness**: Follows existing style (Chinese comments, English identifiers, 4-space indent, no formatter). The constant is placed logically after the other scene prompts.
- **Tests verify behavior**: `test_english_tables_exist` confirms schema migration creates the tables; `test_english_room_seeded` confirms the room row exists with the correct Chinese name.
- **One deviation**: Fixed `row[1]` → `row[0]` in the table-existence test because the brief's version had an off-by-one against a single-column query. The test still verifies the exact same intent.

## Issues or concerns

- None blocking. The `english_exercise_stats` table has no index beyond the implicit FK; if later tasks query it heavily by `friend_id` + `created_at`, a composite index may be worth adding (not needed for this task).
- The `status` column in `english_progress` is TEXT with no CHECK constraint — valid values (e.g., "new"/"learning"/"review"/"mastered") will be enforced at the application layer in later tasks.
