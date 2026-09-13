"""MessageBubble 取色测试：气泡 QSS 跟随当前主题（spec 6 第 5 用例）"""
import sys
from PySide6.QtWidgets import QApplication
from shadowtalk.ui.theme import set_current
from shadowtalk.ui.widgets.message_bubble import SpeechBubble

app = QApplication.instance() or QApplication(sys.argv)


def test_user_bubble_qss_follows_theme():
    set_current("light")
    b = SpeechBubble("你好", "user")
    assert "#37352F" in b.styleSheet()  # LIGHT.USER_BUBBLE
    set_current("dark")
    b = SpeechBubble("你好", "user")
    assert "#2E9E57" in b.styleSheet()  # DARK.USER_BUBBLE
    set_current("light")  # 复位全局状态


def test_ai_bubble_qss_follows_theme():
    set_current("dark")
    b = SpeechBubble("回复", "ai")
    assert "#2E2E34" in b.styleSheet()  # DARK.AI_BUBBLE
    assert "border: 1px solid #3A3A40" in b.styleSheet()  # DARK.BORDER
    assert "color: #E8E6E1" in b.styleSheet()  # DARK.AI_FG
    set_current("light")
    b = SpeechBubble("回复", "ai")
    assert "#FFFFFF" in b.styleSheet()  # LIGHT.AI_BUBBLE
