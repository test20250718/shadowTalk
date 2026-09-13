# Task 3: AI client — register present_exercise tool

**Files to modify:**
- `shadowtalk/core/ai_client.py`
- `tests/test_ai_client.py` (add test)

**What to do:**

1. **Add import** at the top of `shadowtalk/core/ai_client.py`:
```python
from shadowtalk.core.english_exercise import PRESENT_EXERCISE_TOOL
```

2. **Add `present_exercise` to the tools list** in `chat_with_tools()`. Change the `tools` variable from a single-element list to two elements (keep existing `run_python` tool, add `PRESENT_EXERCISE_TOOL`):

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

3. **Add dispatch branch** in the `for tc in message.tool_calls:` loop. After the `if name == "run_python":` block (around line 125-133), add an `elif` for `present_exercise`:

```python
                elif name == "present_exercise":
                    # present_exercise 不由 python_executor 执行，
                    # 而是由 AIWorker._run_tool 拦截并挂起等待用户交互。
                    # 此处把工具参数作为 code 传给 tool_runner。
                    exercise_json = args if isinstance(args, str) else json.dumps(args)
                    result_text = tool_runner(exercise_json, f"出题: {args.get('word', '')}")
```

This goes AFTER the `if name == "run_python":` block and BEFORE the `else: result_text = f"未知工具: {name}"` line.

4. **Add test** to `tests/test_ai_client.py`:

```python
def test_present_exercise_in_tools():
    """present_exercise 工具应出现在 chat_with_tools 的工具列表中"""
    import shadowtalk.core.ai_client as ai_mod
    src = open(ai_mod.__file__).read()
    assert "present_exercise" in src
    assert "PRESENT_EXERCISE_TOOL" in src
```

**Verification:**
- `pytest tests/test_ai_client.py::test_present_exercise_in_tools -v` → PASS
- `python -m pytest tests/ -q --ignore=tests/test_main_window.py` → all pass

**Commit message:** `feat: register present_exercise tool in ai_client`

**Context:** The existing `chat_with_tools` method has a tools list with one tool (`run_python`). The tool loop dispatches by name. For `present_exercise`, the actual execution happens in `AIWorker._run_tool` (Task 4) — here we just route the tool call to `tool_runner` with the JSON args as `code` and a reason prefix `"出题: "` so the worker can detect it.
