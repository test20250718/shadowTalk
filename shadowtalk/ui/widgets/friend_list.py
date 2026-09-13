# shadowtalk.ui.widgets.friend_list.py
"""
ShadowTalk 好友列表（侧边栏）
设计参考：shadowtalk-chat.html — 品牌栏 + 搜索 + 会话列表 + 操作按钮
"""
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QHBoxLayout, QWidget, QMessageBox, QFrame, QLabel, QLineEdit
)
from PySide6.QtCore import Signal, Qt, QSize, QRect
from PySide6.QtGui import QFont, QColor
from shadowtalk.ui.widgets.message_bubble import AvatarLabel
from shadowtalk.ui.theme import current as theme_current
from shadowtalk.config.paths import resource_path
from shadowtalk.config.i18n import tr, on_language_changed

LOGO_PATH = resource_path("resources/shadowtalk_logo.png")


class FriendListWidget(QWidget):
    friend_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit_callback = None
        self._delete_callback = None
        self._room_callback = None
        self._import_callback = None
        self._last_messages = {}  # friend_id → (text, time)
        self._all_friends = []    # 缓存好友数据用于搜索
        self._friend_items = {}   # friend_id → _ConversationItem
        self._build_ui()

    def _build_ui(self):
        self.setMinimumWidth(240)
        self.resize(328, self.height())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 品牌头部（已移除：搜索框上方的 logo + "影聊 · 私密对话"）──
        # 保留引用防止外部调用报错，但不再显示
        self._header = None
        self._brand_mark = None
        self._brand_sub = None

        # ── 搜索框 + 添加好友按钮 ──
        search_frame = QFrame()
        search_frame.setFixedHeight(60)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(20, 0, 20, 14)
        search_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("搜索联系人"))
        self.search_input.setFixedHeight(42)
        self.search_input.textChanged.connect(self._on_search)
        # 语言切换时即时刷新搜索框/标签/按钮提示文本
        on_language_changed(self._retranslate_ui)
        search_layout.addWidget(self.search_input, 1)

        # 添加好友按钮：紧跟在搜索框右侧，与搜索框等高
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(42, 42)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setToolTip(tr("新增联系人"))
        self.add_btn.clicked.connect(self._on_add)
        search_layout.addWidget(self.add_btn)
        layout.addWidget(search_frame)

        # ── 联系人标签 ──
        label_row = QFrame()
        label_row.setFixedHeight(33)
        label_layout = QHBoxLayout(label_row)
        label_layout.setContentsMargins(22, 0, 22, 0)
        self._contact_label = QLabel(tr("联系人"))
        label_layout.addWidget(self._contact_label)
        label_layout.addStretch()
        self._count_label = QLabel(f"0{tr(' 位')}")
        label_layout.addWidget(self._count_label)
        layout.addWidget(label_row)

        # ── 会话列表 ──
        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.verticalScrollBar().setSingleStep(20)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        # ── 底部操作按钮（微信风格：扁平图标 + 悬停反馈）──
        self._actions_frame = QFrame()
        self._actions_frame.setFixedHeight(56)
        actions_layout = QHBoxLayout(self._actions_frame)
        actions_layout.setContentsMargins(12, 8, 12, 8)
        actions_layout.setSpacing(4)

        btn_specs = [
            ("✎", tr("编辑联系人"), self._on_edit),
            ("✕", tr("删除联系人"), self._on_delete),
            ("🏠", tr("沉浸式聊天（咖啡馆）"), self._on_room),
        ]
        self.edit_btn, self.del_btn, self.room_btn = \
            None, None, None
        for i, (icon, tip, slot) in enumerate(btn_specs):
            btn = QPushButton(icon)
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            if i == 0:
                self.edit_btn = btn
            elif i == 1:
                self.del_btn = btn
            else:
                self.room_btn = btn
            actions_layout.addWidget(btn)
        actions_layout.addStretch()
        layout.addWidget(self._actions_frame)

        self._apply_styles()

    def _apply_styles(self):
        """按当前主题重设全部容器样式（_build_ui 与 restyle 共用）"""
        t = theme_current()
        self.setStyleSheet(f"""
            background-color: {t.SURFACE};
            QMessageBox {{
                /* 删除确认弹窗以本组件为父级，继承本样式表而非全局 QSS，
                   必须自带深色规则，否则深色模式下白底黑字 */
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QMessageBox QLabel {{
                color: {t.FG};
            }}
            QMessageBox QPushButton {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: 1px solid {t.BORDER};
                border-radius: 6px;
                padding: 5px 18px;
                min-width: 64px;
            }}
            QMessageBox QPushButton:hover {{
                background-color: {t.BG};
                border-color: {t.MUTED};
            }}
        """)
        # 品牌头部已移除，跳过样式设置
        if self._header is not None:
            self._header.setStyleSheet(f"background-color: {t.SURFACE};")
        if self._brand_sub is not None:
            self._brand_sub.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t.BG};
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 0 14px;
                font-size: 14px;
                color: {t.FG};
            }}
            QLineEdit:hover {{
                border-color: {t.BORDER};
            }}
            QLineEdit:focus {{
                border-color: {t.ACCENT};
                background-color: {t.SURFACE};
            }}
            QLineEdit::placeholder {{
                color: {t.MUTED};
            }}
        """)
        self._contact_label.setStyleSheet(
            f"color: {t.MUTED}; font-family: Menlo, monospace; font-size: 11px;"
        )
        self._count_label.setStyleSheet(
            f"color: {t.MUTED}; font-family: Menlo, monospace; font-size: 11px;"
        )
        self.list.setStyleSheet(f"""
            QListWidget {{
                background-color: {t.SURFACE};
                border: none;
                outline: none;
                padding: 0 10px;
            }}
            QListWidget::item {{
                background-color: {t.SURFACE};
                border: none;
                padding: 0px;
                border-radius: 12px;
                margin: 2px 0;
            }}
            QListWidget::item:hover {{
                background-color: {t.BG};
            }}
            QListWidget::item:selected {{
                background-color: {t.ACCENT_SOFT};
            }}
        """)
        self._actions_frame.setStyleSheet(f"border-top: 1px solid {t.BORDER};")
        # 底部操作按钮样式
        for btn in (self.edit_btn, self.del_btn, self.room_btn):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {t.FG};
                    border: none;
                    border-radius: 8px;
                    font-size: 17px;
                }}
                QPushButton:hover {{
                    background-color: {t.BG};
                }}
                QPushButton:pressed {{
                    background-color: {t.BORDER};
                }}
            """)
        # 搜索栏添加好友按钮样式（与搜索框视觉协调）
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.BG};
                color: {t.FG};
                border: 1px solid transparent;
                border-radius: 12px;
                font-size: 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {t.BORDER};
                border-color: {t.ACCENT};
            }}
            QPushButton:pressed {{
                background-color: {t.BORDER};
            }}
        """)

    def restyle(self):
        """主题切换后按当前主题重设容器样式（spec 3.4）"""
        self._apply_styles()

    def _retranslate_ui(self):
        """语言切换后刷新可见文本（搜索框/标签/按钮提示/计数）。"""
        self.search_input.setPlaceholderText(tr("搜索联系人"))
        self.add_btn.setToolTip(tr("新增联系人"))
        self._contact_label.setText(tr("联系人"))
        self._count_label.setText(f"{len(self._all_friends)}{tr(' 位')}")
        if self.edit_btn:
            self.edit_btn.setToolTip(tr("编辑联系人"))
        if self.del_btn:
            self.del_btn.setToolTip(tr("删除联系人"))
        if self.room_btn:
            self.room_btn.setToolTip(tr("沉浸式聊天（咖啡馆）"))

    def resizeEvent(self, event):
        """左栏宽度变化时，同步会话条目宽度"""
        super().resizeEvent(event)
        w = self.list.viewport().width()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setSizeHint(QSize(w - 20, 68))  # -20 留出滚动条+内边距余量

    def _on_search(self, text: str):
        """搜索过滤联系人"""
        query = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            widget = self.list.itemWidget(item)
            if widget and hasattr(widget, '_name'):
                match = query in widget._name.lower()
                item.setHidden(not match)

    def set_last_message(self, friend_id: int, text: str, time_str: str):
        """更新某个好友的最后一条消息：记录字典并同步刷新列表项预览"""
        self._last_messages[friend_id] = (text, time_str)
        widget = self._friend_items.get(friend_id)
        if widget is not None:
            widget.update_preview(text, time_str)

    def _current_friend(self):
        item = self.list.currentItem()
        if not item:
            return None, None
        friend_id = item.data(Qt.UserRole)
        widget = self.list.itemWidget(item)
        name = widget._name if widget else ""
        return friend_id, name

    def _on_add(self):
        pass  # 由 MainWindow 连接

    def _on_import(self):
        """导入网页数字分身资产 —— 具体逻辑由 MainWindow 注入"""
        if self._import_callback:
            self._import_callback()

    def _on_room(self):
        """沉浸式聊天入口 —— 具体逻辑由 MainWindow 注入"""
        if self._room_callback:
            self._room_callback()

    def _on_edit(self):
        friend_id, name = self._current_friend()
        if friend_id is None:
            QMessageBox.warning(self, tr("提示"), tr("请先选择一个好友"))
            return
        if self._edit_callback:
            self._edit_callback(friend_id)

    def _on_delete(self):
        friend_id, name = self._current_friend()
        if friend_id is None:
            QMessageBox.warning(self, tr("提示"), tr("请先选择一个好友"))
            return
        reply = QMessageBox.warning(
            self, tr("确认删除"),
            tr("确定要删除好友") + f" {name} " + tr("吗？\n（聊天记录将一并删除）"),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes and self._delete_callback:
            self._delete_callback(friend_id)

    def _on_item_clicked(self, item):
        friend_id = item.data(Qt.UserRole)
        if friend_id:
            self.friend_selected.emit(friend_id)

    def load_friends(self, friends: list):
        self.list.clear()
        self._all_friends = friends
        self._friend_items = {}
        self._count_label.setText(f"{len(friends)}{tr(' 位')}")
        for friend in friends:
            friend_id = friend["id"]
            last = self._last_messages.get(friend_id, ("", ""))
            display_name = friend["remark"] or friend["name"]
            widget = _ConversationItem(
                display_name, friend["avatar_path"],
                last[0], last[1]
            )
            self._friend_items[friend_id] = widget
            item = QListWidgetItem()
            item.setData(Qt.UserRole, friend_id)
            item.setSizeHint(QSize(self.list.viewport().width(), 68))
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)


class _ConversationItem(QWidget):
    """会话项：头像 + 昵称 + 消息预览 + 时间"""

    def __init__(self, name: str, avatar_path: str,
                 preview: str, time_str: str, parent=None):
        super().__init__(parent)
        self._name = name
        self.setFixedHeight(68)
        self._preview_label = None
        self._time_label = None
        t = theme_current()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)

        # 头像
        avatar = AvatarLabel(name, avatar_path, 44, variant="default")
        layout.addWidget(avatar)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        text_layout.setContentsMargins(0, 8, 0, 0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(name)
        name_font = QFont()
        name_font.setPointSize(14)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet(f"color: {t.FG};")
        top_row.addWidget(name_label)
        top_row.addStretch()
        self._time_label = QLabel(time_str)
        self._time_label.setStyleSheet(
            f"color: {t.MUTED}; font-family: Menlo, monospace; font-size: 10px;"
        )
        top_row.addWidget(self._time_label)
        text_layout.addLayout(top_row)

        self._preview_label = QLabel(preview or "　")
        self._preview_label.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
        text_layout.addWidget(self._preview_label)

        layout.addLayout(text_layout, 1)

    def update_preview(self, preview: str, time_str: str):
        """会话中新消息到达时刷新预览文字与时间（不重建 widget）"""
        self._preview_label.setText(preview or "　")
        self._time_label.setText(time_str)
