# tests/test_ai_client.py
from unittest.mock import MagicMock, patch
from shadowtalk.core.ai_client import AIClient


def test_chat_returns_content():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "AI回复内容"

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response
        client = AIClient(
            base_url="https://api.test.com/v1",
            api_key="test-key",
            model="test-model"
        )
        result = client.chat([{"role": "user", "content": "你好"}])

    assert result == "AI回复内容"


def test_chat_strips_layer_key():
    """Ensure internal 'layer' key is not sent to API"""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "回复"

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response
        client = AIClient(
            base_url="https://api.test.com/v1",
            api_key="test-key",
            model="test-model"
        )
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


def test_chat_with_tools_executes_tool_call():
    """模型请求工具 → 执行 → 结果回传 → 返回最终文本"""
    tool_msg = MagicMock()
    tool_msg.content = None
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "run_python"
    tool_call.function.arguments = '{"code": "print(1)", "reason": "测试"}'
    tool_msg.tool_calls = [tool_call]

    final_msg = MagicMock()
    final_msg.content = "完成！"
    final_msg.tool_calls = None

    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=tool_msg)]
    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=final_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.side_effect = [resp1, resp2]

        client = AIClient(base_url="https://t", api_key="k", model="m")
        executed = []
        result = client.chat_with_tools(
            [{"role": "user", "content": "你好"}],
            tool_runner=lambda code, reason: executed.append(code) or "输出: 1"
        )

    assert executed == ["print(1)"]
    assert result == "完成！"


def test_chat_with_tools_falls_back_without_tools_support():
    """模型不支持 tools（抛异常）→ 回退 chat()"""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "纯文本回复"
    mock_response.choices[0].message.tool_calls = None

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        # 第一次调用（带 tools）抛异常 → 回退；第二次（chat 内部）返回纯文本
        mock_instance.chat.completions.create.side_effect = [
            RuntimeError("tools not supported"), mock_response]

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "你好"}],
            tool_runner=lambda c, r: "x"
        )
    assert result == "纯文本回复"


def test_chat_with_tools_limits_loop_to_5():
    """循环上限 5 次"""
    tool_msg = MagicMock()
    tool_msg.content = None
    tool_call = MagicMock()
    tool_call.id = "call_x"
    tool_call.function.name = "run_python"
    tool_call.function.arguments = '{"code": "x", "reason": "r"}'
    tool_msg.tool_calls = [tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=tool_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = mock_response

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "hi"}],
            tool_runner=lambda c, r: "out",
            max_tool_calls=5,
        )
    # 循环 5 次后强制停止，返回拟人化"掉线"提示（引导用户任意回复）
    assert "掉线" in result


# ── 空回复防御（用户报告：秘书角色空回复闭嘴，空历史毒害后续所有请求）──

def test_chat_with_tools_empty_content_retries_without_tools():
    """模型在工具轮后返回空 content（无 tool_calls）→ 重试一次纯文本"""
    empty_msg = MagicMock()
    empty_msg.content = ""      # 空回复
    empty_msg.tool_calls = None
    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=empty_msg)]

    plain_msg = MagicMock()
    plain_msg.content = "重试成功"
    plain_msg.tool_calls = None
    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=plain_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.side_effect = [resp1, resp2]

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "继续"}],
            tool_runner=lambda c, r: "out"
        )
    assert result == "重试成功"


def test_chat_with_tools_empty_everything_returns_fallback():
    """重试仍空 → 返回非空兜底文案（空气泡不得入库/显示）"""
    empty_msg = MagicMock()
    empty_msg.content = None   # content 为 None
    empty_msg.tool_calls = None
    resp = MagicMock()
    resp.choices = [MagicMock(message=empty_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = resp

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "在吗"}],
            tool_runner=lambda c, r: "out"
        )
    assert isinstance(result, str)
    assert result.strip(), "兜底文案不得为空"


def test_chat_with_tools_filters_empty_assistant_history():
    """已落库的空 assistant 消息不得发给 API（毒害后续请求致持续空回复）"""
    final_msg = MagicMock()
    final_msg.content = "好的"
    final_msg.tool_calls = None
    resp = MagicMock()
    resp.choices = [MagicMock(message=final_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.return_value = resp

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": ""},       # 历史空回复
                {"role": "assistant", "content": "   "},    # 纯空白
                {"role": "assistant", "content": "正常回复"},
                {"role": "user", "content": "在吗"},
            ],
            tool_runner=lambda c, r: "out"
        )

        sent = mock_instance.chat.completions.create.call_args.kwargs["messages"]
        contents = [(m["role"], m["content"]) for m in sent]
        assert ("assistant", "") not in contents
        assert ("assistant", "   ") not in contents
        assert ("assistant", "正常回复") in contents
    assert result == "好的"
