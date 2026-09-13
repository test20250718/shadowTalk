# shadowtalk/ui/widgets/message_bubble.py
"""
ShadowTalk 聊天气泡组件
设计参考：shadowtalk-chat.html — 非对称圆角气泡 + 打字动画
"""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PySide6.QtCore import Qt, QRect, QSize, QPoint, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPixmap, QFont
from shadowtalk.ui.theme import current as theme_current


class AvatarLabel(QLabel):
    """圆形头像：优先显示图片，否则显示名字首字"""

    def __init__(self, name: str, image_path: str = "", size: int = 40,
                 variant: str = "default", parent=None):
        super().__init__(parent)
        self._size = size
        self._name = name or "?"
        self._variant = variant  # default / soft
        self._pixmap = None
        self.setFixedSize(size, size)
        self.set_avatar(name, image_path)

    def set_avatar(self, name: str, image_path: str = ""):
        """更新头像：图片优先，否则名字首字；空名字显示 ?"""
        self._name = name or "?"
        self._pixmap = None
        if image_path and os.path.isfile(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                self._pixmap = pix
        self._render()

    def _bg_color(self) -> str:
        t = theme_current()
        if self._variant == "soft":
            return t.SOFT
        return t.FG  # default — 浅色深底白字 / 深色浅底深字

    def _text_color(self) -> str:
        t = theme_current()
        return t.SURFACE if self._variant == "default" else t.FG

    def _render(self):
        diameter = self._size
        pixmap = QPixmap(diameter, diameter)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._pixmap:
            path = QPainterPath()
            path.addEllipse(0, 0, diameter, diameter)
            painter.setClipPath(path)
            scaled = self._pixmap.scaled(
                diameter, diameter,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            x = (scaled.width() - diameter) // 2
            y = (scaled.height() - diameter) // 2
            painter.drawPixmap(-x, -y, scaled)
        else:
            painter.setBrush(QColor(self._bg_color()))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, diameter, diameter)
            painter.setPen(QColor(self._text_color()))
            font = QFont()
            font.setPointSizeF(diameter * 0.40)
            font.setBold(True)
            painter.setFont(font)
            initial = self._name[0]
            painter.drawText(QRect(0, 0, diameter, diameter),
                             Qt.AlignCenter, initial)
        painter.end()
        self.setPixmap(pixmap)


class SpeechBubble(QLabel):
    """聊天气泡：纯 QSS，非对称圆角，文字和背景在同一层。
    AI 消息渲染 Markdown，宽度占满可用空间（长输出不折行受限）。"""

    def __init__(self, text: str, role: str, parent=None):
        """
        role: "user" | "ai"
        """
        super().__init__(text, parent)
        self._role = role
        self.setWordWrap(True)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
        self.setTextFormat(Qt.MarkdownText)  # 启用 Markdown 渲染
        # AI 消息全宽，用户消息限制最大宽度
        if role == "user":
            self.setMaximumWidth(420)
        else:
            self.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX，实际由布局约束
        self.setContentsMargins(15, 12, 15, 12)

        font = QFont()
        font.setPointSize(12)
        self.setFont(font)

        t = theme_current()
        if role == "user":
            # 自己：主题色气泡 + 白字 + 右下角尖
            self.setStyleSheet(
                f"background-color: {t.USER_BUBBLE};"
                f"color: {t.USER_FG};"
                "border-radius: 16px 16px 5px 16px;"
                "padding: 12px 15px;"
            )
        elif role == "human":
            # 真人回信：暖色调气泡 + 左下角尖（与 AI 区分）
            self.setStyleSheet(
                f"background-color: {t.HUMAN_BUBBLE};"
                f"color: {t.HUMAN_FG};"
                f"border: 1px solid {t.BORDER};"
                "border-radius: 16px 16px 16px 5px;"
                "padding: 12px 15px;"
            )
        else:
            # AI：主题色气泡 + 主题色文字 + 左下角尖
            self.setStyleSheet(
                f"background-color: {t.AI_BUBBLE};"
                f"color: {t.AI_FG};"
                f"border: 1px solid {t.BORDER};"
                "border-radius: 16px 16px 16px 5px;"
                "padding: 12px 15px;"
            )

    def heightForWidth(self, w: int) -> int:
        """QLabel::heightForWidth 的传入宽度与实际分配宽度不一致：
        布局按可用宽度问高度，但实际分配宽度被 clamp 到
        [sizeHint 理想宽度, maximumWidth]，导致高度被低估、文本尾部被裁剪。
        AI 消息无最大宽度限制，直接使用传入宽度计算。"""
        if self._role == "user":
            eff = min(w, self.sizeHint().width(), self.maximumWidth())
        else:
            eff = w  # AI 消息全宽，不限制
        return super().heightForWidth(eff)


class TypingIndicator(QWidget):
    """三点打字动画"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(62, 38)
        self._dots = [1.0, 1.0, 1.0]
        self._phase = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(160)

    def _animate(self):
        self._phase = (self._phase + 1) % 3
        for i in range(3):
            if i == self._phase:
                self._dots[i] = 0.28
            else:
                self._dots[i] = 1.0
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start(160)

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        t = theme_current()

        # 气泡背景
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(t.AI_BUBBLE))
        rect = self.rect().adjusted(0, 0, 0, 0)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.drawPath(path)

        # 边框
        pen = painter.pen()
        pen.setColor(QColor(t.BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 16, 16)

        # 三点
        painter.setPen(Qt.NoPen)
        cx = 21
        cy = 19
        for i, alpha in enumerate(self._dots):
            color = QColor(t.MUTED)
            color.setAlphaF(alpha)
            painter.setBrush(color)
            painter.drawEllipse(QPoint(cx + i * 11, cy), 4, 4)


class MessageBubble(QWidget):
    """完整的消息行：头像 + 气泡 + 元信息 + （AI）语音播放按钮"""

    play_requested = Signal(str, int)  # (text, msg_id)
    stop_requested = Signal(int)       # msg_id（播放中再点按钮 → 停止，规格 5.2）

    def __init__(self, text: str, role: str, timestamp: str,
                 avatar_name: str = "", avatar_path: str = "",
                 avatar_variant: str = "default", msg_id: int = 0,
                 parent=None):
        super().__init__(parent)
        self._role = role
        self.msg_id = msg_id
        self._play_btn = None
        self._build_ui(text, role, timestamp, avatar_name, avatar_path, avatar_variant)

    def _build_ui(self, text, role, timestamp, avatar_name, avatar_path, avatar_variant):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(26, 6, 26, 6)
        main_layout.setSpacing(4)

        # 内容行
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)

        # 头像
        avatar_size = 32
        avatar = AvatarLabel(avatar_name, avatar_path, avatar_size, variant=avatar_variant)

        # 气泡容器（气泡 + 元信息）
        bubble_col = QVBoxLayout()
        bubble_col.setSpacing(4)
        bubble_col.setContentsMargins(0, 0, 0, 0)

        self._bubble = SpeechBubble(text, role)
        # 用户消息按内容自然宽度靠左；AI 消息不设对齐 → 水平占满整列
        # （AlignLeft 会把宽度钉在 sizeHint，窗口拉宽后气泡不跟随铺满）
        if role == "user":
            bubble_col.addWidget(self._bubble, 0, Qt.AlignLeft)
        else:
            bubble_col.addWidget(self._bubble, 1)

        # 元信息行：AI 消息在时间戳左侧加语音播放按钮
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(0, 0, 0, 0)
        t = theme_current()
        if role == "ai" and text.strip():
            self._play_btn = QPushButton("🔊")
            self._play_btn.setFixedSize(22, 18)
            self._play_btn.setCursor(Qt.PointingHandCursor)
            self._play_btn.setToolTip("播放语音")
            self._play_btn.setCheckable(True)
            self._play_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: 5px;
                    font-size: 11px;
                    color: {t.MUTED};
                }}
                QPushButton:hover {{
                    background-color: {t.BG};
                }}
                QPushButton:checked {{
                    background-color: {t.ACCENT_SOFT};
                    color: {t.ACCENT};
                }}
            """)
            self._play_btn.clicked.connect(self._on_play_clicked)
            meta_row.addWidget(self._play_btn)
        if timestamp:
            meta = QLabel(timestamp)
            meta.setStyleSheet(
                f"color: {t.MUTED}; font-size: 10px; padding: 0 4px;"
            )
            meta_row.addWidget(meta)
        if role == "user":
            meta_row.addStretch()
        bubble_col.addLayout(meta_row)

        if role == "user":
            # stretch 因子必须为 1：bubble_col 因 meta_row 的 stretch 而
            # 水平可扩展，因子 0 时两者平分剩余空间，气泡漂到窗口中间
            row.addStretch(1)
            row.addLayout(bubble_col)
            row.addWidget(avatar, 0, Qt.AlignBottom)
        else:
            # AI / 真人回信：头像在左，气泡占满剩余宽度
            row.addWidget(avatar, 0, Qt.AlignBottom)
            row.addLayout(bubble_col, 1)  # stretch=1，气泡列占满可用宽度

        main_layout.addLayout(row)

    def _on_play_clicked(self):
        if self._play_btn.isChecked():
            self.play_requested.emit(self._bubble.text(), self.msg_id)
        else:
            self.stop_requested.emit(self.msg_id)

    def set_playing(self, playing: bool):
        """播放状态驱动按钮外观（checked = 播放中）"""
        if self._play_btn is None:
            return
        self._play_btn.setChecked(playing)
        self._play_btn.setToolTip("停止" if playing else "播放语音")


class ApprovalCard(QWidget):
    """写文件确认卡片：路径列表 + 允许/拒绝"""

    approved = Signal(bool)

    def __init__(self, paths, reason, parent=None):
        super().__init__(parent)
        t = theme_current()
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        title = QLabel("✋ 秘书想写入以下文件：")
        title.setStyleSheet(f"color: {t.FG}; font-weight: bold; font-size: 12px;")
        layout.addWidget(title)

        for p in paths:
            path_label = QLabel(f"· {p}")
            path_label.setWordWrap(True)
            path_label.setStyleSheet(f"color: {t.FG}; font-size: 12px;")
            layout.addWidget(path_label)

        if reason:
            reason_label = QLabel(f"说明：{reason}")
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet(f"color: {t.MUTED}; font-size: 11px;")
            layout.addWidget(reason_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 6, 0, 0)
        allow = QPushButton("允许")
        allow.setCursor(Qt.PointingHandCursor)
        allow.setStyleSheet(
            f"background: {t.ACCENT}; color: white; border: none;"
            "border-radius: 6px; padding: 4px 16px;"
        )
        deny = QPushButton("拒绝")
        deny.setCursor(Qt.PointingHandCursor)
        deny.setStyleSheet(
            f"background: {t.BORDER}; color: {t.FG}; border: none;"
            "border-radius: 6px; padding: 4px 16px;"
        )
        allow.clicked.connect(lambda: self.approved.emit(True))
        deny.clicked.connect(lambda: self.approved.emit(False))
        btn_row.addWidget(allow)
        btn_row.addWidget(deny)
        btn_row.addStretch()
        layout.addLayout(btn_row)


class DayDivider(QWidget):
    """日期分隔线"""

    def __init__(self, text: str = "今天", parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        t = theme_current()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 14, 26, 6)
        layout.setSpacing(14)

        line1 = QLabel()
        line1.setFixedHeight(1)
        line1.setStyleSheet(f"background-color: {t.BORDER};")
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {t.MUTED}; font-family: Menlo, monospace; font-size: 11px;"
        )
        line2 = QLabel()
        line2.setFixedHeight(1)
        line2.setStyleSheet(f"background-color: {t.BORDER};")

        layout.addWidget(line1, 1)
        layout.addWidget(label, 0)
        layout.addWidget(line2, 1)
