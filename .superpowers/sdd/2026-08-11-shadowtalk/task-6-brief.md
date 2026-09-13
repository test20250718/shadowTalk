# Task 6: AI Client

**Files:**
- Create: `shadowtalk/core/ai_client.py`
- Create: `tests/test_ai_client.py`

## Interfaces
- Consumes: `Settings` (for API config)
- Produces:
  - `AIClient.chat(messages: list[dict]) -> str`

## Implementation

```python
# shadowtalk/core/ai_client.py
import openai


class AIClient:
    """封装 OpenAI 兼容接口，纯 Python 无 UI 依赖"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 2000):
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def chat(self, messages: list[dict]) -> str:
        """非流式调用，返回完整回复文本"""
        clean_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=clean_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        return response.choices[0].message.content
```

## Tests

```python
# tests/test_ai_client.py
from unittest.mock import MagicMock, patch
from shadowtalk.core.ai_client import AIClient


def test_chat_returns_content():
    client = AIClient(
        base_url="https://api.test.com/v1",
        api_key="test-key",
        model="test-model"
    )
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "AI回复内容"
    
    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response
        result = client.chat([{"role": "user", "content": "你好"}])
    
    assert result == "AI回复内容"

def test_chat_strips_layer_key():
    """Ensure internal 'layer' key is not sent to API"""
    client = AIClient(
        base_url="https://api.test.com/v1",
        api_key="test-key",
        model="test-model"
    )
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "回复"
    
    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response
        result = client.chat([
            {"role": "system", "content": "人设", "layer": "L3"},
            {"role": "user", "content": "你好", "layer": "L0"},
        ])
        
        # Verify the call was made with clean messages (no 'layer' key)
        call_args = mock_instance.chat.completions.create.call_args
        sent_messages = call_args.kwargs["messages"]
        for msg in sent_messages:
            assert "layer" not in msg
    
    assert result == "回复"
```

## TDD Steps
1. Write failing test
2. Run to verify FAIL
3. Implement ai_client.py
4. Run to verify PASS
5. Commit
