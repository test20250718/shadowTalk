# Task 7: Summarizer

**Files:**
- Create: `shadowtalk/core/summarizer.py`
- Create: `tests/test_summarizer.py`

## Interfaces
- Consumes: `AIClient`, `SummaryRepository`, `MessageRepository`, `Database.transaction()`
- Produces:
  - `generate_batch_summary(friend_id, messages) -> str`
  - `generate_high_level_summary(expired_summaries) -> str`
  - `merge_high_level_summaries(summaries) -> str`

## Implementation

```python
# shadowtalk/core/summarizer.py
from shadowtalk.data.repositories import SummaryRepository, MessageRepository
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings


def get_ai_client():
    """Factory: create AIClient from current Settings"""
    from shadowtalk.core.ai_client import AIClient
    return AIClient(
        base_url=Settings.get("api_base_url"),
        api_key=Settings.get("api_key"),
        model=Settings.get("model_name"),
        temperature=Settings.get_float("temperature"),
        max_tokens=Settings.get_int("max_output_tokens"),
    )


def build_summary_prompt(messages: list) -> list[dict]:
    """构建生成摘要的 prompt"""
    dialogue = "\n".join(
        f"{'用户' if m['sender_type'] == 'user' else 'AI'}: {m['content']}"
        for m in messages
    )
    word_limit = Settings.get_int("daily_summary_word_limit")
    return [
        {
            "role": "system",
            "content": f"请将以下对话压缩为一条{word_limit}字以内的简短摘要，"
                       f"保留关键信息和情感走向。"
        },
        {"role": "user", "content": dialogue},
    ]


def build_merge_prompt(summaries: list) -> list[dict]:
    """构建合并摘要的 prompt"""
    text = "\n".join(f"- {s['content']}" for s in summaries)
    return [
        {
            "role": "system",
            "content": "请将以下多条摘要合并为一条极简的高阶记忆，"
                       "保留最核心的人物关系和情感走向。"
        },
        {"role": "user", "content": text},
    ]


def generate_batch_summary(friend_id: int, messages: list) -> str:
    """生成批次摘要，带重试和截断兜底。写入 DB + 标记原文已归档。"""
    ai = get_ai_client()
    prompt = build_summary_prompt(messages)
    word_limit = Settings.get_int("daily_summary_word_limit")

    text = ""
    for _ in range(2):
        try:
            text = ai.chat(prompt)
            if len(text) <= word_limit:
                break
        except Exception:
            continue
    else:
        text = (text if text else "摘要生成失败")[:word_limit] + "…[摘要截断]"

    is_truncated = 1 if text.endswith("…[摘要截断]") else 0
    start_round = min(m["round_index"] for m in messages)
    end_round = max(m["round_index"] for m in messages)

    with Database.transaction() as conn:
        SummaryRepository.save_batch_summary(
            friend_id, text, start_round, end_round, is_truncated
        )
        msg_ids = [m["id"] for m in messages]
        placeholders = ",".join("?" * len(msg_ids))
        conn.execute(
            f"UPDATE chat_messages SET is_archived=1 WHERE id IN ({placeholders})",
            msg_ids
        )

    return text


def generate_high_level_summary(expired_summaries: list) -> str:
    """合并多条过期批次摘要为一条 L2"""
    ai = get_ai_client()
    prompt = build_merge_prompt(expired_summaries)
    try:
        return ai.chat(prompt)
    except Exception:
        return "高阶摘要生成失败"


def merge_high_level_summaries(summaries: list) -> str:
    """合并多条 L2 为一条（L2 超限时使用）"""
    return generate_high_level_summary(summaries)
```

## Tests

```python
# tests/test_summarizer.py
from unittest.mock import MagicMock, patch
from shadowtalk.core.summarizer import (
    generate_batch_summary, generate_high_level_summary
)
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def test_generate_batch_summary_success():
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    MessageRepository.insert(fid, "ai", "你好！", 1)
    msgs = MessageRepository.get_unarchived(fid)
    
    mock_ai = MagicMock()
    mock_ai.chat.return_value = "简短摘要"
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_batch_summary(fid, msgs)
    
    assert result == "简短摘要"
    assert MessageRepository.count_unarchived_rounds(fid) == 0

def test_generate_batch_summary_truncation():
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    msgs = MessageRepository.get_unarchived(fid)
    
    mock_ai = MagicMock()
    mock_ai.chat.return_value = "超" * 100
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_batch_summary(fid, msgs)
    
    assert len(result) <= 52
    assert "截断" in result

def test_generate_high_level_summary():
    mock_ai = MagicMock()
    mock_ai.chat.return_value = "聚合后的高阶记忆"
    
    expired = [
        {"content": "旧摘要1"},
        {"content": "旧摘要2"},
    ]
    
    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_high_level_summary(expired)
    
    assert result == "聚合后的高阶记忆"
```

## TDD Steps
1. Write failing tests
2. Run to verify FAIL
3. Implement summarizer.py
4. Run to verify PASS
5. Commit
