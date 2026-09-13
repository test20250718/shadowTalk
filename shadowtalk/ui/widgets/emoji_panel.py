"""
ShadowTalk 表情面板
点击输入框旁的笑脸按钮展开，点击表情插入输入框
"""
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton
from PySide6.QtCore import Signal, Qt
from shadowtalk.ui.theme import current as theme_current

# 48 个常用表情（笑脸 / 手势 / 爱心 / 日常）
EMOJIS = [
    "😀", "😄", "😁", "😂", "🤣", "😊", "😇", "🙂",
    "😉", "😍", "😘", "🥰", "😜", "🤪", "😎", "🤓",
    "🥳", "😢", "😭", "😤", "😡", "🥺", "😳", "🤔",
    "🤗", "🙄", "😴", "🤤", "😷", "🤒", "💪", "👏",
    "👍", "👎", "👌", "✌️", "🤝", "🙏", "👋", "💖",
    "💕", "💯", "🔥", "✨", "🎉", "🎂", "🌈", "🍀",
]

BTN_SIZE = 38
COLUMNS = 8


class EmojiPanel(QFrame):
    """常用表情网格面板"""

    emoji_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(2)
        for i, emoji in enumerate(EMOJIS):
            btn = QPushButton(emoji)
            btn.setFixedSize(BTN_SIZE, BTN_SIZE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, e=emoji: self.emoji_selected.emit(e))
            grid.addWidget(btn, i // COLUMNS, i % COLUMNS)
        self.setFixedWidth(COLUMNS * BTN_SIZE + 20)
        self._apply_styles()

    def _apply_styles(self):
        """按当前主题重设面板与按钮样式（_build 与 restyle 共用）"""
        t = theme_current()
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                font-size: 20px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
            }}
        """)

    def restyle(self):
        """主题切换后按当前主题重设样式（ChatArea.restyle 持有调用）"""
        self._apply_styles()

    def set_panel_visible(self, visible: bool):
        """显示/隐藏面板"""
        self.setVisible(visible)
