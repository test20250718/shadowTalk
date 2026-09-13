# shadowtalk/ui/widgets/chat_area.py
"""
ShadowTalk 聊天区域
设计参考：shadowtalk-chat.html — 80px 头部 + 消息列表 + 圆角输入框
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout,
    QListWidget, QListWidgetItem, QFrame, QLabel, QScrollArea,
    QApplication
)
from PySide6.QtCore import Signal, Qt, QSize, QTimer, QElapsedTimer
from PySide6.QtGui import QFont, QColor
from shadowtalk.ui.widgets.message_bubble import (
    MessageBubble, DayDivider, TypingIndicator, ApprovalCard
)
from shadowtalk.config.i18n import tr
from shadowtalk.ui.theme import current as theme_current
from shadowtalk.config.settings import Settings
from shadowtalk.core.tts_service import resolve_voice
from shadowtalk.ui.widgets.tts_player import get_player


class MessageList(QListWidget):
    """消息列表：视口宽度变化时同步所有 item 的 sizeHint 并强制重布局。

    QListWidget 默认 Fixed 布局模式，item 尺寸提示只在插入时生效；
    窗口切全屏/拖宽后旧 item 不会变宽（用户报告：切全屏气泡不铺满），
    必须在 resizeEvent 里重算 sizeHint 并调 doItemsLayout() 重同步 itemWidget 几何。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 每次视图尺寸变化都重新布局（配合 resizeEvent 的 sizeHint 重算）
        self.setResizeMode(QListWidget.Adjust)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.viewport().width()
        for i in range(self.count()):
            item = self.item(i)
            widget = self.itemWidget(item)
            if widget is None:
                continue
            if widget.hasHeightForWidth():
                item.setSizeHint(QSize(w, widget.heightForWidth(w)))
            else:
                # 分隔线/加载动画等固定高度项：只更新宽度
                item.setSizeHint(QSize(w, item.sizeHint().height()))
        self.doItemsLayout()



class ChatArea(QWidget):
    message_sent = Signal(str)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading_item = None
        self._approval_card = None
        self._current_friend_id = None
        self._avatar_name = ""
        self._avatar_path = ""
        self._friend_voice = ""
        # 工作过程卡：活动文字 + 计时器（AI 干活时可见，防"感觉卡死"）
        self._activity_label = None
        self._activity_timer = None
        self._activity_text = ""
        self._activity_clock = None
        self._player = get_player()
        self._player.playback_started.connect(self._on_player_started)
        self._player.playback_finished.connect(self._on_player_finished)
        self._player.playback_failed.connect(self._on_player_failed)
        self._player.synthesis_failed.connect(self._on_player_synth_failed)
        self._build_ui()
        # 全局事件过滤：点击面板外部任意处（消息列表/发送按钮/滚动条等）收起面板
        QApplication.instance().installEventFilter(self)

    def closeEvent(self, event):
        """关闭时注销全局事件过滤器，避免 PySide6 保活 wrapper 导致实例泄漏"""
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def set_friend_info(self, friend_id: int, name: str, avatar_path: str = "", voice: str = ""):
        """设置当前好友信息"""
        self._friend_voice = voice
        self._current_friend_id = friend_id
        self._avatar_name = name
        self._avatar_path = avatar_path
        self._header_avatar.set_avatar(name, avatar_path)
        self._header_name.setText(name)
        self._header_name2.setText(name)
        self._header_status.setText(tr("在线 · 消息仅保存在本机"))

    def set_frozen(self, frozen: bool):
        """设置冻结态（授权作废后禁用输入 + 显示提示条）。"""
        self.input_box.setReadOnly(frozen)
        self.send_btn.setEnabled(not frozen)
        if frozen:
            self.input_box.setPlaceholderText(tr("该分身已被创作者取消授权，无法继续聊天"))
        else:
            self.input_box.setPlaceholderText(tr("输入消息，Enter 发送，Shift+Enter 换行"))

    def show_empty_state(self):
        """无选中好友：隐藏头部/消息列表/输入区，聊天区显示空白（微信风格）"""
        self._header.hide()
        self.message_list.hide()
        self._composer_wrap.hide()

    def show_conversation(self):
        """选中好友：恢复头部/消息列表/输入区"""
        self._header.show()
        self.message_list.show()
        self._composer_wrap.show()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 头部 ──
        self._header = QFrame()
        self._header.setFixedHeight(80)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        header_layout.setSpacing(13)

        # 左侧：头像 + 名称
        from shadowtalk.ui.widgets.message_bubble import AvatarLabel
        self._header_avatar = AvatarLabel("", "", 42)
        header_layout.addWidget(self._header_avatar)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.setContentsMargins(0, 12, 0, 0)
        self._header_name = QLabel(tr("影聊"))
        name_font = QFont()
        name_font.setPointSize(19)
        name_font.setBold(False)
        self._header_name.setFont(name_font)
        title_col.addWidget(self._header_name)

        self._header_status = QLabel(tr("选择一个联系人开始对话"))
        status_font = QFont()
        status_font.setPointSize(12)
        self._header_status.setFont(status_font)
        title_col.addWidget(self._header_status)
        header_layout.addLayout(title_col)

        header_layout.addStretch()

        # 右侧：语音开关（🔊/🔇）；主题切换已移至顶部工具栏
        tts_on = Settings.get("tts_auto_play") == "1"
        self._tts_toggle = QPushButton("🔊" if tts_on else "🔇")
        self._tts_toggle.setFixedSize(36, 36)
        self._tts_toggle.setCursor(Qt.PointingHandCursor)
        self._tts_toggle.setCheckable(True)
        self._tts_toggle.setChecked(tts_on)
        self._tts_toggle.setToolTip(
            tr("语音朗读：开（点击关闭）") if tts_on else tr("语音朗读：关（点击开启）")
        )
        self._tts_toggle.clicked.connect(self._on_tts_toggle)
        header_layout.addWidget(self._tts_toggle, 0, Qt.AlignVCenter)

        header_layout.addSpacing(8)
        layout.addWidget(self._header)

        # ── 消息列表 ──
        self.message_list = MessageList()
        self.message_list.setSpacing(8)
        self.message_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_list.verticalScrollBar().setSingleStep(20)
        layout.addWidget(self.message_list)

        # ── 输入区 ──
        self._composer_wrap = QFrame()
        self._composer_wrap.setStyleSheet("background: transparent;")
        composer_layout = QVBoxLayout(self._composer_wrap)
        composer_layout.setContentsMargins(20, 0, 20, 12)
        composer_layout.setSpacing(0)

        # 输入框容器（圆角卡片）
        self._input_card = QFrame()
        input_layout = QHBoxLayout(self._input_card)
        input_layout.setContentsMargins(10, 4, 6, 4)
        input_layout.setSpacing(6)

        # 表情按钮（位于输入框左侧）
        self.emoji_btn = QPushButton("😊")
        self.emoji_btn.setFixedSize(30, 30)
        self.emoji_btn.setCursor(Qt.PointingHandCursor)
        self.emoji_btn.setToolTip(tr("表情"))
        self.emoji_btn.setCheckable(True)
        self.emoji_btn.clicked.connect(self._toggle_emoji_panel)
        input_layout.addWidget(self.emoji_btn, 0, Qt.AlignVCenter)

        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText(tr("输入消息，Enter 发送，Shift+Enter 换行"))
        self.input_box.setFixedHeight(60)
        self.input_box.setFrameStyle(0)  # 去掉 QTextEdit 内建边框
        self.input_box.document().setDocumentMargin(0)
        self.input_box.setViewportMargins(0, 0, 0, 0)
        self.input_box.installEventFilter(self)
        input_layout.addWidget(self.input_box, 1, Qt.AlignVCenter)

        # 发送按钮
        self.send_btn = QPushButton(tr("发送"))
        self.send_btn.setFixedSize(44, 22)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn, 0, Qt.AlignVCenter)

        # 表情面板（默认隐藏，位于输入卡片上方）
        from shadowtalk.ui.widgets.emoji_panel import EmojiPanel
        self.emoji_panel = EmojiPanel()
        self.emoji_panel.hide()
        self.emoji_panel.emoji_selected.connect(self._on_emoji_selected)
        composer_layout.addWidget(self.emoji_panel, 0, Qt.AlignLeft)

        composer_layout.addWidget(self._input_card)
        layout.addWidget(self._composer_wrap)

        self._apply_styles()

    def _apply_styles(self):
        """按当前主题重设全部容器样式（_build_ui 与 restyle 共用）"""
        t = theme_current()
        self.setStyleSheet(f"background-color: {t.BG}; border: none;")
        self._header.setStyleSheet(
            f"background-color: {t.SURFACE}; border-bottom: 1px solid {t.BORDER};"
        )
        self._header_name.setStyleSheet(f"color: {t.FG};")
        self._header_status.setStyleSheet(f"color: {t.MUTED};")
        # 语音开关样式（透明底 + 圆角 hover）；主题切换已移至工具栏
        header_icon_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                font-size: 18px;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {t.BORDER};
            }}
        """
        self._tts_toggle.setStyleSheet(header_icon_style)
        self.message_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {t.BG};
                border: none;
                padding: 16px 0 8px;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QListWidget::item:selected {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {t.SCROLL_HANDLE};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {t.SCROLL_HANDLE_HOVER};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                height: 0px;
            }}
        """)
        self._input_card.setStyleSheet(f"""
            QFrame {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
            }}
        """)
        self.emoji_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
            }}
            QPushButton:checked {{
                background-color: {t.ACCENT_SOFT};
            }}
        """)
        self.input_box.setStyleSheet(f"""
            QTextEdit {{
                background-color: transparent;
                border: none;
                padding: 0px 4px;
                font-size: 13px;
                color: {t.FG};
                selection-background-color: {t.ACCENT_SOFT};
            }}
            QTextEdit::placeholder {{
                color: {t.MUTED};
            }}
        """)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.ACCENT};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {t.ACCENT_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {t.SCROLL_HANDLE};
                color: {t.SURFACE};
            }}
        """)

    def restyle(self):
        """主题切换后按当前主题重设容器样式（spec 3.4）"""
        self._apply_styles()
        # 头部头像重绘（默认变体按当前主题取底/字色）
        self._header_avatar.set_avatar(self._avatar_name, self._avatar_path)
        self.emoji_panel.restyle()

    def eventFilter(self, obj, event):
        """Enter 发送，Shift+Enter 换行；点击面板外部收起表情面板"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.MouseButtonPress:
            # 真实点击时全局过滤器收到的第一个事件 obj 是 QWindow（顶层窗口），
            # 无法用 obj 身份判断点击目标，改用全局坐标判断是否落在面板矩形内。
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QRect, QPoint
            inside_panel = False
            if isinstance(event, QMouseEvent):
                gp = event.globalPosition().toPoint()
                tl = self.emoji_panel.mapToGlobal(QPoint(0, 0))
                panel_rect = QRect(tl, self.emoji_panel.size())
                inside_panel = panel_rect.contains(gp)
            if (self.emoji_panel.isVisible()
                    and obj is not self.emoji_btn  # 笑脸按钮由 clicked 负责切换
                    and not inside_panel):  # 点击面板（含子按钮）不收起
                self.emoji_panel.hide()
                self.emoji_btn.setChecked(False)
            return super().eventFilter(obj, event)
        if obj is self.input_box and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False
                else:
                    self._on_send()
                    return True
        return super().eventFilter(obj, event)

    def _on_send(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        self.message_sent.emit(text)
        self.input_box.clear()

    def _toggle_emoji_panel(self):
        """切换表情面板显示状态"""
        visible = not self.emoji_panel.isVisible()
        self.emoji_panel.setVisible(visible)
        self.emoji_btn.setChecked(visible)

    def _on_emoji_selected(self, emoji: str):
        """点击表情 → 插入输入框光标处"""
        self.input_box.setFocus()
        cursor = self.input_box.textCursor()
        cursor.insertText(emoji)
        self.input_box.setTextCursor(cursor)

    def add_message(self, text: str, role: str, timestamp: str, msg_id: int = 0):
        """添加一条消息气泡（role: user | ai | human）。"""
        if role == "user":
            bubble = MessageBubble(
                text, role, timestamp,
                avatar_name=tr("我"), avatar_path="", avatar_variant="soft",
                msg_id=msg_id
            )
        else:
            # AI / 真人回信：头像在左，气泡在右
            bubble = MessageBubble(
                text, role, timestamp,
                avatar_name=self._avatar_name,
                avatar_path=self._avatar_path,
                avatar_variant="default",
                msg_id=msg_id
            )
            # 仅 AI 消息可播放语音（真人回信不播放）
            if role == "ai":
                bubble.play_requested.connect(self._on_play_requested)
                bubble.stop_requested.connect(self._on_stop_requested)
        item = QListWidgetItem()
        width = self.message_list.viewport().width()
        item.setSizeHint(QSize(width, bubble.heightForWidth(width)))
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, bubble)
        self.message_list.scrollToBottom()

    def show_approval_card(self, paths, reason, on_answer):
        """显示写文件确认卡片（AI 请求目录外写入时）

        on_answer: 用户点击后的回调（允许/拒绝布尔值）
        """
        card = ApprovalCard(paths, reason)
        card.approved.connect(on_answer)
        item = QListWidgetItem()
        width = self.message_list.viewport().width()
        item.setSizeHint(QSize(width, card.heightForWidth(width)))
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, card)
        self._approval_card = card  # 保留引用，防止被回收
        self.message_list.scrollToBottom()

    def add_day_divider(self, text: str = None):
        if text is None:
            text = tr("今天")
        """添加日期分隔线"""
        divider = DayDivider(text)
        item = QListWidgetItem()
        item.setSizeHint(QSize(self.message_list.viewport().width(), 36))
        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, divider)

    def show_loading(self):
        """显示打字动画 + 工作过程卡（活动文字/计时随任务刷新）"""
        self._remove_loading_item()  # 中断场景：旧任务卡死时再次 loading 先移除旧项
        indicator = TypingIndicator()
        indicator.start()
        item = QListWidgetItem()
        item.setSizeHint(QSize(self.message_list.viewport().width(), 50))

        # 把动画指示器包在头像行里
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(26, 6, 26, 6)
        row_layout.setSpacing(10)

        from shadowtalk.ui.widgets.message_bubble import AvatarLabel
        avatar = AvatarLabel(self._avatar_name, self._avatar_path, 32, variant="default")
        row_layout.addWidget(avatar, 0, Qt.AlignBottom)
        row_layout.addWidget(indicator, 0, Qt.AlignBottom)

        t = theme_current()
        self._activity_label = QLabel(tr("正在思考…"))
        self._activity_label.setStyleSheet(
            f"color: {t.MUTED}; font-size: 12px; background: transparent;")
        row_layout.addWidget(self._activity_label, 0, Qt.AlignBottom)
        row_layout.addStretch()

        self.message_list.addItem(item)
        self.message_list.setItemWidget(item, row)
        self._loading_item = item
        self.send_btn.setEnabled(False)
        self._activity_text = ""
        self._activity_clock = QElapsedTimer()
        self._activity_clock.start()
        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(self._refresh_activity)
        self._activity_timer.start(1000)
        self.message_list.scrollToBottom()

    def update_activity(self, text: str):
        """更新工作卡活动文字（AIWorker.activity → 此处；迟到信号安全忽略）"""
        self._activity_text = text
        if self._activity_label is not None:
            self._activity_label.setText(text)

    def _refresh_activity(self):
        """计时器每秒刷新：活动文字 + 累计耗时（无更新也在动 = 没卡死）"""
        if self._activity_label is None or self._activity_clock is None:
            return
        secs = self._activity_clock.elapsed() // 1000
        self._activity_label.setText(f"{self._activity_text or tr('正在思考…')} · {secs}s")

    def hide_loading(self):
        self._remove_loading_item()
        self.send_btn.setEnabled(True)

    def _remove_loading_item(self):
        """从列表移除当前 loading 项并复位引用（幂等），停掉活动计时"""
        if self._loading_item:
            row = self.message_list.row(self._loading_item)
            self.message_list.takeItem(row)
            self._loading_item = None
        self._stop_activity()

    def _stop_activity(self):
        if self._activity_timer is not None:
            self._activity_timer.stop()
            self._activity_timer = None
        self._activity_label = None
        self._activity_text = ""
        self._activity_clock = None

    def remove_approval_card(self):
        """移除展示中的审批确认卡片（中断旧任务时调用，幂等）"""
        if self._approval_card is None:
            return
        for i in range(self.message_list.count()):
            if self.message_list.itemWidget(self.message_list.item(i)) is self._approval_card:
                self.message_list.takeItem(i)
                break
        self._approval_card = None

    def clear_messages(self):
        """清空消息列表并复位 loading 状态（切换/删除好友时调用）

        直接 message_list.clear() 会销毁 loading item 但不同步
        _loading_item，导致旧 AIWorker 回复到达时 hide_loading() 访问
        已删除的 C++ 对象而崩溃（RuntimeError）。
        """
        self._player.stop()
        self.message_list.clear()
        self._loading_item = None
        self.send_btn.setEnabled(True)
        self._stop_activity()

    def _on_tts_toggle(self, checked: bool):
        """头部语音开关：开/关自动朗读"""
        Settings.set("tts_auto_play", "1" if checked else "0")
        if checked:
            self._tts_toggle.setText("🔊")
            self._tts_toggle.setToolTip(tr("语音朗读：开（点击关闭）"))
        else:
            self._tts_toggle.setText("🔇")
            self._tts_toggle.setToolTip(tr("语音朗读：关（点击开启）"))

    def _on_play_requested(self, text: str, msg_id: int):
        """气泡按钮点播"""
        self._play_text(text, msg_id)

    def _on_stop_requested(self, msg_id: int):
        """播放中再点按钮 → 停止（规格 5.2）"""
        self._player.stop()

    def auto_play_ai_reply(self, text: str, msg_id: int):
        """AI 回复渲染后自动朗读（由 main_window 调用）"""
        self._play_text(text, msg_id)

    def _play_text(self, text: str, msg_id: int):
        voice = resolve_voice(self._friend_voice, Settings.get("tts_voice"))
        self._player.play(text, voice, msg_id)

    def _find_bubble(self, msg_id: int):
        """按消息 ID 找气泡 widget；找不到返回 None"""
        for i in range(self.message_list.count()):
            w = self.message_list.itemWidget(self.message_list.item(i))
            if getattr(w, "msg_id", None) == msg_id:
                return w
        return None

    def _on_player_started(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(True)

    def _on_player_finished(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)

    def _on_player_failed(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)
        self.status_message.emit(tr("语音播放失败，已清除缓存，可重试"))

    def _on_player_synth_failed(self, msg_id: int):
        b = self._find_bubble(msg_id)
        if b is not None:
            b.set_playing(False)
        self.status_message.emit(tr("语音合成失败，请检查网络"))

    def resizeEvent(self, event):
        """气泡宽度跟随窗口：高度按当前宽度重算（heightForWidth），
        避免换行增多后 item 高度不足导致尾部文字被裁剪"""
        super().resizeEvent(event)
        width = self.message_list.viewport().width()
        for i in range(self.message_list.count()):
            item = self.message_list.item(i)
            widget = self.message_list.itemWidget(item)
            if widget:
                item.setSizeHint(QSize(width, widget.heightForWidth(width)))

    # 兼容旧代码的内部引用
    @property
    def _header_name2(self):
        return self._header_name

    @_header_name2.setter
    def _header_name2(self, val):
        pass
