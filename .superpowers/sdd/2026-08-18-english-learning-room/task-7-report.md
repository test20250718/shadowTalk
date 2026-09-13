# Task 7 Report: UI — exercise card rendering (all 5 types)

## Status: ✅ Complete

## Commits
- `feat: implement all 5 exercise card types with answer checking`

## Files Changed
- `shadowtalk/ui/widgets/english_room.py` — replaced placeholder with full ExerciseCard + answer/skip/feedback flow
- `tests/test_english_room.py` — 27 tests covering all 5 types, answer correctness, skip, resume, feedback, double-answer guard

## Implementation Summary

### ExerciseCard (QFrame)
- Constructor takes `exercise_data`, `tool_call_id`, `window` (callback ref), `parent`
- `_render()` dispatches by `data["type"]` to type-specific methods
- Each type has its own `_render_<type>()` + interaction handlers
- Shared: `_add_action_buttons()` (检查答案/提示/跳过), `_get_user_answer()`, `_get_hint()`, style helpers

### 5 Card Types
1. **sentence_build** — word pool → build area chip movement (click to move, click to return)
2. **cloze** — prompt with `____` + 4 option buttons, single select with highlight
3. **match** — left (English) / right (Chinese, shuffled) columns, click-to-pair, QTimer countdown (15s), auto-submit on completion or timeout
4. **translate_assemble** — Chinese prompt + English chips (with distractors), pool→build like sentence_build
5. **story** — English narrative + QRadioButton choices, single select

### Window Callbacks
- `_check_answer(card, data, user_answer)` — records stats, shows feedback, calls `resume_exercise`, re-enables input
- `_skip_exercise(card, data)` — marks skipped, calls `resume_exercise`, re-enables input
- `_show_feedback(card, correct, correct_answer, explanation)` — green ✅ or red ❌ QLabel in card

### Answer Checking
- Case-insensitive comparison: `user_answer.strip().lower() == correct_answer.strip().lower()`
- Guard: `_answered` flag prevents double-submission
- Stats: `record_exercise()` + `upsert_progress()` per existing core API

## Test Results
```
tests/test_english_room.py — 27 passed
tests/ (full suite, excl. test_main_window.py) — 326 passed
```

### Test Coverage
| Category | Tests |
|----------|-------|
| Skeleton/layout (carried from Task 6) | 7 |
| Render each type (no crash) | 5 |
| Correct answer records stats | 4 (cloze, sentence_build, translate_assemble, story) |
| Wrong answer records stats | 2 (cloze, sentence_build) |
| resume_exercise called | 2 (correct + wrong) |
| Skip flow | 1 |
| Input re-enabled | 2 (answer + skip) |
| Double-answer guard | 1 |
| Feedback display | 2 (correct + wrong) |

## Self-Review Findings
- ✅ All 5 exercise types render without crashing
- ✅ Answer checking matches brief's algorithm exactly
- ✅ `resume_exercise` called with proper JSON result
- ✅ Input re-enabled after answer/skip
- ✅ Double-answer protected
- ✅ Feedback shows correct/wrong with explanation
- ✅ Match timer auto-submits on timeout
- ✅ `_FakeWorker` in tests has proper signal stubs for teardown

### Minor Notes
- Match answer format uses " / " separator — AI should provide `answer` field in same format for comparison to work; alternatively, future enhancement could compare pairs directly
- Hint button appears on all types but reveals the full answer for cloze/story (acceptable per brief, could be softened later)
- `random` import moved to top-level (was briefly inline during dev)

## Post-Review Fixes (Coordinator Review Round)

### Critical Fix — Closure over loop variable in `_render_match`
- **Bug:** `lambda checked, e=en: self._on_left_click(e, btn)` captured `btn` by reference — all left-column lambdas resolved to the LAST button after the loop. Same defect on the right column.
- **Fix:** Bind `btn` as a default argument: `lambda checked, e=en, b=btn: self._on_left_click(e, b)`. Same for right column.
- **Why tests didn't catch it originally:** Existing match test only checked that the card rendered (button count), not that clicking each button invoked its own handler.

### Important Fix — Match timer not stopped on manual submit
- **Bug:** Clicking "检查答案" before timeout left `self._match_timer` running — it would fire `_on_match_tick` later and double-submit.
- **Fix:** `_on_check_answer` now calls `self._match_timer.stop()` when `type == "match"`.

### New Tests Added
1. `test_match_full_pair_cycle_correct` — performs a full left→right pair cycle through the real click callbacks and asserts `correct=True`. This test would have caught the closure bug (with the bug, all clicks target the last button and pairing fails).
2. `test_match_timer_stops_on_manual_submit` — verifies the timer is inactive after manual submit.

### Re-test Results
- `tests/test_english_room.py` — **29 passed** (27 original + 2 new)
- Full suite (excl. `test_main_window.py`) — **328 passed**

## Concerns
None blocking. The match-type answer comparison relies on the AI providing the `answer` field in the expected " / " format. If the AI doesn't, match answers will always register as incorrect. This is a soft dependency on AI output formatting — acceptable for now, could be hardened in a future task by comparing pairs directly.
