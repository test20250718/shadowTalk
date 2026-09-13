# Task 9: Memory Engine (Main Pipeline)

**Files:**
- Create: `shadowtalk/core/memory_engine.py`
- Create: `tests/test_memory_engine.py`

## Interfaces
- Consumes: `archiver`, `l3`, `l2`, `l1`, `l0`, `token_budget`, `Settings`
- Produces:
  - `build_context(friend_id: int, user_message: str) -> list[dict]`

## Implementation

```python
# shadowtalk/core/memory_engine.py
from shadowtalk.core.layers import l3, l2, l1, l0
from shadowtalk.core.archiver import check_and_archive
from shadowtalk.core.token_budget import trim_context
from shadowtalk.config.settings import Settings


def build_context(friend_id: int, user_message: str) -> list[dict]:
    """
    组装完整的 AI 上下文消息列表。
    返回: [{"role": "system"|"user"|"assistant", "content": str, "layer": "L0"|"L1"|"L2"|"L3"}, ...]
    """
    # 1. 归档检查
    check_and_archive(friend_id)

    # 2. 逐层提取
    context = []
    context += l3.extract(friend_id)
    context += l2.extract(friend_id)
    context += l1.extract(friend_id)
    context += l0.extract(friend_id)

    # 3. Token 预算检查 & 裁剪
    max_tokens = Settings.get_int("max_context_tokens")
    context = trim_context(context, max_tokens)

    # 4. 追加用户最新消息
    context.append({"role": "user", "content": user_message})

    return context
```

## Tests

```python
# tests/test_memory_engine.py
from shadowtalk.core.memory_engine import build_context
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)
from shadowtalk.config.settings import Settings


def test_build_context_basic():
    fid = FriendRepository.insert("好友", "", "你是一个助手")
    MessageRepository.insert(fid, "user", "你好", 1)
    
    result = build_context(fid, "新消息")
    
    layers = [m.get("layer") for m in result]
    assert "L3" in layers
    assert "L0" in layers
    assert result[-1]["role"] == "user"
    assert result[-1]["content"] == "新消息"

def test_build_context_with_summaries():
    fid = FriendRepository.insert("好友", "", "人设")
    SummaryRepository.save_batch_summary(fid, "批次摘要", 1, 30)
    SummaryRepository.save_high_level_summary(fid, "高阶摘要")
    
    result = build_context(fid, "你好")
    
    layers = [m.get("layer") for m in result]
    assert "L3" in layers
    assert "L2" in layers
    assert "L1" in layers

def test_build_context_order():
    """Verify L3 -> L2 -> L1 -> L0 -> user order"""
    fid = FriendRepository.insert("好友", "", "人设")
    SummaryRepository.save_high_level_summary(fid, "L2")
    SummaryRepository.save_batch_summary(fid, "L1", 1, 30)
    MessageRepository.insert(fid, "user", "L0", 1)
    
    result = build_context(fid, "用户消息")
    
    layers = [m.get("layer") for m in result if m.get("layer")]
    assert layers == ["L3", "L2", "L1", "L0"]

def test_build_context_trims_l0():
    """When context exceeds max_tokens, L0 should be trimmed"""
    fid = FriendRepository.insert("好友", "", "人设")
    for i in range(20):
        MessageRepository.insert(fid, "user", "x" * 200, i + 1)
    
    Settings.set("max_context_tokens", "50")
    
    result = build_context(fid, "新消息")
    
    assert result[0]["layer"] == "L3"
    l0_count = sum(1 for m in result if m.get("layer") == "L0")
    assert l0_count < 20
    
    # Restore default
    Settings.set("max_context_tokens", "8000")
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement memory_engine.py
4. Run to verify PASS
5. Commit
