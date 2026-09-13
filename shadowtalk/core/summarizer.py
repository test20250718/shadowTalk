# shadowtalk/core/summarizer.py
from shadowtalk.data.repositories import SummaryRepository, MessageRepository
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings


class SummaryGenerationError(Exception):
    """摘要生成失败（AI 不可用或返回为空）。"""
    pass


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
    """构建生成摘要的 prompt（目标字数为软引导，不做硬截断）"""
    dialogue = "\n".join(
        f"{'用户' if m['sender_type'] == 'user' else 'AI'}: {m['content']}"
        for m in messages
    )
    target = Settings.get_int("summary_target_chars")
    return [
        {
            "role": "system",
            "content": f"请将以下对话压缩为一条约{target}字的摘要，"
                       f"保留关键信息、人物关系和情感走向。"
                       f"字数仅供参考，宁可完整也不要遗漏要点。"
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
    """生成批次摘要并归档原文。写入 DB + 标记原文已归档。

    目标字数是软引导：AI 返回超长也保留全文，绝不截断
    （用户反馈：30 条消息被砍成 50 字还带"[摘要截断]"，记忆残缺）。
    AI 调用失败时抛 SummaryGenerationError，不落库、不归档原文——
    避免用占位符顶替真实记忆造成数据丢失。
    """
    if not messages:
        return ""
    ai = get_ai_client()
    prompt = build_summary_prompt(messages)

    text = ""
    for _ in range(2):  # 网络类错误重试一次
        try:
            text = ai.chat(prompt).strip()
            if text:
                break
        except Exception:
            continue
    if not text:
        raise SummaryGenerationError("两次尝试均未生成摘要内容")

    start_round = min(m["round_index"] for m in messages)
    end_round = max(m["round_index"] for m in messages)

    with Database.transaction() as conn:
        conn.execute(
            "INSERT INTO batch_summary "
            "(friend_id, content, start_round, end_round, is_truncated) "
            "VALUES (?, ?, ?, ?, 0)",
            (friend_id, text, start_round, end_round)
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
