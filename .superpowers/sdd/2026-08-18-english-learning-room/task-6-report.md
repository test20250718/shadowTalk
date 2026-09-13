# Task 6 Report: UI — EnglishRoomWindow skeleton and layout

## Status: ✅ Complete

## TDD Evidence

**Red phase (test before implementation):**
```
tests/test_english_room.py::test_english_room_window_class FAILED
E       ModuleNotFoundError: No module named 'shadowtalk.ui.widgets.english_room'
```
All 9 tests failed with `ModuleNotFoundError` — confirmed the test correctly drives the missing implementation.

**Green phase (after implementation):**
```
tests/test_english_room.py::test_english_room_window_class PASSED
tests/test_english_room.py::test_english_room_subclass_instance PASSED
tests/test_english_room.py::test_chat_scroll_fixed_width PASSED
tests/test_english_room.py::test_exercise_panel_exists PASSED
tests/test_english_room.py::test_stats_label_exists PASSED
tests/test_english_room.py::test_exercise_requested_disables_input PASSED
tests/test_english_room.py::test_exercise_requested_renders_placeholder PASSED
tests/test_english_room.py::test_exercise_requested_invalid_json_no_crash PASSED
tests/test_english_room.py::test_close_event_cleans_up_card PASSED
============================== 9 passed in 6.68s ==============================
```

**Full suite regression:**
```
308 passed in 64.13s (0:01:04)
```

## Files Changed

| File | Action |
|------|--------|
| `shadowtalk/ui/widgets/english_room.py` | Create — `ExerciseCard` stub + `EnglishRoomWindow` |
| `tests/test_english_room.py` | Create — 9 tests |

## Commit

```
c264b7e feat: add EnglishRoomWindow skeleton with layout
```

## Implementation Summary

`EnglishRoomWindow` extends `RoomWindow` following the reading-room pattern:
- Calls `super()._build_ui()` first, then customizes
- Left chat fixed at 280px (matches reading room's right chat)
- Right exercise panel via `self._content_host.addWidget(self.exercise_panel, 1)`
- Stats label (`_stats_label`) showing streak / today count / accuracy
- `_on_exercise_requested` disables input bar + send button during exercise
- `_render_exercise_card` clears old card, inserts placeholder QLabel ("练习卡片加载中…")
- `closeEvent` cleans up `_current_card` before delegating to super
- `ExerciseCard` stub defined (Task 7 adds 5 exercise-type renderers)

## Self-Review Findings

1. **Test fix applied**: Initial test used `findChildren(QLabel)` on the placeholder card, but the placeholder IS a QLabel (not a container). Fixed to assert `isinstance(_current_card, QLabel)` + check `.text()` directly. This is a test-correctness fix, not a workaround.

2. **Signal not wired yet**: `_on_exercise_requested` is defined but not connected to `ai_worker.exercise_requested` in `_build_ui`. This is intentional — the brief's code doesn't connect it, and the AI worker lifecycle is established in the base `RoomWindow._on_send`. The connection will be added when the exercise flow is fully wired (likely Task 7 or integration). The method is unit-tested directly.

3. **`ExerciseCard` stub**: The class is defined but unused (placeholder QLabel used instead). This matches the brief — Task 7 replaces the placeholder with real card rendering using this base class. The `answered` signal and `_start_time`/`_attempts` fields are pre-positioned for Task 7.

4. **No new dependencies**: Only imports from existing modules (`english_exercise`, `room_window`) + PySide6. No DB schema changes, no settings changes.

5. **Chinese comments**: All user-facing strings and comments are in Chinese, consistent with codebase style. English identifiers used throughout.

## Concerns

- **Signal wiring deferred**: `exercise_requested` → `_on_exercise_requested` connection not yet established. Will need to be added when the exercise flow is integrated (Task 7+). Documented as intentional per brief.
- **Stats label placement**: `_stats_label` is created but not yet added to the toolbar layout (brief code creates it but doesn't insert into `top_l`). It is functional for testing (`_update_stats()` works) but not visually placed. Task 7 / polish should add it to the toolbar.
