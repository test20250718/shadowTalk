# shadowtalk/core/memory_engine.py
import logging

from shadowtalk.core.layers import l3, l2, l1, l0
from shadowtalk.core.archiver import check_and_archive
from shadowtalk.core.token_budget import trim_context, estimate_tokens
from shadowtalk.core import summarizer
from shadowtalk.data.repositories import MessageRepository
from shadowtalk.config.settings import Settings

logger = logging.getLogger(__name__)

# 单次最多压缩批数（每批一次 AI 调用），防止超长历史阻塞界面过久
MAX_COMPRESS_ROUNDS = 10


def build_context(friend_id: int, user_message: str) -> list[dict]:
    """
    组装完整的 AI 上下文消息列表。
    返回: [{"role": "system"|"user"|"assistant", "content": str, "layer": "L0"|"L1"|"L2"|"L3"}, ...]
    """
    # 1. 归档检查（轮次维度：raw_keep_max / batch_size 双门槛）
    check_and_archive(friend_id)

    # 2. 逐层提取
    context = _extract_all(friend_id)

    # 3. Token 预算检查：超预算先归档压缩（生成 L1 摘要），不裸截断。
    #    压缩失败（AI 不可用）或剩余不足一批时，才退回截断兜底——
    #    保证本次请求始终能发出去。（用户反馈：第16~19轮既没被摘要
    #    也不在上下文里，成了"真空区"）
    max_tokens = Settings.get_int("max_context_tokens")
    if _total_tokens(context) > max_tokens:
        context = _compress_to_fit(friend_id, max_tokens)
        if _total_tokens(context) > max_tokens:
            context = trim_context(context, max_tokens)

    # 4. 追加用户最新消息。
    # 调用方（_on_message_sent）先落库再构建：L0 末尾已含同一条时不得
    # 再追加，否则模型每条消息都看到两遍（AI 反馈"你连说两遍"）。
    last = context[-1] if context else None
    already_latest = (last is not None
                      and last.get("role") == "user"
                      and last.get("content") == user_message)
    if not already_latest:
        context.append({"role": "user", "content": user_message})

    return context


def _extract_all(friend_id: int) -> list[dict]:
    """L3 -> L2 -> L1 -> L0 逐层提取"""
    context = []
    context += l3.extract(friend_id)
    context += l2.extract(friend_id)
    context += l1.extract(friend_id)
    context += l0.extract(friend_id)
    return context


def _total_tokens(context: list[dict]) -> int:
    return sum(estimate_tokens(m["content"]) for m in context)


def _compress_to_fit(friend_id: int, max_tokens: int) -> list[dict]:
    """超预算时归档最老的未归档消息生成 L1 摘要，替代裸截断。

    每轮归档一批（summary_batch_size 条最老消息）→ 重新提取 → 重算
    token，直到满足预算或触发停止条件：
    - 剩余未归档消息不足一批（无法继续压缩）
    - 摘要生成失败（AI 不可用，交回上层兜底截断）
    - 达到 MAX_COMPRESS_ROUNDS 上限
    """
    batch_size = Settings.get_int("summary_batch_size")
    context = _extract_all(friend_id)
    for _ in range(MAX_COMPRESS_ROUNDS):
        msgs = MessageRepository.get_unarchived(friend_id)
        if len(msgs) < batch_size:
            break  # 不够一批，无法继续归档
        try:
            summarizer.generate_batch_summary(friend_id, msgs[:batch_size])
        except summarizer.SummaryGenerationError as e:
            logger.warning("token 触发归档失败，回退截断 friend_id=%s：%s",
                           friend_id, e)
            break
        context = _extract_all(friend_id)
        if _total_tokens(context) <= max_tokens:
            break
    return context
