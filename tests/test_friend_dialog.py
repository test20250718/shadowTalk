"""FriendDialog 工作目录字段测试"""
import sys
from PySide6.QtWidgets import QApplication
from shadowtalk.core.tts_service import TTS_VOICES
from shadowtalk.ui.widgets.friend_dialog import FriendDialog
from shadowtalk.ui import theme

app = QApplication.instance() or QApplication(sys.argv)


def test_work_dir_input_blank_for_new_friend():
    dialog = FriendDialog()
    assert dialog.work_dir_input.text() == ""
    assert dialog.get_data()["work_dir"] == ""


def test_work_dir_fills_from_friend_and_returns():
    friend = {"name": "秘书", "remark": "", "ai_role": "", "user_role": "",
              "system_prompt": "", "avatar_path": "", "work_dir": "D:/novel/p1",
              "voice": ""}
    dialog = FriendDialog(friend=friend)
    assert dialog.work_dir_input.text() == "D:/novel/p1"
    assert dialog.get_data()["work_dir"] == "D:/novel/p1"


def test_work_dir_browse_button_exists():
    dialog = FriendDialog()
    from PySide6.QtWidgets import QPushButton
    buttons = dialog.findChildren(QPushButton)
    assert any(b.text() == "浏览…" for b in buttons)


def test_friend_dialog_voice_combo():
    dlg = FriendDialog()
    assert dlg.voice_combo.count() == len(TTS_VOICES) + 1  # 首项"默认"
    assert dlg.voice_combo.itemData(0) == ""
    dlg.voice_combo.setCurrentIndex(dlg.voice_combo.findData("zh-CN-YunxiNeural"))
    assert dlg.get_data()["voice"] == "zh-CN-YunxiNeural"


def test_friend_dialog_voice_default():
    dlg = FriendDialog()
    assert dlg.get_data()["voice"] == ""


def test_dialog_label_color_rule_dark():
    """回归：深色下表单行标签（头像左侧）不得为默认黑字。
    Qt QSS 的 color 不向子控件传播，必须显式 QDialog QLabel 规则。"""
    theme.set_current("dark")
    dialog = FriendDialog()
    qss = dialog.styleSheet()
    assert "QDialog QLabel" in qss
    assert "color: #E8E6E1" in qss  # DARK.FG
    theme.set_current("light")


def test_checkbox_color_rule_dark():
    """回归：深色下邮件同步复选框（QCheckBox）文字不得为默认黑字。
    QSS color 不向子控件传播，必须显式 QCheckBox 规则。"""
    theme.set_current("dark")
    dialog = FriendDialog()
    qss = dialog.styleSheet()
    assert "QCheckBox" in qss
    # QCheckBox 选择器块内须含深色前景色（不依赖 QLabel 规则）
    cb_idx = qss.index("QCheckBox")
    next_block = qss[cb_idx:cb_idx + 200]
    assert "color: #E8E6E1" in next_block
    theme.set_current("light")


def test_voice_combo_dark_style():
    """回归：语音下拉框 QSS 须含 QComboBox 规则（原 _input_style 只有
    QLineEdit 选择器，不作用于 QComboBox，深色下为默认白底黑字）"""
    theme.set_current("dark")
    dialog = FriendDialog()
    qss = dialog.voice_combo.styleSheet()
    assert "QComboBox" in qss
    assert "color: #E8E6E1" in qss
    assert "QAbstractItemView" in qss  # 下拉弹层也要深色
    theme.set_current("light")


def test_friend_dialog_fills_voice_from_sqlite_row():
    """生产路径 friend 是 sqlite3.Row（无 .get()），回归测试防崩溃"""
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE friends (name, remark, ai_role, user_role, work_dir, "
        "system_prompt, avatar_path, voice)"
    )
    conn.execute(
        "INSERT INTO friends VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("v", "", "", "", "", "", "", "zh-CN-YunxiNeural"),
    )
    row = conn.execute("SELECT * FROM friends").fetchone()
    assert not hasattr(row, "get")  # 前提校验：生产路径对象确实无 .get()
    dlg = FriendDialog(friend=row)
    assert dlg.voice_combo.currentData() == "zh-CN-YunxiNeural"
