# Task 5 Report: Word range selection dialog

## Status: ✅ Complete

## TDD Evidence

**Red phase** — tests failed before implementation:
```
ERROR tests/test_english_word_range_dialog.py
E   ModuleNotFoundError: No module named 'shadowtalk.ui.widgets.english_word_range_dialog'
```

**Green phase** — after implementation:
```
tests/test_english_word_range_dialog.py::test_dialog_default_selection PASSED
tests/test_english_word_range_dialog.py::test_dialog_with_progress PASSED
tests/test_english_word_range_dialog.py::test_dialog_all_ranges PASSED
tests/test_english_word_range_dialog.py::test_dialog_continue_disabled_without_progress PASSED
tests/test_english_word_range_dialog.py::test_dialog_continue_enabled_with_progress PASSED
tests/test_english_word_range_dialog.py::test_dialog_select_range_and_mode PASSED
tests/test_english_word_range_dialog.py::test_dialog_restart_mode PASSED
7 passed in 1.56s
```

**Full suite**: 299 passed in 66.43s (no regressions).

## Files Changed

- `shadowtalk/ui/widgets/english_word_range_dialog.py` (new) — `EnglishWordRangeDialog` + `WORD_RANGES` constant
- `tests/test_english_word_range_dialog.py` (new) — 7 tests

## Implementation Notes

- Dialog is a `QDialog`, modal, 380×280px, with two `QButtonGroup`s (range + mode).
- `has_progress=False` → "continue" radio disabled, "restart" checked by default.
- `has_progress=True` → "continue" enabled and checked by default.
- `get_selected_range()` returns `(word_range_key, mode)` tuple; mode is one of `continue`/`restart`/`test`.
- Added 3 extra tests beyond the brief (continue enabled/disabled state, interactive selection, restart mode) to cover the `has_progress` gating logic and the `get_selected_range()` mapping.

## Self-Review Findings

- ✅ Matches brief spec exactly (UI structure, method signature, return values).
- ✅ Follows codebase conventions: Chinese comments, English identifiers, snake_case, 4-space indent, `logger = logging.getLogger(__name__)`.
- ✅ No PySide6 import in non-UI layer (dialog is UI, so fine).
- ✅ `WORD_RANGES` is module-level constant, importable for tests.
- ⚠️ Minor: `Qt` import is unused (brief included it). Left as-is to match the brief verbatim; harmless.
- ⚠️ `get_selected_range()` uses `rb.text()` comparison — works because radio labels match keys exactly. Fragile if labels are localized later, but acceptable for now.
- ✅ All 7 tests pass; full suite green.

## Commit

`1a59372` — `feat: add english word range selection dialog`
