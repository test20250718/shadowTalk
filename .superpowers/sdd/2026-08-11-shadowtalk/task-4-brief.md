# Task 4: Token Budget

**Files:**
- Create: `shadowtalk/core/__init__.py`
- Create: `shadowtalk/core/token_budget.py`
- Create: `tests/test_token_budget.py`

## Interfaces
- Consumes: nothing (pure functions)
- Produces:
  - `estimate_tokens(text: str) -> int`
  - `trim_context(messages: list[dict], max_tokens: int) -> list[dict]`

## Implementation

```python
# shadowtalk/core/token_budget.py
def estimate_tokens(text: str) -> int:
    """字符数估算：总字符数 // 2（偏保守）"""
    return len(text) // 2


def trim_context(messages: list[dict], max_tokens: int) -> list[dict]:
    """从 L0 最旧消息开始裁剪，直到满足预算。不裁剪非 L0 层。"""
    total = sum(estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages

    protected = [m for m in messages if m.get("layer") != "L0"]
    l0_msgs = [m for m in messages if m.get("layer") == "L0"]

    while l0_msgs and total > max_tokens:
        removed = l0_msgs.pop(0)
        total -= estimate_tokens(removed["content"])

    return protected + l0_msgs
```

## Tests

```python
# tests/test_token_budget.py
import pytest
from shadowtalk.core.token_budget import estimate_tokens, trim_context


def test_estimate_tokens_chinese():
    assert estimate_tokens("你好" * 50) == 50

def test_estimate_tokens_english():
    assert estimate_tokens("a" * 100) == 50

def test_trim_context_no_trim_needed():
    messages = [
        {"role": "system", "content": "hi", "layer": "L3"},
        {"role": "user", "content": "hello", "layer": "L0"},
    ]
    result = trim_context(messages, 1000)
    assert len(result) == 2

def test_trim_context_trims_l0_oldest_first():
    messages = [
        {"role": "system", "content": "persona", "layer": "L3"},
        {"role": "user", "content": "a" * 100, "layer": "L0"},
        {"role": "assistant", "content": "b" * 100, "layer": "L0"},
        {"role": "user", "content": "c" * 100, "layer": "L0"},
    ]
    result = trim_context(messages, 75)
    assert result[0]["layer"] == "L3"
    contents = [m["content"] for m in result]
    assert "a" * 100 not in contents

def test_trim_context_never_trims_non_l0():
    messages = [
        {"role": "system", "content": "x" * 1000, "layer": "L3"},
        {"role": "user", "content": "y" * 1000, "layer": "L0"},
    ]
    result = trim_context(messages, 100)
    assert len(result) == 1
    assert result[0]["layer"] == "L3"
```

## TDD Steps
1. Write failing test
2. Run to verify FAIL
3. Implement token_budget.py
4. Run to verify PASS
5. Commit
