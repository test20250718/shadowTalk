# tests/test_summarizer.py
import pytest
from unittest.mock import MagicMock, patch
from shadowtalk.core.summarizer import (
    generate_batch_summary, generate_high_level_summary,
    SummaryGenerationError,
)
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)


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


def test_generate_batch_summary_keeps_full_text_over_target():
    """超目标字数也保留全文，绝不截断。

    回归（用户反馈）：30 条消息压缩后被硬截成 50 字还带"[摘要截断]"，
    记忆残缺。现在目标字数只是软引导。
    """
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    msgs = MessageRepository.get_unarchived(fid)

    long_summary = "这" * 350  # 远超 200 目标
    mock_ai = MagicMock()
    mock_ai.chat.return_value = long_summary

    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        result = generate_batch_summary(fid, msgs)

    assert result == long_summary
    assert "摘要截断" not in result
    assert MessageRepository.count_unarchived_rounds(fid) == 0


def test_generate_batch_summary_failure_raises_and_keeps_raw():
    """AI 不可用时抛 SummaryGenerationError，不落库、不归档原文。

    回归：此前失败会写入"摘要生成失败"占位符并标记原文已归档，
    等于用垃圾顶替了真实记忆。
    """
    fid = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(fid, "user", "你好", 1)
    msgs = MessageRepository.get_unarchived(fid)

    mock_ai = MagicMock()
    mock_ai.chat.side_effect = Exception("网络断开")

    with patch("shadowtalk.core.summarizer.get_ai_client", return_value=mock_ai):
        with pytest.raises(SummaryGenerationError):
            generate_batch_summary(fid, msgs)

    # 原文未被归档、没有摘要落库
    assert MessageRepository.count_unarchived_rounds(fid) == 1
    assert len(SummaryRepository.get_valid_summaries(fid, 30)) == 0


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
