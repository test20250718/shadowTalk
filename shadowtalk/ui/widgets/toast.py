# shadowtalk/ui/widgets/toast.py
"""轻量 Toast 提示组件：非阻塞、自动消失、淡入淡出动画。

用于替代容易被忽略的 statusBar.showMessage()，在操作结果需要明确反馈时使用
（如邮件发送成功/失败）。样式跟随当前主题。
"""
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint
from PySide6.QtGui import QColor

from shadowtalk.ui.theme import current as theme_current


class Toast(QFrame):
    """顶部居中浮动的 Toast 提示。

    用法：
        toast = Toast(self)          # parent = 主窗口
        toast.show_success("邮件已发送")
        toast.show_error("发送失败：xxx")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._build_animations()
        # 默认隐藏
        self.hide()

    def _build_ui(self):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 不挡点击
        self.setObjectName("toast")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(8)

        self._icon_label = QLabel("✓")
        self._icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._icon_label)

        self._text_label = QLabel()
        self._text_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._text_label)

        self._apply_style("success")

    def _build_animations(self):
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.hide)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._fade_out.start)

    def _apply_style(self, kind: str):
        t = theme_current()
        if kind == "success":
            bg = t.ACCENT
            fg = "#FFFFFF"
            border = t.ACCENT
        else:  # error
            bg = "#E53E3E" if t.name == "light" else "#FC8181"
            fg = "#FFFFFF"
            border = bg

        self._icon_label.setText("✓" if kind == "success" else "✗")
        self.setStyleSheet(f"""
            QFrame#toast {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 22px;
            }}
            QLabel {{
                color: {fg};
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }}
        """)

    def _reposition(self):
        """在父窗口顶部居中定位。"""
        if self.parentWidget():
            parent_rect = self.parentWidget().rect()
            # 宽度自适应文本，但有最大限制
            self.adjustSize()
            w = min(self.width(), parent_rect.width() - 40)
            self.setFixedWidth(w)
            x = (parent_rect.width() - w) // 2
            y = 16  # 离顶部 16px
            self.move(x, y)

    def show_success(self, text: str, duration_ms: int = 4000):
        self._show(text, "success", duration_ms)

    def show_error(self, text: str, duration_ms: int = 6000):
        self._show(text, "error", duration_ms)

    def _show(self, text: str, kind: str, duration_ms: int):
        # 如果正在自动隐藏，先停掉
        self._auto_hide_timer.stop()
        self._fade_out.stop()
        self._opacity.setOpacity(1.0)

        self._apply_style(kind)
        self._text_label.setText(text)
        self._reposition()
        self.show()
        self.raise_()
        self._fade_in.start()
        self._auto_hide_timer.start(duration_ms)
