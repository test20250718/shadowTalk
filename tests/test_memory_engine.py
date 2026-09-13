# tests/test_memory_engine.py
from unittest.mock import MagicMock, patch
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


def test_build_context_no_duplicate_user_message():
    """回归（用户报告 AI 说"连说两遍"）：调用方先落库再 build_context，
    L0 已含最新用户消息时不得再 append 一次（模型此前每条都看到两遍）"""
    fid = FriendRepository.insert("好友", "", "人设")
    # 模拟 _on_message_sent 的真实顺序：先 insert，后 build
    MessageRepository.insert(fid, "user", "周日好", 1)

    result = build_context(fid, "周日好")

    same = [m for m in result
            if m["role"] == "user" and m["content"] == "周日好"]
    assert len(same) == 1, "最新用户消息在上下文中出现两次"
    assert result[-1]["content"] == "周日好"  # 且仍是最后一条


def test_build_context_appends_when_message_not_in_db():
    """消息未落库的调用方式（先构建后落库）仍追加一次"""
    fid = FriendRepository.insert("好友", "", "人设")
    MessageRepository.insert(fid, "user", "旧消息", 1)

    result = build_context(fid, "全新消息")

    same = [m for m in result
            if m["role"] == "user" and m["content"] == "全新消息"]
    assert len(same) == 1
    assert result[-1]["content"] == "全新消息"

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


def test_build_context_compresses_instead_of_trimming():
    """超预算时先归档压缩（生成 L1 摘要），不裸截断。

    回归（用户反馈"真空区"）：Token 裁剪先于轮次归档触发时，
    最老的几轮既没被摘要、也不在上下文里，凭空丢失。
    现在超预算 → 归档最老一批成 L1 → 全部剩余消息仍在上下文。
    """
    fid = FriendRepository.insert("好友", "", "人设")
    for i in range(40):  # 40 条 > batch_size 30，具备压缩条件
        MessageRepository.insert(fid, "user", "x" * 200, i + 1)
    Settings.set("max_context_tokens", "1500")

    mock_ai = MagicMock()
    mock_ai.chat.return_value = "摘要" * 50  # 100 字

    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = build_context(fid, "新消息")
    Settings.set("max_context_tokens", "8000")

    # 生成了 L1 摘要
    assert "L1" in [m.get("layer") for m in result]

    # 全部未归档消息都在上下文里（没有裸截断）
    n_unarchived = len(MessageRepository.get_unarchived(fid))
    n_l0 = sum(1 for m in result if m.get("layer") == "L0")
    assert n_l0 == n_unarchived

    # 且总量在预算内
    total = sum(len(m["content"]) for m in result) // 2
    assert total <= 1500


def test_build_context_falls_back_to_trim_when_summary_fails():
    """摘要生成失败（AI 不可用）时回退截断，保证本次请求能发出"""
    fid = FriendRepository.insert("好友", "", "人设")
    for i in range(40):
        MessageRepository.insert(fid, "user", "x" * 200, i + 1)
    Settings.set("max_context_tokens", "1500")

    mock_ai = MagicMock()
    mock_ai.chat.side_effect = Exception("AI 不可用")

    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = build_context(fid, "新消息")
    Settings.set("max_context_tokens", "8000")

    # 没有生成任何摘要（原文保住了，下次再压缩）
    assert "L1" not in [m.get("layer") for m in result]

    # 回退截断后上下文在预算内
    total = sum(len(m["content"]) for m in result) // 2
    assert total <= 1500
