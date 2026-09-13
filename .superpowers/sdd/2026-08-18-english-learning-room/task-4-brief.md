# Task 4: AIWorker — exercise suspend/resume mechanism

**Files to modify:**
- `shadowtalk/ui/threads/ai_worker.py`
- `tests/test_ai_worker.py` (add tests)

**What to do:**

1. **Add signals** to the `AIWorker` class:
```python
    exercise_requested = Signal(str, str, str)   # (exercise_json, word_range, reason)
    exercise_answered = Signal(str, str)         # (tool_call_id, result_json) — optional, for future use
```

2. **Add fields** to `__init__`:
```python
        self._word_range = ""
        self._exercise_loop = None
        self._last_exercise_result = None
```

Add `word_range: str = ""` parameter to `__init__` signature.

3. **Add `present_exercise` interception in `_run_tool`**. Replace the method with:

```python
    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码；present_exercise 挂起等待用户答题。"""
        # present_exercise 工具：挂起线程等待用户答题，不执行代码
        # 检测方式：reason 以 "出题: " 开头且 code 是 JSON 对象字符串
        if reason.startswith("出题: ") and code and code.strip().startswith("{"):
            from PySide6.QtCore import QEventLoop
            loop = QEventLoop()
            self._exercise_loop = loop
            self._last_exercise_result = None
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

4. **Add `resume_exercise` method**:

```python
    def resume_exercise(self, result_json: str) -> None:
        """用户答题后恢复挂起的练习循环。由 UI 线程调用。"""
        self._last_exercise_result = result_json
        if self._exercise_loop is not None:
            self._exercise_loop.quit()
```

5. **Add tests** to `tests/test_ai_worker.py`:

```python
def test_exercise_signals_exist():
    """AIWorker 应有 exercise_requested 和 exercise_answered 信号"""
    from shadowtalk.ui.threads.ai_worker import AIWorker
    assert hasattr(AIWorker, "exercise_requested")
    assert hasattr(AIWorker, "exercise_answered")


def test_resume_exercise_method_exists():
    """AIWorker 应有 resume_exercise 方法"""
    from shadowtalk.ui.threads.ai_worker import AIWorker
    assert hasattr(AIWorker, "resume_exercise")
```

**Verification:**
- `pytest tests/test_ai_worker.py -v -k "exercise"` → PASS
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: add exercise suspend/resume to AIWorker`

**Context:** The existing `_run_tool` method handles `run_python` tool execution with approval flow. The `present_exercise` tool needs different handling: instead of executing code, it suspends the worker thread (via nested QEventLoop) and emits a signal so the UI can render an exercise card. When the user answers, `resume_exercise` is called to unblock the loop and return the result as a tool_result string.

The detection logic checks `reason.startswith("出题: ")` (set by ai_client.py Task 3) AND `code.strip().startswith("{")` (valid JSON object) to avoid false positives on regular tool calls.
