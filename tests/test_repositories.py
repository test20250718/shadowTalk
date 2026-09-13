import pytest
from shadowtalk.data.repositories import (
    MessageRepository, SummaryRepository, FriendRepository
)


class TestFriendRepository:
    def test_insert_and_get(self):
        fid = FriendRepository.insert("测试好友", "备注", "你是一个助手")
        friend = FriendRepository.get_by_id(fid)
        assert friend["name"] == "测试好友"
        assert friend["remark"] == "备注"

    def test_get_all(self):
        FriendRepository.insert("好友A", "", "")
        FriendRepository.insert("好友B", "", "")
        all_friends = FriendRepository.get_all()
        assert len(all_friends) >= 2

    def test_update(self):
        fid = FriendRepository.insert("原名", "", "")
        FriendRepository.update(fid, name="新名", remark="新备注")
        friend = FriendRepository.get_by_id(fid)
        assert friend["name"] == "新名"
        assert friend["remark"] == "新备注"

    def test_delete_cascade(self):
        fid = FriendRepository.insert("待删除", "", "")
        MessageRepository.insert(fid, "user", "hello", 1)
        FriendRepository.delete(fid)
        assert FriendRepository.get_by_id(fid) is None
        msgs = MessageRepository.get_unarchived(fid)
        assert len(msgs) == 0

    def test_insert_with_work_dir(self):
        fid = FriendRepository.insert("写手", "", "", work_dir="D:/novel/project1")
        friend = FriendRepository.get_by_id(fid)
        assert friend["work_dir"] == "D:/novel/project1"

    def test_update_work_dir(self):
        fid = FriendRepository.insert("写手", "", "")
        FriendRepository.update(fid, work_dir="E:/books")
        friend = FriendRepository.get_by_id(fid)
        assert friend["work_dir"] == "E:/books"


class TestMessageRepository:
    def test_insert_and_get_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "你好", 1)
        MessageRepository.insert(fid, "ai", "你好！", 1)
        msgs = MessageRepository.get_unarchived(fid)
        assert len(msgs) == 2

    def test_count_unarchived_rounds(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息1", 1)
        MessageRepository.insert(fid, "ai", "回复1", 1)
        MessageRepository.insert(fid, "user", "消息2", 2)
        count = MessageRepository.count_unarchived_rounds(fid)
        assert count == 2

    def test_mark_archived(self):
        fid = FriendRepository.insert("好友", "", "")
        MessageRepository.insert(fid, "user", "消息", 1)
        msgs = MessageRepository.get_unarchived(fid)
        MessageRepository.mark_archived([msgs[0]["id"]])
        msgs_after = MessageRepository.get_unarchived(fid)
        assert len(msgs_after) == 0

    def test_get_oldest_unarchived(self):
        fid = FriendRepository.insert("好友", "", "")
        for i in range(5):
            MessageRepository.insert(fid, "user", f"消息{i}", i + 1)
        oldest = MessageRepository.get_oldest_unarchived(fid, 2)
        assert len(oldest) == 2
        assert oldest[0]["round_index"] == 1


def test_friend_insert_and_update_voice():
    fid = FriendRepository.insert(
        name="测试好友", remark="", system_prompt="",
        voice="zh-CN-YunxiNeural"
    )
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-YunxiNeural"
    FriendRepository.update(fid, voice="zh-CN-XiaoyiNeural")
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-XiaoyiNeural"

def test_message_insert_returns_id():
    fid = FriendRepository.insert(name="m", remark="", system_prompt="")
    mid = MessageRepository.insert(fid, "ai", "你好", 1)
    assert isinstance(mid, int) and mid > 0


def test_get_last_per_friend():
    """每个好友返回其最后一条消息（会话列表预览数据源）"""
    f1 = FriendRepository.insert("好友A", "", "")
    f2 = FriendRepository.insert("好友B", "", "")
    MessageRepository.insert(f1, "user", "A第一条", 1)
    MessageRepository.insert(f1, "ai", "A最后一条", 1)
    MessageRepository.insert(f2, "user", "B最后一条", 1)
    last = MessageRepository.get_last_per_friend()
    assert last[f1][0] == "A最后一条"
    assert last[f2][0] == "B最后一条"


def test_get_last_per_friend_skips_archived():
    """归档后的消息不参与预览（旧摘要流程归档的消息不显示）"""
    f = FriendRepository.insert("好友", "", "")
    MessageRepository.insert(f, "user", "旧消息", 1)
    mid = MessageRepository.insert(f, "user", "已归档消息", 2)
    MessageRepository.mark_archived([mid])
    last = MessageRepository.get_last_per_friend()
    assert last[f][0] == "旧消息"


class TestSummaryRepository:
    def test_save_and_get_valid(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_batch_summary(fid, "摘要内容", 1, 30)
        valid = SummaryRepository.get_valid_summaries(fid, 30)
        assert len(valid) == 1
        assert valid[0]["content"] == "摘要内容"

    def test_save_high_level(self):
        fid = FriendRepository.insert("好友", "", "")
        SummaryRepository.save_high_level_summary(fid, "高阶摘要")
        all_l2 = SummaryRepository.get_all_high_level_summaries(fid)
        assert len(all_l2) == 1
        assert all_l2[0]["content"] == "高阶摘要"


def test_get_unarchived_limit_returns_latest():
    """界面渲染只取最近 N 条（防超长历史一次全量加载），顺序保持升序"""
    from shadowtalk.data.repositories import FriendRepository, MessageRepository
    fid = FriendRepository.insert("限载", "", "")
    for i in range(1, 11):
        MessageRepository.insert(fid, "user", f"msg{i}", i)

    rows = MessageRepository.get_unarchived(fid, limit=3)

    assert [r["content"] for r in rows] == ["msg8", "msg9", "msg10"]
    # 不传 limit 仍取全量（记忆引擎依赖）
    assert len(MessageRepository.get_unarchived(fid)) == 10
