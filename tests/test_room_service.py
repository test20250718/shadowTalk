"""沉浸式房间服务测试（第一期：咖啡馆）"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from shadowtalk.core import room_service
from shadowtalk.core.room_service import (
    build_room_context, get_room, get_room_bg, rooms_dir, save_room_bg,
)
from shadowtalk.data.database import Database
from shadowtalk.data.repositories import FriendRepository, MessageRepository

app = QApplication.instance() or QApplication(sys.argv)


def test_cafe_room_seeded_on_migration():
    """启动迁移自动播种咖啡馆（含场景人设），重复迁移不覆盖"""
    Database.get_connection()
    room = get_room("cafe")
    assert room is not None
    assert room["name"] == "咖啡馆"
    assert "咖啡馆" in room["scene_prompt"]
    assert "口语化" in room["scene_prompt"]


def test_get_room_missing_key_returns_none():
    assert get_room("no-such-room") is None


def test_save_room_bg_copies_and_updates_db(tmp_path):
    """房间默认图：图复制进 data/rooms/<key>.<ext>，库路径更新"""
    src = tmp_path / "cafe_new.png"
    src.write_bytes(b"IMGDATA")

    path = save_room_bg("cafe", str(src))

    assert path and Path(path).exists()
    assert Path(path).parent == rooms_dir()
    assert get_room("cafe")["bg_path"] == path


def test_room_bg_per_friend(tmp_path):
    """每个好友记住自己的咖啡馆图（用户报告 bug：换人图片不变）：
    按好友存图互不覆盖；未设过的好友不显示任何人的图（占位渐变）"""
    f1 = FriendRepository.insert("小影", "", "")
    f2 = FriendRepository.insert("阿云", "", "")

    img1 = tmp_path / "cafe1.png"; img1.write_bytes(b"IMG1")
    img2 = tmp_path / "cafe2.jpg"; img2.write_bytes(b"IMG2")

    p1 = save_room_bg("cafe", str(img1), friend_id=f1)
    p2 = save_room_bg("cafe", str(img2), friend_id=f2)

    assert get_room_bg("cafe", f1) == p1
    assert get_room_bg("cafe", f2) == p2
    assert open(p1, "rb").read() == b"IMG1"
    assert open(p2, "rb").read() == b"IMG2"
    # 未设专属图的好友 → 空（哪怕 rooms.bg_path 有旧共享图也不串）
    save_room_bg("cafe", str(img1), None)   # 旧共享方案写入的默认图
    assert get_room_bg("cafe", 999999) == ""


def test_save_room_bg_bad_source_keeps_old(tmp_path):
    """源图缺失：返回空串且不改动库里的路径"""
    old = get_room("cafe")["bg_path"]
    assert save_room_bg("cafe", str(tmp_path / "nope.png")) == ""
    assert get_room("cafe")["bg_path"] == old


def test_build_room_context_injects_scene_after_persona():
    """场景人设插在 L3 人设块之后；记忆层结构不变"""
    fid = FriendRepository.insert("小影", "", "你是小影")
    MessageRepository.insert(fid, "user", "你好", 1)

    scene = "此刻你在咖啡馆。"
    ctx = build_room_context(fid, "喝点什么？", scene)

    # 顺序：人设 L3 → 场景 L3 → … → user
    assert ctx[0]["role"] == "system"      # 人设
    assert "小影" in ctx[0]["content"]
    assert ctx[1]["role"] == "system"      # 场景
    assert ctx[1]["content"] == scene
    assert ctx[-1]["role"] == "user" and ctx[-1]["content"] == "喝点什么？"


def test_build_room_context_empty_scene_unchanged():
    """空场景人设：上下文与主线完全一致（不多插消息）"""
    fid = FriendRepository.insert("小影", "", "你是小影")
    ctx = build_room_context(fid, "你好", "")
    assert not any("咖啡馆" in (m.get("content") or "") for m in ctx)
