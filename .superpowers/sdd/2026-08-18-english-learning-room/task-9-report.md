# Task 9 Report: Scene prompt injection with word_range and stats

## Status: PASS

## TDD Evidence

### Red phase (tests fail before implementation)
```
ERROR collecting tests/test_english_exercise.py
E   ImportError: cannot import name 'build_scene_prompt' from 'shadowtalk.core.english_exercise'
```

### Green phase (tests pass after implementation)
```
tests/test_english_exercise.py::test_build_scene_prompt_injects_word_range PASSED
tests/test_english_exercise.py::test_build_scene_prompt_injects_stats PASSED
tests/test_english_exercise.py::test_build_scene_prompt_zero_stats PASSED
tests/test_english_room.py::test_current_scene_prompt_uses_build_scene_prompt PASSED

Full suite: 332 passed in 75.53s
```

## Files Changed

| File | Change |
|------|--------|
| `shadowtalk/core/english_exercise.py` | Added `_SCENE_PROMPT_TEMPLATE` constant + `build_scene_prompt()` function |
| `shadowtalk/ui/widgets/english_room.py` | Override `_current_scene_prompt()` to call `build_scene_prompt` |
| `tests/test_english_exercise.py` | 3 new tests + `_seed_progress` helper |
| `tests/test_english_room.py` | 1 new integration test verifying override calls `build_scene_prompt` |

## Commit

```
a802b57 feat: inject word range and stats into english room scene prompt
```

## Test Summary

| Test | Purpose |
|------|---------|
| `test_build_scene_prompt_injects_word_range` | Verifies word_range string appears in output + Chinese "英语" |
| `test_build_scene_prompt_injects_stats` | Verifies mastered/learning/review_due counts injected (2, 1, 1) |
| `test_build_scene_prompt_zero_stats` | Verifies graceful handling when no progress data exists (all 0) |
| `test_current_scene_prompt_uses_build_scene_prompt` | Verifies `EnglishRoomWindow._current_scene_prompt()` override calls `build_scene_prompt` with correct args |

## Self-Review Findings

1. **Template lives at module level** — `_SCENE_PROMPT_TEMPLATE` is a module constant (consistent with `PRESENT_EXERCISE_TOOL` pattern).
2. **SQL queries match existing patterns** — uses same `english_progress` table structure as `upsert_progress`/`get_next_word`.
3. **review_due uses `review_at IS NOT NULL AND review_at <= now`** — consistent with `get_next_word` which has identical WHERE clause for due reviews.
4. **Override is minimal** — 4-line method added before `closeEvent`, clean override of parent's `_current_scene_prompt()`.
5. **Import inside method** — avoids circular imports (english_room already imports from english_exercise at top, but the override uses local import to be explicit about the dependency).
6. **Test coverage** — covers word_range injection, stats injection, zero-stats edge case, and the UI override wiring.

## Concerns

None. Implementation matches the task brief exactly, all 332 tests pass, no regressions.
