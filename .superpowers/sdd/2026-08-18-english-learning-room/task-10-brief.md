# Task 10: Full integration polish and edge cases

**Files to modify:**
- `shadowtalk/ui/widgets/english_room.py`
- `shadowtalk/ui/threads/ai_worker.py`
- Various test files

**What to do:**

This is the final polish task. Address these edge cases and integration issues identified during development:

1. **Handle worker recreation on each message** — In `EnglishRoomWindow._on_send`, ensure exercise signal is reconnected for each new worker (already done in Task 8, but verify).

2. **Handle closeEvent cleanup** — Override `closeEvent` in `EnglishRoomWindow` to clean up `_current_card` (already done in Task 6, but verify).

3. **Disable input during exercise** — In `_on_exercise_requested`, disable input_edit and send_btn. Re-enable in `_check_answer` and `_skip_exercise` (already done in Task 7, but verify).

4. **Handle rapid double-submit** — Guard in `_check_answer` and `_skip_exercise` with `card._answered` flag (already done in Task 7, but verify).

5. **Handle AI worker not having work_dir** — The `present_exercise` tool doesn't need a work_dir (it's not executing code). But `_run_tool` checks `if not self.work_dir:` BEFORE the exercise detection. Fix: move the exercise detection BEFORE the work_dir check.

In `ai_worker.py`, modify `_run_tool`:
```python
    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码；present_exercise 挂起等待用户答题。"""
        # present_exercise 工具：挂起线程等待用户答题（无需工作目录）
        if reason.startswith("出题: ") and code and code.strip().startswith("{"):
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            self._exercise_loop = loop
            self._last_exercise_result = None
            self.exercise_requested.emit(code, self._word_range, reason)
            loop.exec()
            self._exercise_loop = None
            return self._last_exercise_result or json.dumps({
                "correct": False, "user_answer": "", "correct_answer": "",
                "attempts": 1, "time_used": 0, "exercise_type": "skip", "skipped": True})

        if not self.work_dir:
            logger.warning("拒绝工具执行: 未配置工作目录")
            return ("当前好友未配置工作目录。请在好友设置中添加工作目录，"
                    "即可让我读写文件。")
        # ... rest unchanged
```

**This is the key fix**: The exercise detection MUST come before the work_dir check, because present_exercise doesn't need a work_dir.

**Verification:**
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass
- Manual smoke test: `python -m shadowtalk.main` → open English room → chat with AI → verify exercise flow works

**Commit message:** `fix: polish english room edge cases and exercise tool ordering`

**Context:** The current `_run_tool` in ai_worker.py has the exercise detection AFTER the work_dir check. This means if the friend doesn't have a work_dir configured, the present_exercise tool would get rejected with "未配置工作目录" instead of rendering a card. The fix moves the exercise detection to the top of the method, before the work_dir check.
