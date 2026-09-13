# shadowtalk/core/room_service.py
"""沉浸式房间服务：房间数据读取、背景图管理、场景化上下文构建。

对话记录记到好友名下（设计决策 2026-08-16）：房间只是"场景皮肤"，
记忆引擎与主线聊天共享，她在房间里聊过的事主线也记得。
"""
import shutil
import os
from pathlib import Path

from shadowtalk.config.paths import get_base_dir
from shadowtalk.core.memory_engine import build_context
from shadowtalk.data.database import Database


def rooms_dir() -> Path:
    """房间资源目录（背景图存放处），不存在则创建"""
    d = get_base_dir() / "data" / "rooms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_room(key: str) -> dict | None:
    """按 key 读取房间（dict），无则 None"""
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT * FROM rooms WHERE key=?", (key,)
    ).fetchone()
    return dict(row) if row else None


def get_room_bg(key: str, friend_id: int) -> str:
    """背景图解析：只认该好友在此房间的专属图，未设过返回空串
    （界面显示占位渐变+换图提示）。

    用户要求"每个 AI 记住自己的咖啡馆图片"——图与 (房间, 好友) 绑定；
    不回落共享默认图（旧共享方案残留的默认图会串到新好友头上）。
    """
    conn = Database.get_connection()
    row = conn.execute(
        "SELECT bg_path FROM room_backgrounds WHERE room_key=? AND friend_id=?",
        (key, friend_id),
    ).fetchone()
    if row and row["bg_path"] and os.path.isfile(row["bg_path"]):
        return row["bg_path"]
    return ""


def save_room_bg(key: str, source_path: str, friend_id: int | None = None) -> str:
    """把用户选的背景图复制进 data/rooms/ 并记录归属。

    friend_id 给定 → 存为该好友在此房间的专属图（<key>_<fid>.<ext>，
    room_backgrounds 表）；None → 存为房间默认图（<key>.<ext>，rooms 表）。
    返回新路径；源图缺失/复制失败返回空串（调用方保持原图不变）。
    """
    if not source_path or not os.path.isfile(source_path):
        return ""
    ext = os.path.splitext(source_path)[1] or ".jpg"
    stem = f"{key}_{friend_id}" if friend_id is not None else key
    dst = rooms_dir() / f"{stem}{ext}"
    # 清掉该归属旧扩展名的图（换 jpg→png 时避免两张并存）
    for old in rooms_dir().glob(f"{stem}.*"):
        if old != dst:
            try:
                old.unlink()
            except OSError:
                pass
    try:
        shutil.copy2(source_path, dst)
    except OSError:
        return ""
    with Database.transaction() as conn:
        if friend_id is not None:
            conn.execute(
                "INSERT OR REPLACE INTO room_backgrounds "
                "(room_key, friend_id, bg_path) VALUES (?, ?, ?)",
                (key, friend_id, str(dst)))
        else:
            conn.execute("UPDATE rooms SET bg_path=? WHERE key=?",
                         (str(dst), key))
    return str(dst)


def build_room_context(friend_id: int, user_message: str,
                       scene_prompt: str) -> list[dict]:
    """构建房间场景化上下文：记忆层照旧，场景人设插在 L3 人设块之后。

    场景在前定义"此刻在哪、什么氛围"，人设紧随定义"她是谁"——
    两条 system 一起生效（场景是临时的语气覆盖，人格仍是原人设）。
    """
    context = build_context(friend_id, user_message)
    if not scene_prompt:
        return context
    insert_at = 0
    for i, m in enumerate(context):
        if m.get("layer") == "L3":
            insert_at = i + 1
    context.insert(insert_at,
                   {"role": "system", "content": scene_prompt, "layer": "L3"})
    return context
