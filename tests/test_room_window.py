"""沉浸式房间窗口测试（第一期：咖啡馆）"""
import sys
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from shadowtalk.config.settings import Settings
from shadowtalk.core.room_service import get_room
from shadowtalk.data.database import Database
from shadowtalk.data.repositories import FriendRepository, MessageRepository

Database.get_connection()  # 触发 rooms 播种

app = QApplication.instance() or QApplication(sys.argv)


def _make_friend(name="小影"):
    return FriendRepository.insert(name, "", "你是小影")


class _FakeWorker(QObject):
    """不启动真线程的 AIWorker 桩：记录创建参数与 cancel 调用"""
    finished = Signal(str)
    failed = Signal(str)
    approval_requested = Signal(str, list, str)
    activity = Signal(str)

    def __init__(self, friend_id, user_message, ai_client, messages,
                 work_dir="", approval_answered=None):
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.messages = messages
        self.work_dir = work_dir
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def isRunning(self):
        return False

    def wait(self, ms):
        return True

    def start(self):
        self.started = True


def test_room_window_title_and_no_history():
    """窗口标题含房间名与好友名；历史不进入悬浮区（沉浸式，画面是主角）"""
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = _make_friend()
    MessageRepository.insert(fid, "user", "上次聊过", 1)
    MessageRepository.insert(fid, "ai", "是呀", 1)

    win = RoomWindow(fid)

    assert "咖啡馆" in win.windowTitle()
    assert "小影" in win.windowTitle()
    # 悬浮区为空（仅上下两条弹簧），历史不显示
    assert win.chat_l.count() == 2
    assert win._ai_bubble is None
    win.close()


def test_room_shows_only_latest_ai_reply(monkeypatch):
    """自己的消息不回显；悬浮区只保留她最新一条回复"""
    from shadowtalk.ui.widgets import room_window as rw
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = rw.RoomWindow(fid)

    win.input_edit.setText("第一句")
    win._on_send()
    win.ai_worker.finished.emit("第一条回复")
    first = win._ai_bubble

    win.input_edit.setText("第二句")
    win._on_send()
    win.ai_worker.finished.emit("第二条回复")

    assert win.chat_l.count() == 3        # 上弹簧 + 唯一气泡 + 下弹簧
    # 气泡被弹簧夹住（左右索引处均为弹簧项）→ 短文时垂直居中
    assert win.chat_l.itemAt(0).widget() is None
    assert win.chat_l.itemAt(2).widget() is None
    assert win.chat_l.itemAt(1).widget() is win._ai_bubble
    assert win._ai_bubble is not first    # 旧气泡被替换
    assert win._ai_bubble._text == "第二条回复"
    win.close()


def test_room_send_builds_scene_context_and_persists(monkeypatch):
    """发消息：上下文带咖啡馆场景人设；消息落库；工作行显示"""
    from shadowtalk.ui.widgets import room_window as rw
    fid = _make_friend()
    created = []

    def fake_worker(*args, **kwargs):
        w = _FakeWorker(*args, **kwargs)
        created.append(w)
        return w

    monkeypatch.setattr(rw, "AIWorker", fake_worker)
    # 测试库无 api_key，openai 客户端构造会抛错 → 桩掉（本测试不关心它）
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())

    win = rw.RoomWindow(fid)
    win.input_edit.setText("喝点什么？")
    win._on_send()

    assert created, "未创建 worker"
    scene_in_ctx = any(m.get("content") == get_room("cafe")["scene_prompt"]
                       for m in created[0].messages)
    assert scene_in_ctx, "上下文缺少咖啡馆场景人设"
    contents = [m["content"] for m in
                MessageRepository.get_unarchived(fid)]
    assert "喝点什么？" in contents
    assert not win._activity_label.isHidden()
    win.close()


def test_room_reply_persists_and_auto_plays(monkeypatch):
    """回复到达：落库 + 悬浮气泡 + 开启自动朗读时播放"""
    from shadowtalk.ui.widgets import room_window as rw
    fid = _make_friend()
    played = []

    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = rw.RoomWindow(fid)
    monkeypatch.setattr(getattr(rw, "get_player")().__class__, "play",
                        lambda self, text, voice, mid: played.append((text, mid)))

    Settings.set("tts_auto_play", "1")
    try:
        win.input_edit.setText("你好")
        win._on_send()
        win.ai_worker.finished.emit("咖啡不错吧～")

        contents = [m["content"] for m in
                    MessageRepository.get_unarchived(fid)]
        assert "咖啡不错吧～" in contents
        assert played == [("咖啡不错吧～", 0)] or played  # 已触发播放
        assert win._activity_label.isHidden()
    finally:
        Settings.set("tts_auto_play", "0")
    win.close()


def test_room_new_send_interrupts_previous(monkeypatch):
    """房间内发新消息中断旧任务（与主界面同规则）"""
    from shadowtalk.ui.widgets import room_window as rw
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = rw.RoomWindow(fid)

    win.input_edit.setText("第一句")
    win._on_send()
    first = win.ai_worker

    win.input_edit.setText("第二句")
    win._on_send()

    assert first.cancelled
    assert win.ai_worker is not first
    win.close()


def test_room_approval_card_answer(monkeypatch):
    """目录外写入审批：悬浮卡出现，点允许后信号发出、卡片移除"""
    from shadowtalk.ui.widgets import room_window as rw
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = rw.RoomWindow(fid)

    answers = []
    win.approval_answered.connect(answers.append)
    win._on_approval("code", ["D:/x.txt"], "写文件")

    assert win._approval_card is not None
    allow_btn = next(b for b in win._approval_card.findChildren(QPushButton)
                     if b.text() == "允许")
    allow_btn.click()
    assert answers == [True]
    assert win._approval_card is None
    win.close()


def test_room_ai_bubble_has_play_button():
    """AI 气泡带 🔊 点播按钮，用户气泡没有"""
    from shadowtalk.ui.widgets.room_window import RoomBubble
    ai = RoomBubble("你好呀", "ai", msg_id=3)
    user = RoomBubble("你好", "user")
    assert ai._play_btn is not None
    assert user._play_btn is None


def test_show_in_screen_respects_taskbar():
    """最大化铺满用屏幕可用区域（排除任务栏），输入条不被挡
    （用户报告：showMaximized 底部输入框被任务栏遮住）"""
    from PySide6.QtGui import QGuiApplication
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = _make_friend()
    win = RoomWindow(fid)
    win.show_in_screen()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    # 客户区不越出可用区（输入条不被任务栏挡），且基本铺满
    assert win.geometry().bottom() <= avail.bottom()
    assert win.frameGeometry().bottom() <= avail.bottom() + 1
    assert win.geometry().height() > avail.height() * 0.85
    win.close()


def test_room_enter_key_does_not_trigger_buttons(monkeypatch):
    """回归（用户报告：发消息弹出文件选择框）：QDialog 按钮默认
    autoDefault=True，Enter（含输入法回车）会激活默认按钮——
    创建序第一个是『换背景』→ 误弹文件框。房间内所有按钮必须关闭。"""
    from shadowtalk.ui.widgets import room_window as rw
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = _make_friend()
    monkeypatch.setattr(rw, "AIWorker", lambda *a, **k: _FakeWorker(*a, **k))
    monkeypatch.setattr(rw, "AIClient", lambda *a, **k: object())
    win = RoomWindow(fid)
    win._show_ai_reply("你好", 1)             # 带播放按钮的气泡
    win._on_approval("code", ["D:/x.txt"], "写")  # 审批卡按钮

    offenders = [b.text() for b in win.findChildren(QPushButton)
                 if b.autoDefault()]
    assert offenders == [], f"未关闭 autoDefault 的按钮: {offenders}"
    win.close()


def test_room_close_emits_finished():
    """回归（用户报告：离开咖啡馆主界面不刷新）：close() 路径必须补发
    QDialog.finished —— Qt 只在 done()/accept() 时发它，而离开房间走 close"""
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = _make_friend()
    win = RoomWindow(fid)
    codes = []
    win.finished.connect(codes.append)
    win.close()
    assert codes, "close() 未发 finished，主界面无法得知房间已关闭"


def test_content_host_wraps_chat_and_user_hook():
    """内容区宿主默认只含聊天区；用户消息钩子默认空实现不抛错"""
    from shadowtalk.data.repositories import FriendRepository
    from shadowtalk.ui.widgets.room_window import RoomWindow
    fid = FriendRepository.insert("宿主测试", "", "测试")
    win = RoomWindow(fid, "cafe")
    assert win._content_host.count() == 1
    assert win._content_host.indexOf(win.chat_scroll) == 0
    win._show_user_message("你好")   # 咖啡馆不显示用户消息，静默即可
    win.close()
