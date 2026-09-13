"""MainWindow 归属校验测试

回归保护：切换/删除好友后，在途旧 AIWorker 的回复不得写入当前好友
（历史 bug：_on_ai_reply 用 current_friend_id 落库，数据串好友）。
"""
import logging
import os
import sys
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from shadowtalk.ui.main_window import MainWindow
from shadowtalk.ui.threads.ai_worker import AIWorker
from shadowtalk.data.repositories import MessageRepository, FriendRepository
from shadowtalk.core.friend_service import FriendService

app = QApplication.instance() or QApplication(sys.argv)


def _make_worker(window, friend_id):
    worker = AIWorker(friend_id, "你好", ai_client=None, messages=[], work_dir="")
    worker.finished.connect(window._on_ai_reply)
    worker.failed.connect(window._on_ai_failed)
    window.ai_worker = worker
    return worker


def test_reply_lands_in_current_friend_when_not_switched():
    """正常路径回归保护：回复写入当前好友并入库"""
    a_id = FriendRepository.insert("儿子", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)

    _make_worker(window, a_id).finished.emit("正常回复")

    contents = [m["content"] for m in MessageRepository.get_unarchived(a_id)]
    assert contents == ["正常回复"]


def test_auto_play_triggered_when_enabled(monkeypatch):
    """回归：tts_auto_play=1 时 AI 回复到达必须触发自动朗读
    （用户报告：开启回复并朗读后没有起作用）"""
    from shadowtalk.config.settings import Settings
    a_id = FriendRepository.insert("朗读", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)

    calls = []
    monkeypatch.setattr(window.chat_area._player, "play",
                        lambda text, voice, msg_id: calls.append(text))

    Settings.set("tts_auto_play", "1")
    try:
        _make_worker(window, a_id).finished.emit("**加粗** 你好")
        assert calls == ["**加粗** 你好"], "自动朗读未触发"
    finally:
        Settings.set("tts_auto_play", "0")


class _FakeWorker(QObject):
    """中断测试桩：不启动真线程，记录 cancel 调用"""
    finished = Signal(str)
    failed = Signal(str)
    approval_requested = Signal(str, list, str)
    activity = Signal(str)

    def __init__(self):
        super().__init__()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def isRunning(self):
        return False

    def wait(self, ms):
        return True

    def start(self):
        pass


def test_ai_worker_cancel_noop_when_not_running(monkeypatch):
    """未启动的 worker 调 cancel() 无副作用（不 terminate）"""
    from shadowtalk.ui.threads.ai_worker import AIWorker
    w = AIWorker(1, "hi", ai_client=None, messages=[], work_dir="")
    terminated = []
    monkeypatch.setattr(w, "terminate", lambda: terminated.append(True))
    w.cancel()
    assert terminated == []


def test_new_message_cancels_previous_worker(monkeypatch):
    """回归：发新消息必须中断在途旧任务（用户：新信息直接中断
    前一个任务，可间接撤销卡死的任务）"""
    window = MainWindow()
    a_id = FriendRepository.insert("中断", "", "")
    window._on_friend_selected(a_id)

    old = _FakeWorker()
    old.finished.connect(window._on_ai_reply)
    window.ai_worker = old

    monkeypatch.setattr("shadowtalk.ui.main_window.AIWorker", _FakeWorker)
    window._on_message_sent("新消息")

    assert old.cancelled, "旧任务未被中断"
    assert window.ai_worker is not old

    # 旧 worker 信号已断开：其迟到回复不得进入当前对话
    old.finished.emit("旧任务的回复")
    contents = [m["content"] for m in MessageRepository.get_unarchived(a_id)]
    assert "旧任务的回复" not in contents
    assert "新消息" in contents


def test_stale_worker_reply_lands_in_original_friend():
    """切换好友后旧 worker 的回复写回原好友，不污染当前好友"""
    a_id = FriendRepository.insert("儿子", "", "")
    b_id = FriendRepository.insert("秘书", "", "")
    window = MainWindow()

    window._on_friend_selected(a_id)
    worker = _make_worker(window, a_id)

    # 用户切换到 B（clear_messages 已复位 loading）
    window._on_friend_selected(b_id)

    # 旧 worker 的回复此时到达
    worker.finished.emit("儿子回复")

    assert [m["content"] for m in MessageRepository.get_unarchived(a_id)] == ["儿子回复"]
    assert MessageRepository.get_unarchived(b_id) == []
    assert window.chat_area.message_list.count() == 0  # 未显示在当前视图


def test_stale_worker_failure_not_shown_in_current_view():
    """切换好友后旧 worker 的失败提示不显示在当前视图"""
    a_id = FriendRepository.insert("儿子", "", "")
    b_id = FriendRepository.insert("秘书", "", "")
    window = MainWindow()

    window._on_friend_selected(a_id)
    worker = _make_worker(window, a_id)
    window._on_friend_selected(b_id)

    worker.failed.emit("网络超时")

    assert window.chat_area.message_list.count() == 0


def test_stale_worker_reply_dropped_when_friend_deleted():
    """好友已删除时迟到的回复被丢弃，不插孤立消息"""
    a_id = FriendRepository.insert("儿子", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)
    worker = _make_worker(window, a_id)

    FriendService.delete(a_id, keep_messages=False)
    window.current_friend_id = None
    window.chat_area.clear_messages()

    worker.finished.emit("迟到的回复")

    assert MessageRepository.get_unarchived(a_id) == []
    assert window.chat_area.message_list.count() == 0


# ── 编辑好友：头像与属性持久化 ──

class _FakeDialog:
    """模拟 FriendDialog：exec 直接 Accepted，get_data 返回预设数据"""
    def __init__(self, data, *args, **kwargs):
        self._data = data

    def exec(self):
        return 1  # QDialog.Accepted

    def get_data(self):
        return self._data


def test_edit_friend_persists_all_fields(monkeypatch, tmp_path):
    """编辑好友：名称/备注/角色/工作目录/语音/头像全部落库"""
    import shadowtalk.ui.main_window as mw
    fid = FriendService.create("旧名", "旧备注", "旧人设", "", voice="")
    window = MainWindow()
    window._on_friend_selected(fid)

    img = tmp_path / "新头像.png"
    img.write_bytes(b"PNGDATA")

    monkeypatch.setattr(mw, "FriendDialog", lambda parent, friend: _FakeDialog({
        "name": "新名", "remark": "新备注", "system_prompt": "新人设",
        "ai_role": "老师", "user_role": "学生", "work_dir": "D:/novel/p2",
        "avatar_path": str(img), "voice": "zh-CN-YunxiNeural",
    }))
    window._on_edit_friend(fid)

    row = FriendRepository.get_by_id(fid)
    assert row["name"] == "新名"
    assert row["remark"] == "新备注"
    assert row["system_prompt"] == "新人设"
    assert row["ai_role"] == "老师"
    assert row["user_role"] == "学生"
    assert row["work_dir"] == "D:/novel/p2"
    assert row["voice"] == "zh-CN-YunxiNeural"
    # 头像已复制进应用目录且文件存在
    assert row["avatar_path"]
    assert os.path.exists(row["avatar_path"])
    # 正在聊天 → 头部同步刷新
    assert window.chat_area._avatar_name == "新备注"  # 显示名：备注优先


def test_edit_friend_keeps_avatar_when_unchanged(monkeypatch):
    """未换头像：数据库 avatar_path 保持不变"""
    import shadowtalk.ui.main_window as mw
    fid = FriendService.create("旧名", "", "", "")
    row = FriendRepository.get_by_id(fid)
    old_path = row["avatar_path"]  # 空
    window = MainWindow()
    window._on_friend_selected(fid)

    monkeypatch.setattr(mw, "FriendDialog", lambda parent, friend: _FakeDialog({
        "name": "新名", "remark": "", "system_prompt": "",
        "ai_role": "", "user_role": "", "work_dir": "",
        "avatar_path": old_path, "voice": "",
    }))
    window._on_edit_friend(fid)

    assert FriendRepository.get_by_id(fid)["avatar_path"] == old_path


# ── I1：日志归因——回复/失败日志必须带好友 id（含写回原好友场景）──

def test_ai_reply_log_attributes_friend_id(caplog):
    """AI 回复日志带好友 id 归因（当前好友正常路径）"""
    a_id = FriendRepository.insert("儿子", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)

    with caplog.at_level(logging.INFO, logger="shadowtalk"):
        _make_worker(window, a_id).finished.emit("正常回复")

    assert any(
        f"AI 回复: 好友_id={a_id} 长度=4" in r.message
        for r in caplog.records)


def test_stale_worker_reply_logs_original_friend(caplog):
    """切换好友后写回原好友的回复，日志归因原好友 id（守卫之前记录）"""
    a_id = FriendRepository.insert("儿子", "", "")
    b_id = FriendRepository.insert("秘书", "", "")
    window = MainWindow()

    window._on_friend_selected(a_id)
    worker = _make_worker(window, a_id)
    window._on_friend_selected(b_id)

    with caplog.at_level(logging.INFO, logger="shadowtalk"):
        worker.finished.emit("儿子回复")

    assert any(
        f"AI 回复: 好友_id={a_id} 长度=4" in r.message
        for r in caplog.records)


def test_ai_failed_log_attributes_friend_id(caplog):
    """AI 回复失败日志带好友 id 归因"""
    a_id = FriendRepository.insert("儿子", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)

    with caplog.at_level(logging.ERROR, logger="shadowtalk"):
        _make_worker(window, a_id).failed.emit("网络超时")

    assert any(
        f"AI 回复失败: 好友_id={a_id} 错误=网络超时" in r.message
        for r in caplog.records)


def test_apply_theme_switches_qss_and_rebuilds_lists():
    """主题切换后：全局 QSS 变深色；容器样式重设；好友列表与消息列表重建（取新主题色）"""
    from PySide6.QtWidgets import QLabel
    from shadowtalk.ui import theme
    a_id = FriendRepository.insert("儿子", "", "")
    MessageRepository.insert(a_id, "user", "你好", 1)
    window = MainWindow()
    window._on_friend_selected(a_id)
    assert window.current_friend_id == a_id

    theme.set_current("dark")
    window._apply_theme()

    assert "#26262B" in window.styleSheet()      # 全局 QSS 已切 DARK.SURFACE
    assert a_id in window.friend_list._friend_items   # 好友列表已重建
    # 消息已重载（clear+reload）：1 条消息 + 1 条"今天"分隔线 = 2 项
    assert window.chat_area.message_list.count() == 2
    # 容器样式跟随主题（restyle 后按 DARK 取色，而非构造时冻结的浅色）
    assert "#1A1A1E" in window.chat_area.styleSheet()      # DARK.BG
    assert "#26262B" in window.friend_list.styleSheet()    # DARK.SURFACE
    # 会话项名称标签取深色文字（DARK.FG）；名称标签为加粗 14pt 的那一个
    item_widget = window.friend_list._friend_items[a_id]
    name_label = next(l for l in item_widget.findChildren(QLabel) if l.font().bold())
    assert "#E8E6E1" in name_label.styleSheet()
    theme.set_current("light")  # 复位


def test_chat_area_empty_without_selection():
    """未选中好友：聊天区空白（微信风格）；选中好友后恢复"""
    window = MainWindow()
    # 启动时无选中好友 → 头部与输入区隐藏
    assert window.chat_area._header.isHidden()
    assert window.chat_area._composer_wrap.isHidden()

    a_id = FriendRepository.insert("儿子", "", "")
    window._on_friend_selected(a_id)
    assert not window.chat_area._header.isHidden()
    assert not window.chat_area._composer_wrap.isHidden()
    assert not window.chat_area.message_list.isHidden()


def test_statusbar_shows_ai_disclaimer():
    """状态栏常驻 AI 输出声明（右侧，不占用瞬时消息区）"""
    from PySide6.QtWidgets import QLabel
    window = MainWindow()
    texts = [l.text() for l in window.status_bar.findChildren(QLabel)]
    assert any("AI 输出仅供参考" in t and "切勿直接采信" in t for t in texts), \
        "状态栏缺少 AI 输出声明"


def test_room_close_refreshes_main_chat():
    """回归（用户报告）：离开咖啡馆回主界面，聊天区要主动重载
    （房间消息直接落库，不切换好友也能看到）"""
    a_id = FriendRepository.insert("房间好友", "", "")
    window = MainWindow()
    window._on_friend_selected(a_id)
    count_before = window.chat_area.message_list.count()

    # 模拟房间里聊了一轮（直接落库），然后房间关闭
    MessageRepository.insert(a_id, "user", "在咖啡馆", 1)
    MessageRepository.insert(a_id, "ai", "咖啡不错", 1)
    window._on_room_closed(a_id)

    count_after = window.chat_area.message_list.count()
    assert count_after == count_before + 3      # 分隔线算 1 条：user + ai + divider
    texts = [window.chat_area.message_list.item(i) and
             getattr(window.chat_area.message_list.itemWidget(
                 window.chat_area.message_list.item(i)), "_bubble", None)
             for i in range(count_after)]
    bubble_texts = [b.text() for b in texts if b is not None]
    assert "在咖啡馆" in bubble_texts
    assert "咖啡不错" in bubble_texts
