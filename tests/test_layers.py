# tests/test_layers.py
import pytest
from shadowtalk.core.layers import l3, l2, l1, l0
from shadowtalk.data.repositories import (
    FriendRepository, MessageRepository, SummaryRepository
)


class TestLayers:
    def test_l3_returns_persona(self):
        fid = FriendRepository.insert("好友", "", "你是一个热情的助手")
        result = l3.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L3"
        assert "热情的助手" in result[0]["content"]

    def test_l3_empty_persona(self):
        fid = FriendRepository.insert("好友", "", "")
        result = l3.extract(fid)
        assert len(result) == 1
        # 即使无人设，也会注入真人回复说明（帮助 AI 区分本人与用户）
        assert "[名字]" in result[0]["content"]

    def test_l2_returns_high_level(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_high_level_summary(fid, "高阶摘要内容")
        result = l2.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L2"
        assert result[0]["content"] == "高阶摘要内容"

    def test_l2_empty(self):
        fid = FriendRepository.insert("好友", "", "")
        result = l2.extract(fid)
        assert len(result) == 0

    def test_l1_returns_valid_summaries(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_batch_summary(fid, "批次摘要", 1, 30)
        result = l1.extract(fid)
        assert len(result) == 1
        assert result[0]["layer"] == "L1"
        assert result[0]["content"] == "批次摘要"

    def test_l1_excludes_expired(self):
        fid = FriendRepository.insert("好友", "", "")
        from shadowtalk.data.database import Database
        conn = Database.get_connection()
        conn.execute(
            "INSERT INTO batch_summary "
            "(friend_id, content, start_round, end_round, create_time) "
            "VALUES (?, ?, ?, ?, datetime('now', '-40 days'))",
            (fid, "过期摘要", 1, 30)
        )
        conn.commit()
        result = l1.extract(fid)
        assert len(result) == 0

    def test_l0_returns_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "你好", 1)
        MessageRepository.insert(fid, "ai", "你好！", 1)
        result = l0.extract(fid)
        assert len(result) == 2
        assert all(m["layer"] == "L0" for m in result)

    def test_l0_excludes_archived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息", 1)
        msgs = MessageRepository.get_unarchived(fid)
        MessageRepository.mark_archived([msgs[0]["id"]])
        result = l0.extract(fid)
        assert len(result) == 0

    def test_l3_injects_work_dir(self):
        fid = FriendRepository.insert("秘书", "", "", work_dir="D:/novel/project1")
        result = l3.extract(fid)
        assert len(result) == 1
        assert "D:/novel/project1" in result[0]["content"]
        assert "工作目录" in result[0]["content"]

    def test_l3_empty_work_dir_no_injection(self):
        fid = FriendRepository.insert("秘书", "", "")
        result = l3.extract(fid)
        assert "工作目录" not in result[0]["content"]
