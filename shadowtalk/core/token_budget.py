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
