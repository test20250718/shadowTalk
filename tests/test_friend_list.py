"""FriendListWidget 会话预览测试

回归保护：会话列表预览（头像下方最后消息 + 时间）—— 曾缺失
"启动时从数据库加载最后消息"且 set_last_message 不刷新已渲染的列表项，
导致预览从不显示。
"""
import sys
from PySide6.QtWidgets import QApplication
from shadowtalk.ui.widgets.friend_list import FriendListWidget

app = QApplication.instance() or QApplication(sys.argv)

FRIEND = {"id": 1, "name": "小明", "remark": "", "avatar_path": ""}


def test_restyle_reapplies_dark_theme_styles():
    """主题切换后 restyle() 将侧栏容器样式重设为深色（回归：构造时一次取色冻结）"""
    from shadowtalk.ui import theme
    fl = FriendListWidget()
    theme.set_current("dark")
    fl.restyle()
    assert "#26262B" in fl.styleSheet()                 # DARK.SURFACE
    assert "#1A1A1E" in fl.search_input.styleSheet()    # DARK.BG
    assert "#3A3A40" in fl._actions_frame.styleSheet()  # DARK.BORDER
    assert "#E8E6E1" in fl.add_btn.styleSheet()         # DARK.FG
    # 品牌头部已移除（logo + "影聊 · 私密对话"）
    assert fl._brand_mark is None
    theme.set_current("light")  # 复位


def test_sidebar_stylesheet_has_messagebox_rules():
    """回归：删除好友确认弹窗挂在 FriendListWidget 样式表下
    （父级样式表覆盖继承），须自带 QMessageBox 深色规则"""
    from shadowtalk.ui import theme
    fl = FriendListWidget()
    theme.set_current("dark")
    fl.restyle()
    assert "QMessageBox" in fl.styleSheet()
    assert "#E8E6E1" in fl.styleSheet()  # DARK.FG
    theme.set_current("light")  # 复位


def test_load_friends_shows_preset_last_messages():
    """load_friends 前填充的字典应渲染为预览（启动路径：先查库再渲染）"""
    fl = FriendListWidget()
    fl.set_last_message(1, "最近一条消息", "08:30")
    fl.load_friends([FRIEND])
    widget = fl._friend_items[1]
    assert widget._preview_label.text() == "最近一条消息"
    assert widget._time_label.text() == "08:30"


def test_set_last_message_refreshes_item_ui():
    """会话中发消息后，列表项预览应即时刷新（不重建列表）"""
    fl = FriendListWidget()
    fl.load_friends([FRIEND])
    widget = fl._friend_items[1]
    assert widget._preview_label.text() == "　"  # 无消息时占位全角空格

    fl.set_last_message(1, "你好呀", "12:34")

    assert widget._preview_label.text() == "你好呀"
    assert widget._time_label.text() == "12:34"


def test_set_last_message_before_load_applies_to_fresh_render():
    """先 set 再 load（增删好友后重建列表）预览不丢"""
    fl = FriendListWidget()
    fl.set_last_message(1, "先填充", "09:00")
    fl.load_friends([FRIEND])
    fl.load_friends([FRIEND])  # 再次重建（编辑/删除后场景）
    widget = fl._friend_items[1]
    assert widget._preview_label.text() == "先填充"


def test_room_button_invokes_callback():
    """☕ 房间按钮存在且点击触发回调（沉浸式房间入口）"""
    fl = FriendListWidget()
    assert fl.room_btn is not None
    calls = []
    fl._room_callback = lambda: calls.append(True)
    fl.room_btn.click()
    assert calls == [True]
