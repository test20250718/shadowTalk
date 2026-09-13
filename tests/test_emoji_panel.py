"""EmojiPanel 组件测试"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from shadowtalk.ui.widgets.emoji_panel import EmojiPanel

app = QApplication.instance() or QApplication(sys.argv)


def test_restyle_reapplies_dark_theme_styles():
    """主题切换后 restyle() 将面板样式重设为深色（ChatArea.restyle 持有调用）"""
    from shadowtalk.ui import theme
    panel = EmojiPanel()
    theme.set_current("dark")
    panel.restyle()
    assert "#26262B" in panel.styleSheet()  # DARK.SURFACE（面板底）
    assert "#1A1A1E" in panel.styleSheet()  # DARK.BG（按钮 hover）
    theme.set_current("light")  # 复位


def test_panel_starts_hidden():
    panel = EmojiPanel()
    assert not panel.isVisible()


def test_click_emits_emoji_selected():
    panel = EmojiPanel()
    received = []
    panel.emoji_selected.connect(received.append)
    # 通过 findChildren 拿到第一个表情按钮并点击
    from PySide6.QtWidgets import QPushButton
    first_btn = panel.findChildren(QPushButton)[0]
    first_btn.click()
    assert len(received) == 1
    assert isinstance(received[0], str)
    assert len(received[0]) >= 1  # 是一个非空字符


def test_has_enough_emojis():
    from PySide6.QtWidgets import QPushButton
    panel = EmojiPanel()
    buttons = panel.findChildren(QPushButton)
    assert len(buttons) >= 48


def test_chat_area_emoji_integration():
    """ChatArea 集成：点按钮切换面板，点表情插入输入框"""
    from shadowtalk.ui.widgets.chat_area import ChatArea
    from PySide6.QtWidgets import QPushButton

    area = ChatArea()
    area.show()  # 显示顶层窗口，isVisible() 才有意义
    assert hasattr(area, "emoji_btn")
    assert hasattr(area, "emoji_panel")

    # 初始隐藏
    assert not area.emoji_panel.isVisible()

    # 点按钮 → 展开
    area.emoji_btn.click()
    assert area.emoji_panel.isVisible()

    # 点表情 → 插入输入框
    area.emoji_panel.findChildren(QPushButton)[0].click()
    text = area.input_box.toPlainText()
    assert len(text) >= 1  # 有内容

    # 点表情后面板不自动收起（真实鼠标按下，验证面板内点击不收起）
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    btn = area.emoji_panel.findChildren(QPushButton)[0]
    local = btn.rect().center()
    global_pos = btn.mapToGlobal(local)
    press = QMouseEvent(
        QEvent.MouseButtonPress, local, global_pos,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(btn, press)
    assert area.emoji_panel.isVisible()

    # 再点按钮 → 收起
    area.emoji_btn.click()
    assert not area.emoji_panel.isVisible()


def test_click_outside_panel_collapses_it():
    """点击面板外部任意处（消息列表 viewport）→ 收起面板"""
    from shadowtalk.ui.widgets.chat_area import ChatArea
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    area = ChatArea()
    area.show()  # 显示顶层窗口，isVisible() 才有意义
    area.emoji_btn.click()
    assert area.emoji_panel.isVisible()

    # 点消息列表空白处（真实控件路径，经全局事件过滤）→ 收起
    viewport = area.message_list.viewport()
    local = QPoint(5, 5)
    global_pos = viewport.mapToGlobal(local)
    press = QMouseEvent(
        QEvent.MouseButtonPress, local, global_pos,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(viewport, press)
    assert not area.emoji_panel.isVisible()


def test_click_panel_blank_background_keeps_it_open():
    """点击面板自身空白背景（obj 恰为 panel 本身）→ 不收起"""
    from shadowtalk.ui.widgets.chat_area import ChatArea
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    area = ChatArea()
    area.show()
    area.emoji_btn.click()
    assert area.emoji_panel.isVisible()

    # 向面板自身投 MouseButtonPress（坐标在面板内）→ 不收起
    local = QPoint(5, 5)
    global_pos = area.emoji_panel.mapToGlobal(local)
    press = QMouseEvent(
        QEvent.MouseButtonPress, local, global_pos,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(area.emoji_panel, press)
    assert area.emoji_panel.isVisible()
