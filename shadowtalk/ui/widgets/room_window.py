# shadowtalk/ui/widgets/room_window.py
"""沉浸式房间窗口（第一期：咖啡馆）

全屏背景图 + 半透明悬浮对话 + TTS 语音。对话记录记到好友名下，
记忆与主线共享（她在房间里聊过的主线也记得）。
设计文档：docs/superpowers/specs/2026-08-16-immersive-rooms-design.md
"""
import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QElapsedTimer
from PySide6.QtGui import QPainter, QPixmap, QColor, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QWidget, QFileDialog, QFrame,
)

from shadowtalk.config.settings import Settings
from shadowtalk.core.ai_client import AIClient
from shadowtalk.core.friend_service import resolve_avatar
from shadowtalk.core.room_service import (
    build_room_context, get_room, get_room_bg, save_room_bg,
)
from shadowtalk.core.prompt_logger import log_conversation
from shadowtalk.core.tts_service import resolve_voice
from shadowtalk.data.repositories import FriendRepository, MessageRepository
from shadowtalk.data.database import Database
from shadowtalk.ui.threads.ai_worker import AIWorker
from shadowtalk.ui.widgets.tts_player import get_player

logger = logging.getLogger(__name__)

_ROOM_ICONS = {"cafe": "☕", "music": "🎵", "reading": "📖", "english": "🏫"}


def _now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


class RoomBubble(QWidget):
    """悬浮对话气泡：半透明圆角；AI 侧带点播按钮"""
    play_requested = Signal(str, int)   # (text, msg_id)

    def __init__(self, text: str, role: str, msg_id: int = 0, parent=None,
                 icon: str = "☕"):
        super().__init__(parent)
        self.msg_id = msg_id
        self._text = text
        self._play_btn = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 3, 26, 3)
        layout.setSpacing(8)

        if role == "user":
            layout.addStretch(1)
            layout.addWidget(self._make_label(text, role), 0, Qt.AlignRight)
        else:
            avatar_mark = QLabel(icon)
            avatar_mark.setStyleSheet("font-size: 13px; background: transparent;")
            layout.addWidget(avatar_mark, 0, Qt.AlignBottom)
            layout.addWidget(self._make_label(text, role), 0, Qt.AlignLeft)
            if text.strip():
                self._play_btn = QPushButton("🔊")
                self._play_btn.setFixedSize(24, 24)
                self._play_btn.setCursor(Qt.PointingHandCursor)
                self._play_btn.setAutoDefault(False)
                self._play_btn.setToolTip("播放语音")
                self._play_btn.setStyleSheet("""
                    QPushButton { background: rgba(255,255,255,150);
                                  border: none; border-radius: 8px; font-size: 11px; }
                    QPushButton:hover { background: rgba(255,255,255,220); }
                """)
                self._play_btn.clicked.connect(
                    lambda: self.play_requested.emit(self._text, self.msg_id))
                layout.addWidget(self._play_btn, 0, Qt.AlignBottom)
            layout.addStretch(1)

    @staticmethod
    def _make_label(text: str, role: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(430)
        # QLabel 自动换行在滚动区内不会主动撑高（sizeHint 按宽度给出
        # 但布局只给到 minimum → 长文被裁剪）。按 430px 换行显式设最小高。
        if text:
            label.setMinimumHeight(label.heightForWidth(430))
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if role == "user":
            label.setStyleSheet("""
                background-color: rgba(46,158,87,225);
                color: white; border-radius: 14px;
                padding: 8px 14px; font-size: 13px;
            """)
        else:
            label.setStyleSheet("""
                background-color: rgba(255,255,255,215);
                color: #1F2430; border-radius: 14px;
                padding: 8px 14px; font-size: 13px;
            """)
        return label


class RoomWindow(QDialog):
    """咖啡馆沉浸窗口：上图（铺满）下输入，悬浮对话 + 语音"""
    approval_answered = Signal(bool)

    def __init__(self, friend_id: int, room_key: str = "cafe", parent=None):
        super().__init__(parent)
        self.room = get_room(room_key) or {
            "key": room_key, "name": "房间", "scene_prompt": "", "bg_path": ""}
        self.friend_id = friend_id
        row = FriendRepository.get_by_id(friend_id)
        friend = dict(row) if row else {}
        self.friend_name = (friend.get("remark") or friend.get("name") or "好友")
        self.friend_voice = friend.get("voice", "")
        self.friend_work_dir = friend.get("work_dir", "")
        self._avatar_path = resolve_avatar(friend.get("avatar_path", ""))

        self.ai_worker = None
        self._retired_workers = []
        self.ai_client = None
        self._pixmap = None
        self._approval_card = None
        self._ai_bubble = None   # 只保留她最新一条回复（历史不入悬浮区）
        self._pending_context = None  # 待记录的上下文（回复完成后写入日志）

        self.setWindowTitle(f"{self.room['name']} · {self.friend_name}")
        self.setModal(False)
        # 加最小化/最大化按钮（默认仍可全屏，但用户可自由缩放）
        self.setWindowFlags(self.windowFlags()
                            | Qt.WindowMinMaxButtonsHint
                            | Qt.WindowTitleHint)
        self.resize(1100, 720)
        # 背景图由 paintEvent 绘制，对话框本身不自动填底色（否则会挡图）
        self.setAutoFillBackground(False)
        self._build_ui()
        # 每个好友记住自己的咖啡馆图片（未设过回落房间默认图）
        self._load_bg(get_room_bg(room_key, friend_id))

    # ── UI ──
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部半透明工具条
        top = QFrame()
        top.setStyleSheet("background-color: rgba(20,16,12,120);")
        top_l = QHBoxLayout(top)
        self._top_layout = top_l   # 子类（英语教室）往顶栏插统计标签
        top_l.setContentsMargins(18, 8, 14, 8)
        icon = _ROOM_ICONS.get(self.room.get("key", ""), "🏠")
        title = QLabel(f"{icon} {self.room['name']} · 与 {self.friend_name}")
        title.setStyleSheet("color: #F5EFE6; font-size: 14px; background: transparent;")
        top_l.addWidget(title)
        top_l.addStretch()
        bg_btn = QPushButton("换背景")
        leave_btn = QPushButton("离开房间")
        # QDialog 按钮默认 autoDefault=True：Enter（含输入法提交的回车）
        # 会激活"默认按钮"——创建顺序第一个是换背景 → 误弹文件选择框。
        # Enter 只用于发消息（input_edit.returnPressed）。
        bg_btn.setAutoDefault(False)
        leave_btn.setAutoDefault(False)
        for b in (bg_btn, leave_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,40); color: #F5EFE6;
                              border: none; border-radius: 8px; padding: 5px 14px; }
                QPushButton:hover { background: rgba(255,255,255,90); }
            """)
        bg_btn.clicked.connect(self._on_pick_bg)
        leave_btn.clicked.connect(self.close)
        top_l.addWidget(bg_btn)
        top_l.addWidget(leave_btn)
        layout.addWidget(top)

        # 悬浮对话区：占据中段全部空间，气泡左侧垂直居中；
        # 内容超出可用高度时才出现滚动条（用户要求：尽量显示全）
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)
        self.chat_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,90);"
            " border-radius: 3px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        self.chat_host = QWidget()
        self.chat_host.setStyleSheet("background: transparent;")
        self.chat_l = QVBoxLayout(self.chat_host)
        self.chat_l.setContentsMargins(0, 10, 0, 10)
        self.chat_l.setSpacing(4)
        self.chat_l.addStretch(1)   # 上弹簧：短文时把气泡推向垂直居中
        self.chat_l.addStretch(1)   # 下弹簧
        self.chat_scroll.setWidget(self.chat_host)
        # 内容区宿主：默认只有聊天区（咖啡馆/音乐室不变）；
        # 子类可往里插内容（阅读室在左侧插书页区）
        self._content_host = QHBoxLayout()
        self._content_host.setContentsMargins(0, 0, 0, 0)
        self._content_host.addWidget(self.chat_scroll, 1)
        layout.addLayout(self._content_host, 1)

        # 工作行（干活进度，同主界面工作卡）
        self._activity_label = QLabel("")
        self._activity_label.setStyleSheet(
            "color: rgba(245,239,230,200); font-size: 12px;"
            "background: transparent; padding: 0 28px 2px;")
        self._activity_label.hide()
        layout.addWidget(self._activity_label)
        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(self._tick_activity)
        self._activity_clock = QElapsedTimer()

        # 审批卡片挂载点
        self._approval_host = QVBoxLayout()
        layout.addLayout(self._approval_host)

        # 子类扩展区（输入条上方：音乐室放播放控制条等）
        self._pre_input_host = QVBoxLayout()
        layout.addLayout(self._pre_input_host)

        # 底部输入条
        input_bar = QFrame()
        self.input_bar = input_bar   # 子类（阅读室）需要引用以计算 PDF 高度
        input_bar.setStyleSheet("background-color: rgba(20,16,12,150);")
        bar_l = QHBoxLayout(input_bar)
        bar_l.setContentsMargins(18, 10, 14, 10)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(f"和 {self.friend_name} 说说…（Enter 发送）")
        self.input_edit.setStyleSheet("""
            QLineEdit { background: rgba(255,255,255,235); border: none;
                        border-radius: 16px; padding: 8px 16px; font-size: 13px; }
        """)
        self.input_edit.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setAutoDefault(False)  # Enter 走 returnPressed，不重复触发
        self.send_btn.setStyleSheet("""
            QPushButton { background: rgba(46,158,87,235); color: white;
                          border: none; border-radius: 14px;
                          padding: 8px 20px; font-weight: bold; }
            QPushButton:hover { background: rgba(38,138,76,240); }
        """)
        self.send_btn.clicked.connect(self._on_send)
        bar_l.addWidget(self.input_edit, 1)
        bar_l.addWidget(self.send_btn)
        layout.addWidget(input_bar)

    def show_in_screen(self):
        """铺满"屏幕可用区域"（自动排除任务栏）。

        showMaximized 在部分环境下窗口高度会盖到任务栏，
        底部输入条被挡住（用户报告）——改用 availableGeometry，
        并按标题栏/边框补偿，使客户区精确落在可用区域内。
        """
        from PySide6.QtGui import QGuiApplication
        screen = None
        parent = self.parent()
        if parent is not None and hasattr(parent, "screen"):
            screen = parent.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        self.show()
        self.raise_()
        if screen is not None:
            avail = screen.availableGeometry()
            fg, g = self.frameGeometry(), self.geometry()
            top = g.top() - fg.top()
            left = g.left() - fg.left()
            right = fg.right() - g.right()
            bottom = fg.bottom() - g.bottom()
            self.setGeometry(
                avail.left() + left, avail.top() + top,
                avail.width() - left - right,
                avail.height() - top - bottom)

    def paintEvent(self, event):
        """背景图 cover 铺满；无图时填主题底色（与主页一致）"""
        from shadowtalk.ui.theme import current as theme_current
        p = QPainter(self)
        if self._pixmap and not self._pixmap.isNull():
            pw, ph = self._pixmap.width(), self._pixmap.height()
            scale = max(self.width() / pw, self.height() / ph)
            w, h = int(pw * scale), int(ph * scale)
            x, y = (self.width() - w) // 2, (self.height() - h) // 2
            p.drawPixmap(x, y, self._pixmap.scaled(w, h,
                                                    Qt.KeepAspectRatioByExpanding,
                                                    Qt.SmoothTransformation))
        else:
            # 无背景图时填主题底色，与主页颜色一致（深色模式→深色）
            p.fillRect(self.rect(), QColor(theme_current().BG))
        p.end()

    # ── 消息流 ──
    def _show_user_message(self, text: str):
        """用户消息上屏钩子：咖啡馆/音乐室不显示（只显示她的回复），
        阅读室覆盖为流式气泡（讨论要能看到双方的话）"""

    def _show_ai_reply(self, text: str, msg_id: int = 0):
        """悬浮区只显示她最新一条回复：左侧垂直居中（上下弹簧夹住，
        内容超高时滚动条接管）；替换旧气泡"""
        if self._ai_bubble is not None:
            self.chat_l.removeWidget(self._ai_bubble)
            self._ai_bubble.deleteLater()
        self._ai_bubble = RoomBubble(
            text, "ai", msg_id,
            icon=_ROOM_ICONS.get(self.room.get("key", ""), "☕"))
        self._ai_bubble.play_requested.connect(self._on_play)
        # 插到两个弹簧之间：[上弹簧, 气泡, 下弹簧]
        self.chat_l.insertWidget(1, self._ai_bubble)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """布局完成后再滚到底（立即设值时布局未更新，滚不到位）"""
        def _do():
            sb = self.chat_scroll.verticalScrollBar()
            sb.setValue(sb.maximum())
        QTimer.singleShot(0, _do)

    def _current_scene_prompt(self) -> str:
        """当前场景人设（子类可覆盖追加动态信息，如正在播放的歌）"""
        return self.room["scene_prompt"]

    def _on_send(self):
        text = self.input_edit.text().strip()
        if not text or not self.friend_id:
            return
        self._stop_current_worker()
        self.input_edit.clear()
        MessageRepository.insert(self.friend_id, "user", text,
                                 self._next_round_index())
        self._show_user_message(text)

        try:
            context = build_room_context(
                self.friend_id, text, self._current_scene_prompt())
        except Exception as e:
            logger.error("房间构建上下文失败: %s", e, exc_info=True)
            self._show_ai_reply(f"（出错了：{e}）")
            return

        self._show_activity("正在思考…")
        try:
            if self.ai_client is None:
                self.ai_client = AIClient(
                    base_url=Settings.get("api_base_url"),
                    api_key=Settings.get("api_key"),
                    model=Settings.get("model_name"),
                    temperature=Settings.get_float("temperature"),
                    max_tokens=Settings.get_int("max_output_tokens"),
                )
        except Exception as e:
            self._hide_activity()
            self._show_ai_reply(f"（AI 客户端初始化失败：{e}）")
            return

        self.ai_worker = AIWorker(
            self.friend_id, text, self.ai_client, context,
            work_dir=self.friend_work_dir,
            approval_answered=self.approval_answered,
        )
        self.ai_worker.finished.connect(self._on_reply)
        self.ai_worker.failed.connect(self._on_failed)
        self.ai_worker.activity.connect(self._set_activity)
        self.ai_worker.approval_requested.connect(self._on_approval)
        self._pending_context = context  # 保存上下文，回复完成后记录日志
        self.ai_worker.start()

    def _on_reply(self, reply: str):
        self._hide_activity()
        msg_id = MessageRepository.insert(
            self.friend_id, "ai", reply, self._current_round_index())
        self._show_ai_reply(reply, msg_id)
        # 记录提示词日志（与主界面共享日志目录）
        if self._pending_context:
            log_conversation(
                friend_name=self.friend_name,
                friend_id=self.friend_id,
                context=self._pending_context,
                user_message=self.ai_worker.user_message if self.ai_worker else "",
                ai_reply=reply,
            )
            self._pending_context = None
        if Settings.get("tts_auto_play") == "1":
            self._on_play(reply, msg_id)

    def _on_failed(self, error: str):
        self._hide_activity()
        self._show_ai_reply(f"（她走神了：{error}）")

    def _on_play(self, text: str, msg_id: int):
        voice = resolve_voice(self.friend_voice, Settings.get("tts_voice"))
        get_player().play(text, voice, msg_id)

    # ── 工作行（防"感觉卡死"）──
    def _show_activity(self, text: str):
        self._activity_label.setText(text)
        self._activity_label.show()
        self._activity_clock.start()
        self._activity_timer.start(1000)

    def _set_activity(self, text: str):
        self._activity_label.setText(text)

    def _tick_activity(self):
        secs = self._activity_clock.elapsed() // 1000
        self._activity_label.setText(f"{self._activity_label.text().split(' · ')[0]} · {secs}s")

    def _hide_activity(self):
        self._activity_timer.stop()
        self._activity_label.hide()
        self._activity_label.setText("")

    # ── 审批卡片（目录外写入）──
    def _on_approval(self, code, paths, reason):
        self._remove_approval_card()
        card = QFrame()
        card.setStyleSheet("""
            QFrame { background-color: rgba(255,255,255,235);
                     border-radius: 12px; }
            QLabel { color: #1F2430; font-size: 12px; background: transparent; }
        """)
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 10)
        box.addWidget(QLabel(f"✋ 她想写入工作目录外的文件："))
        for pth in paths:
            box.addWidget(QLabel(f"· {pth}"))
        row = QHBoxLayout()
        row.addStretch()
        allow = QPushButton("允许")
        deny = QPushButton("拒绝")
        for b in (allow, deny):
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoDefault(False)  # Enter 不得误触审批按钮
            b.setStyleSheet(
                "QPushButton { border: none; border-radius: 8px;"
                " padding: 5px 16px; font-size: 12px; }")
        allow.setStyleSheet(allow.styleSheet() +
                            "background-color: #2E9E57; color: white;")
        deny.setStyleSheet(deny.styleSheet() +
                           "background-color: #C9C4BB; color: #1F2430;")
        allow.clicked.connect(lambda: self._answer_approval(True))
        deny.clicked.connect(lambda: self._answer_approval(False))
        row.addWidget(allow)
        row.addWidget(deny)
        box.addLayout(row)
        self._approval_host.addWidget(card)
        self._approval_card = card

    def _answer_approval(self, allowed: bool):
        self._remove_approval_card()
        self.approval_answered.emit(allowed)

    def _remove_approval_card(self):
        if self._approval_card is not None:
            self._approval_card.deleteLater()
            self._approval_card = None

    # ── 背景图 ──
    def _load_bg(self, path: str):
        self._pixmap = QPixmap(path) if path else None
        self.update()

    def _on_pick_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择房间背景图", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        saved = save_room_bg(self.room["key"], path, friend_id=self.friend_id)
        if saved:
            self._load_bg(saved)
            self.room["bg_path"] = saved

    # ── 任务中断（与主界面同款）──
    def _stop_current_worker(self):
        w = self.ai_worker
        if w is None:
            return
        import warnings
        for sig in ("finished", "failed", "approval_requested", "activity"):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Failed to disconnect.*")
                try:
                    getattr(w, sig).disconnect()
                except RuntimeError:
                    pass
        w.cancel()
        if not w.wait(200):
            self._retired_workers.append(w)
        self.ai_worker = None
        self._remove_approval_card()
        self._hide_activity()

    # ── 轮次号（与主界面同规则）──
    def _next_round_index(self) -> int:
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (self.friend_id,)).fetchone()
        return (row[0] or 0) + 1

    def _current_round_index(self) -> int:
        conn = Database.get_connection()
        row = conn.execute(
            "SELECT MAX(round_index) FROM chat_messages WHERE friend_id=?",
            (self.friend_id,)).fetchone()
        return row[0] or 1

    def closeEvent(self, event):
        self._stop_current_worker()
        get_player().stop()
        # close() 不发 QDialog.finished（只有 done()/accept() 才发），
        # 而离开房间/点 X 都走 close —— 手动补发，主界面靠它刷新聊天区
        self.finished.emit(self.result())
        super().closeEvent(event)
