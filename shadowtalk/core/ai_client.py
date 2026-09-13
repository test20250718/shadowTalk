# shadowtalk/core/ai_client.py
import json
import re

import openai

# 空回复兜底文案（模型返回空 content 且重试仍空时使用，
# 避免空气泡落库显示、并污染后续上下文）
_EMPTY_REPLY_FALLBACK = "（我刚才没反应过来，请再说一遍。）"


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """发送前清洗：去掉内部 layer 键；剔除空 content 的 assistant 历史。

    历史 bug 落库的空 assistant 消息会让部分模型/网关在后续请求中
    持续返回空内容（用户报告：秘书角色从此闭嘴），必须在发送前滤除。
    """
    clean = []
    for m in messages:
        content = str(m.get("content") or "")
        if m.get("role") == "assistant" and not content.strip():
            continue
        clean.append({"role": m["role"], "content": content})
    return clean



# ── 文本工具调用解析器（处理不支持函数调用的模型）──
# 部分模型/网关不返回标准 tool_calls，而是把工具调用拼在 content 文本里。
_TEXT_TOOL_RE_LOOSE = re.compile(
    r"run_python[\s\S]*?```(?:python|py)?[\s\S]*?```",
    re.IGNORECASE,
)


def _parse_text_tool_calls(text: str, tool_runner) -> str:
    """从纯文本中提取并执行 run_python 工具调用，返回清理后的文本。"""
    if "run_python" not in text:
        return text

    def _replace_match(m):
        block = m.group(0)
        code_match = re.search(
            r"```(?:python|py)?\s*([\s\S]*?)```", block, re.IGNORECASE
        )
        if not code_match:
            return ""
        code = code_match.group(1).strip()
        if not code:
            return ""
        try:
            result = tool_runner(code, "执行代码")
            if "异常" in result or "Error" in result:
                return f"[代码执行出错: {result[:100]}]"
            return ""
        except Exception as e:
            return f"[代码执行失败: {e}]"

    new_text = _TEXT_TOOL_RE_LOOSE.sub(_replace_match, text)
    new_text = re.sub(r"run_python\s*\n?", "", new_text)
    return new_text.strip()


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
        clean_messages = _sanitize_messages(messages)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=clean_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        if not response.choices:
            raise ValueError("API returned empty choices")
        return response.choices[0].message.content or ""

    def chat_with_tools(self, messages: list[dict],
                        tool_runner, max_tool_calls: int = 15) -> str:
        """
        带工具调用的多轮对话。
        tool_runner: Callable[[code: str, reason: str], str] 执行代码返回文本结果
        模型不支持 tools 时回退纯文本 chat()
        """
        clean_messages = _sanitize_messages(messages)
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
        ]

        for _ in range(max_tool_calls):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=clean_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    tools=tools,
                )
            except Exception:
                return self.chat(messages)

            if not response.choices:
                raise ValueError("API returned empty choices")
            message = response.choices[0].message

            if not getattr(message, "tool_calls", None):
                # 没有标准 tool_calls，检查是否是纯文本形式的工具调用
                content = message.content or ""
                if "run_python" in content.strip():
                    # 模型以文本形式输出了工具调用 → 解析并执行
                    cleaned = _parse_text_tool_calls(content, tool_runner)
                    if cleaned != content:
                        # 成功执行了文本工具调用，把结果放回上下文继续
                        clean_messages.append({
                            "role": "assistant",
                            "content": content,
                        })
                        clean_messages.append({
                            "role": "user",
                            "content": "[工具已执行，请继续]",
                        })
                        continue
                # 纯文本回复
                if content.strip():
                    return content
                retry = self.chat(messages)
                if retry.strip():
                    return retry
                return _EMPTY_REPLY_FALLBACK

            # 执行标准工具调用
            clean_messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })
            for tc in message.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "run_python":
                    code = args.get("code", "")
                    reason = args.get("reason", "")
                    try:
                        result_text = tool_runner(code, reason)
                    except Exception as e:
                        result_text = f"工具执行异常: {e}"
                else:
                    result_text = f"未知工具: {name}"
                clean_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        return "我不小心掉线了，请任意回复，我马上回来。"
