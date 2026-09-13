# Task 3 Report: AI client — register present_exercise tool

## Status: COMPLETE

## TDD Evidence

### Step 1 — Test written first (RED)

Added `test_present_exercise_in_tools` to `tests/test_ai_client.py`. Initial run
failed with `UnicodeDecodeError: 'gbk' codec can't decode` — on Windows the
default `open()` uses GBK, but the source file contains UTF-8 Chinese
comments. Fixed by passing `encoding="utf-8"` (a real bug in the brief's
test code — without this the test could never pass on a Chinese-Windows
dev machine).

After the encoding fix, the test failed for the **correct** reason:
`assert 'present_exercise' in src` → `AssertionError` (feature not yet
implemented).

### Step 2 — Implementation (GREEN)

Three edits to `shadowtalk/core/ai_client.py`:

1. Added import: `from shadowtalk.core.english_exercise import PRESENT_EXERCISE_TOOL`
2. Extended `tools` list from single-element to two elements, appending
   `PRESENT_EXERCISE_TOOL` after the existing `run_python` tool.
3. Added `elif name == "present_exercise":` dispatch branch before the
   `else: 未知工具` fallback. Routes the tool args (JSON) to
   `tool_runner(exercise_json, f"出题: {word}")` so `AIWorker._run_tool`
   (Task 4) can intercept it.

### Step 3 — Verification

```
tests/test_ai_client.py::test_present_exercise_in_tools PASSED
```

Full ai_client suite: **9 passed** (8 existing + 1 new).

Canonical suite: **287 passed** in 70.25s — no regressions.

## Files Changed

| File | Change |
|------|--------|
| `shadowtalk/core/ai_client.py` | +1 import, tools list extended, +7-line dispatch branch |
| `tests/test_ai_client.py` | +7 lines: `test_present_exercise_in_tools` |

## Self-Review Findings

- **Encoding fix is a real bug, not a deviation.** The brief's test code
  used `open(path).read()` which is GBK-on-Windows-hostile. The fix
  (`encoding="utf-8"`) is required for the test to function on the
  developer's machine. Noted in the diff.
- **Import safety.** `PRESENT_EXERCISE_TOOL` is a module-level dict in
  `english_exercise.py` with no side effects at import time (confirmed:
  the module only defines constants and functions, no top-level I/O).
  Importing it into `ai_client.py` does not create a circular dependency
  (`english_exercise` imports only `Database` and `datetime`/`logging`).
- **Dispatch branch placement.** The `elif` sits correctly between the
  `run_python` block and the `else` fallback, matching the existing
  pattern. The `args.get('word', '')` is safe because `args` is always a
  `dict` at that point (parsed from JSON or defaulted to `{}`).
- **Convention match.** The `json.dumps(args)` / reason prefix pattern
  matches the brief's spec exactly, so Task 4's `AIWorker._run_tool` can
  detect the exercise by inspecting the `code` field.
- **No formatter/linter in project** — indentation and style follow the
  surrounding code (4-space indent, Chinese comments explaining the
  user-facing behavior).

## Concerns

None blocking. The encoding fix is worth flagging to the author of the
brief — the test as written would fail on any Chinese/UTF-8 Windows
environment regardless of implementation correctness.
