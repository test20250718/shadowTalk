# shadowtalk/core/prompt_logger.py
"""
提示词日志记录器

每次 AI 对话时，将完整的上下文组成（L0-L3）写入日志文件，
方便调试提示词是否正确组装。

日志目录结构：
  logs/chat_prompts/
  └── {friend_name}_{friend_id}/
      └── {YYYY-MM-DD_HH-MM-SS}.log

注意：LOG_BASE_DIR 在模块 import 时按 get_base_dir() 解析一次——
开发模式（非 frozen）= 当前工作目录 cwd；打包模式（frozen）= exe 所在目录。
因此从其他目录运行脚本/测试时，提示词日志会写到该目录下的
logs/chat_prompts/，而非项目根的 logs/chat_prompts/。
"""
import logging
import os
import datetime
from typing import Optional

from shadowtalk.core.token_budget import estimate_tokens
from shadowtalk.config.paths import get_base_dir


logger = logging.getLogger(__name__)


# 日志根目录
LOG_BASE_DIR = get_base_dir() / "logs" / "chat_prompts"


def _get_log_folder(friend_name: str, friend_id: int) -> str:
    """获取某个好友的日志文件夹路径，不存在则创建"""
    folder = os.path.join(LOG_BASE_DIR, f"{friend_name}_{friend_id}")
    os.makedirs(folder, exist_ok=True)
    return folder


def _format_layer_section(layer_name: str, messages: list[dict]) -> str:
    """格式化某一层的消息为可读文本"""
    lines = []
    if not messages:
        lines.append(f"  （无）")
        return "\n".join(lines)

    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        tokens = estimate_tokens(content)
        # 截断过长内容以便阅读
        display_content = content[:500] + "..." if len(content) > 500 else content
        # 将换行替换为 \n 显示，避免日志格式混乱
        display_content = display_content.replace("\n", "\\n")
        lines.append(f"  [{i}] role={role} tokens≈{tokens}")
        lines.append(f"      {display_content}")

    return "\n".join(lines)


def log_conversation(
    friend_name: str,
    friend_id: int,
    context: list[dict],
    user_message: str,
    ai_reply: str,
) -> Optional[str]:
    """
    记录一次完整的对话上下文到日志文件。

    Args:
        friend_name: 好友名称
        friend_id: 好友 ID
        context: build_context() 返回的完整上下文（含 layer 标记）
        user_message: 用户发送的消息
        ai_reply: AI 的回复

    Returns:
        日志文件路径，失败返回 None
    """
    try:
        folder = _get_log_folder(friend_name, friend_id)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join(folder, f"{timestamp}.log")

        # 按层分组
        l3_msgs = [m for m in context if m.get("layer") == "L3"]
        l2_msgs = [m for m in context if m.get("layer") == "L2"]
        l1_msgs = [m for m in context if m.get("layer") == "L1"]
        l0_msgs = [m for m in context if m.get("layer") == "L0"]

        # 统计 token
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in context)
        l0_tokens = sum(estimate_tokens(m.get("content", "")) for m in l0_msgs)
        l1_tokens = sum(estimate_tokens(m.get("content", "")) for m in l1_msgs)
        l2_tokens = sum(estimate_tokens(m.get("content", "")) for m in l2_msgs)
        l3_tokens = sum(estimate_tokens(m.get("content", "")) for m in l3_msgs)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = []
        lines.append("=" * 70)
        lines.append(f"ShadowTalk 提示词日志")
        lines.append(f"时间: {now_str}")
        lines.append(f"好友: {friend_name} (ID: {friend_id})")
        lines.append("=" * 70)
        lines.append("")

        # ── 概览 ──
        lines.append("【概览】")
        lines.append(f"  总消息数: {len(context)}")
        lines.append(f"  总 Token 估算: {total_tokens}")
        lines.append(f"  L3 (人设): {len(l3_msgs)} 条, ≈{l3_tokens} tokens")
        lines.append(f"  L2 (高层摘要): {len(l2_msgs)} 条, ≈{l2_tokens} tokens")
        lines.append(f"  L1 (批次摘要): {len(l1_msgs)} 条, ≈{l1_tokens} tokens")
        lines.append(f"  L0 (原文): {len(l0_msgs)} 条, ≈{l0_tokens} tokens")
        lines.append("")

        # ── L3: 人设 ──
        lines.append("-" * 70)
        lines.append(f"【L3 - 人设 Persona】 ({len(l3_msgs)} 条)")
        lines.append("-" * 70)
        lines.append(_format_layer_section("L3", l3_msgs))
        lines.append("")

        # ── L2: 高层摘要 ──
        lines.append("-" * 70)
        lines.append(f"【L2 - 高层摘要 High-Level Summary】 ({len(l2_msgs)} 条)")
        lines.append("-" * 70)
        lines.append(_format_layer_section("L2", l2_msgs))
        lines.append("")

        # ── L1: 批次摘要 ──
        lines.append("-" * 70)
        lines.append(f"【L1 - 批次摘要 Batch Summary】 ({len(l1_msgs)} 条)")
        lines.append("-" * 70)
        lines.append(_format_layer_section("L1", l1_msgs))
        lines.append("")

        # ── L0: 原文消息 ──
        lines.append("-" * 70)
        lines.append(f"【L0 - 原文 Raw Messages】 ({len(l0_msgs)} 条)")
        lines.append("-" * 70)
        lines.append(_format_layer_section("L0", l0_msgs))
        lines.append("")

        # ── 用户消息 ──
        lines.append("-" * 70)
        lines.append("【用户消息 User Message】")
        lines.append("-" * 70)
        lines.append(f"  tokens≈{estimate_tokens(user_message)}")
        lines.append(f"  {user_message[:500]}")
        lines.append("")

        # ── AI 回复 ──
        lines.append("-" * 70)
        lines.append("【AI 回复 AI Response】")
        lines.append("-" * 70)
        lines.append(f"  tokens≈{estimate_tokens(ai_reply)}")
        display_reply = ai_reply[:1000] + "..." if len(ai_reply) > 1000 else ai_reply
        lines.append(f"  {display_reply}")
        lines.append("")

        lines.append("=" * 70)
        lines.append("日志结束")
        lines.append("")

        # 写入文件（UTF-8 编码确保中文正常）
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info("提示词日志已写入: %s", filepath)
        return filepath

    except Exception as e:
        # 日志功能不应影响主流程，出错时静默忽略（可打印到控制台）
        print(f"[PromptLogger] 写入日志失败: {e}")
        return None
