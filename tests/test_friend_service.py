import os
import tempfile
from shadowtalk.core.friend_service import FriendService, resolve_avatar
from shadowtalk.data.repositories import FriendRepository, MessageRepository


def test_create_friend():
    fid = FriendService.create("测试", "备注", "人设", "")
    friend = FriendRepository.get_by_id(fid)
    assert friend["name"] == "测试"
    assert friend["remark"] == "备注"

def test_create_with_avatar():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake_image_data")
        avatar_path = f.name

    try:
        fid = FriendService.create("有头像", "", "", avatar_path)
        friend = FriendRepository.get_by_id(fid)
        assert friend["avatar_path"] != ""
        assert os.path.exists(friend["avatar_path"])
    finally:
        os.unlink(avatar_path)

def test_delete_with_cascade():
    fid = FriendService.create("待删除", "", "", "")
    MessageRepository.insert(fid, "user", "消息", 1)

    FriendService.delete(fid, keep_messages=False)
    assert FriendRepository.get_by_id(fid) is None
    msgs = MessageRepository.get_unarchived(fid)
    assert len(msgs) == 0


def test_create_passes_voice():
    fid = FriendService.create(name="v", remark="", system_prompt="",
                               voice="zh-CN-YunxiNeural")
    row = FriendRepository.get_by_id(fid)
    assert row["voice"] == "zh-CN-YunxiNeural"


def _make_png(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_update_avatar_replaces_same_extension(tmp_path):
    """同扩展名换头像：覆盖同一路径，新图生效（曾把刚复制的新头像误删）"""
    a1 = _make_png(tmp_path, "old.png", b"OLD_AVATAR")
    fid = FriendService.create("有头像", "", "", a1)
    friend = FriendRepository.get_by_id(fid)
    old_path = friend["avatar_path"]
    assert os.path.exists(old_path)

    a2 = _make_png(tmp_path, "new.png", b"NEW_AVATAR")
    FriendService.update_avatar(fid, a2)

    row = FriendRepository.get_by_id(fid)
    assert row["avatar_path"] == old_path  # 同扩展名 → 覆盖同一文件
    assert open(row["avatar_path"], "rb").read() == b"NEW_AVATAR"  # 内容是新的
    assert os.path.exists(row["avatar_path"])


def test_update_avatar_different_extension(tmp_path):
    """不同扩展名换头像：jpg → png，新文件生效"""
    a1 = _make_png(tmp_path, "old.jpg", b"JPG_AVATAR")
    fid = FriendService.create("有头像", "", "", a1)
    old_path = FriendRepository.get_by_id(fid)["avatar_path"]

    a2 = _make_png(tmp_path, "new.png", b"PNG_AVATAR")
    FriendService.update_avatar(fid, a2)

    row = FriendRepository.get_by_id(fid)
    assert open(row["avatar_path"], "rb").read() == b"PNG_AVATAR"
    assert not os.path.exists(old_path)


# ── 头像迁移容错（用户报告：换新版/搬家后头像全丢，库里存绝对路径）──

def test_resolve_avatar_keeps_existing_path(tmp_path):
    """文件存在 → 原样返回"""
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert resolve_avatar(str(img)) == str(img)


def test_resolve_avatar_falls_back_to_app_dir(tmp_path, monkeypatch):
    """绝对路径失效 → 按应用头像目录 <id>/avatar.ext 回退"""
    old = tmp_path / "old_location" / "6" / "avatar.png"   # 不存在
    new = tmp_path / "app" / "data" / "avatars" / "6" / "avatar.png"
    new.parent.mkdir(parents=True)
    new.write_bytes(b"img")

    monkeypatch.setattr(FriendService, "AVATAR_DIR",
                        str(tmp_path / "app" / "data" / "avatars"))
    assert resolve_avatar(str(old)) == str(new)


def test_resolve_avatar_missing_everywhere_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(FriendService, "AVATAR_DIR",
                        str(tmp_path / "app" / "data" / "avatars"))
    assert resolve_avatar(str(tmp_path / "nope" / "1" / "avatar.png")) == ""
    assert resolve_avatar("") == ""
