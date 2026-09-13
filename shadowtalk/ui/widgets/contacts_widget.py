# shadowtalk/ui/widgets/contacts_widget.py
"""
联系人管理页（参考 Outlook "People" / 163 网页版通讯录的精简版）。

顶部工具栏：搜索框 + 新建/写信/编辑/删除按钮；
列表行：头像 + 名称 + 地址 + 往来次数/最近时间；
双击联系人 = 直接打开写信（发给 TA）。

数据来自 mail_contacts 表（收发邮件自动累计），也支持手动新建。
新增/编辑/删除在组件内完成（自带确认与表单对话框），
写信通过 compose_requested 信号交给 MainWindow（需接入发送链路）。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QDialog,
    QDialogButtonBox, QFormLayout,
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QFont

from shadowtalk.ui.theme import current as theme_current
from shadowtalk.ui.widgets.message_bubble import AvatarLabel
from shadowtalk.data.repositories import MailContactRepository
from shadowtalk.config.i18n import tr


class ContactEditDialog(QDialog):
    """新建/编辑联系人表单（编辑模式仅可改名称，地址是身份不可变）。"""

    def __init__(self, parent=None, contact: dict | None = None):
        super().__init__(parent)
        self._contact = contact  # None = 新建
        self.setWindowTitle(tr("编辑联系人") if contact else tr("新建联系人"))
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self):
        t = theme_current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("显示名称（可选）"))
        form.addRow(tr("名称："), self.name_input)

        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText("name@example.com")
        if self._contact:
            # 编辑模式：地址即身份（主键），改名不换人
            self.addr_input.setText(self._contact.get("address", ""))
            self.addr_input.setReadOnly(True)
        form.addRow(tr("地址："), self.addr_input)

        layout.addLayout(form)

        tip = QLabel(tr("联系人的往来频率会随收发邮件自动累计") if not self._contact
                     else tr("如需更换地址，请删除后重新新建"))
        tip.setObjectName("tip")
        layout.addWidget(tip)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText(tr("保存"))
        btns.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        if self._contact:
            self.name_input.setText(self._contact.get("name", ""))

        self.setStyleSheet(f"""
            QDialog {{ background-color: {t.SURFACE}; color: {t.FG}; }}
            QLabel {{ color: {t.FG}; font-size: 13px; }}
            QLabel#tip {{ color: {t.MUTED}; font-size: 11px; }}
            QLineEdit {{
                background-color: {t.SURFACE}; color: {t.FG};
                border: 1px solid {t.BORDER}; border-radius: 8px;
                padding: 6px 10px; font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {t.ACCENT}; }}
        """)

    def _on_save(self):
        addr = self.addr_input.text().strip()
        if not self._contact:
            # 新建模式校验地址；编辑模式地址只读无需校验
            if not addr or "@" not in addr:
                QMessageBox.warning(self, tr("提示"), tr("请填写有效的邮件地址"))
                return
            if MailContactRepository.add_manual_contact(addr, self.name_input.text().strip()):
                self.accept()
            else:
                exists_msg = tr("该地址已存在：\n") + addr
                QMessageBox.warning(self, tr("提示"), exists_msg)
        else:
            MailContactRepository.rename_contact(
                self._contact["address"], self.name_input.text())
            self.accept()


class _ContactListItem(QWidget):
    """联系人列表行：头像 + 名称 + 地址 | 次数 · 最近时间。"""

    def __init__(self, contact: dict, parent=None):
        super().__init__(parent)
        self._contact = contact
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        name = self._contact.get("name", "") or ""
        addr = self._contact.get("address", "") or "?"
        avatar = AvatarLabel(name or addr, "", size=38, variant="soft")
        layout.addWidget(avatar)

        center = QVBoxLayout()
        center.setSpacing(2)
        name_label = QLabel(name if name else addr)
        name_label.setObjectName("contactName")
        font = QFont()
        font.setBold(True)
        name_label.setFont(font)
        center.addWidget(name_label)
        if name:  # 有名称才显示第二行地址，避免重复
            addr_label = QLabel(addr)
            addr_label.setObjectName("contactAddr")
            center.addWidget(addr_label)
        layout.addLayout(center, 1)

        freq = self._contact.get("frequency", 0)
        last = (self._contact.get("last_seen", "") or "")[:10]
        right_text = f"{tr('往来')}{freq}{tr(' 次')}" + (f" · {last}" if last else "")
        right = QLabel(right_text)
        right.setObjectName("contactMeta")
        right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(right)

    def apply_style(self):
        t = theme_current()
        for label in self.findChildren(QLabel):
            if label.objectName() == "contactName":
                label.setStyleSheet(f"color: {t.FG}; font-size: 14px; font-weight: bold;")
            elif label.objectName() == "contactAddr":
                label.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
            elif label.objectName() == "contactMeta":
                label.setStyleSheet(f"color: {t.MUTED}; font-size: 11px;")


class ContactsWidget(QWidget):
    """联系人管理页（嵌在邮箱页内部，带返回邮件按钮）。"""

    compose_requested = Signal(str)   # 写信（地址），MainWindow 接发送链路
    back_requested = Signal()         # 返回邮件列表视图

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = None   # 当前选中联系人 dict
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 工具栏 ──
        toolbar = QFrame()
        toolbar.setObjectName("contactsToolbar")
        toolbar.setFixedHeight(52)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 0, 12, 0)
        tb.setSpacing(8)

        # 返回邮件列表（本页嵌在邮箱页内，同页视图切换）
        self.back_btn = QPushButton("← 返回邮件")
        self.back_btn.setObjectName("contactBackBtn")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(lambda: self.back_requested.emit())
        tb.addWidget(self.back_btn)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 " + tr("搜索名称或地址…"))
        self.search_input.setFixedHeight(32)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.reload)
        tb.addWidget(self.search_input, 1)

        self.add_btn = QPushButton("➕ 新建")
        self.add_btn.setObjectName("contactAddBtn")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._on_add)
        tb.addWidget(self.add_btn)

        # 选中后可用的操作
        self.compose_btn = QPushButton("✉️ 写信")
        self.compose_btn.setObjectName("contactComposeBtn")
        self.compose_btn.setCursor(Qt.PointingHandCursor)
        self.compose_btn.setEnabled(False)
        self.compose_btn.clicked.connect(self._on_compose)
        tb.addWidget(self.compose_btn)

        self.edit_btn = QPushButton("✏️ 编辑")
        self.edit_btn.setObjectName("contactEditBtn")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._on_edit)
        tb.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("🗑️ 删除")
        self.delete_btn.setObjectName("contactDeleteBtn")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete)
        tb.addWidget(self.delete_btn)

        layout.addWidget(toolbar)

        # ── 联系人列表 ──
        self.list = QListWidget()
        self.list.setObjectName("contactsList")
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemDoubleClicked.connect(
            lambda _: self._on_compose())  # 双击直接写信
        layout.addWidget(self.list, 1)

        # ── 空态提示 ──
        self.empty_label = QLabel(
            tr("暂无联系人\n\n收发邮件后会自动从邮件中提取，\n也可以点右上角「➕ 新建」手动添加"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("contactsEmpty")
        layout.addWidget(self.empty_label, 1)
        self.empty_label.hide()

        self._apply_styles()

    # ---- 数据 ----

    def reload(self, keyword: str = ""):
        """重新加载列表（带搜索关键字）。"""
        self._selected = None
        self.compose_btn.setEnabled(False)
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        contacts = MailContactRepository.search_contacts(keyword or "")
        self.list.clear()
        self.empty_label.setVisible(not contacts)
        self.list.setVisible(bool(contacts))
        for c in contacts:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
            widget = _ContactListItem(c)
            widget.apply_style()
            self.list.setItemWidget(item, widget)

    # ---- 交互 ----

    def _on_item_clicked(self, item: QListWidgetItem):
        contact = item.data(Qt.UserRole)
        if not contact:
            return
        self._selected = contact
        self.compose_btn.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _on_compose(self):
        if self._selected:
            self.compose_requested.emit(self._selected.get("address", ""))

    def _on_add(self):
        dlg = ContactEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.reload(self.search_input.text())

    def _on_edit(self):
        if not self._selected:
            return
        dlg = ContactEditDialog(self, contact=self._selected)
        if dlg.exec() == QDialog.Accepted:
            self.reload(self.search_input.text())

    def _on_delete(self):
        if not self._selected:
            return
        addr = self._selected.get("address", "")
        name = self._selected.get("name", "") or addr
        reply = QMessageBox.question(
            self, tr("删除联系人"),
            tr("确定删除联系人吗？\n\n") + f"{name}\n{addr}\n\n"
            + "（不影响已收到的邮件；若日后再有往来会重新自动记录）",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            MailContactRepository.delete_contact(addr)
            self.reload(self.search_input.text())

    # ---- 样式 ----

    def _apply_styles(self):
        t = theme_current()
        self.setStyleSheet(f"background-color: {t.BG};")
        toolbar = self.findChild(QFrame, "contactsToolbar")
        if toolbar:
            toolbar.setStyleSheet(
                f"background-color: {t.SURFACE}; "
                f"border-bottom: 1px solid {t.BORDER};")

        btn_style = (
            f"QPushButton{{background-color: {t.SURFACE}; color: {t.FG}; "
            f"border: 1px solid {t.BORDER}; border-radius: 6px; "
            f"padding: 4px 14px; font-size: 13px;}}"
            f"QPushButton:hover{{background-color: {t.BG}; border-color: {t.MUTED};}}"
            f"QPushButton:disabled{{color: {t.MUTED}; border-color: {t.BORDER};}}"
        )
        for btn in (self.back_btn, self.add_btn, self.compose_btn,
                    self.edit_btn, self.delete_btn):
            btn.setStyleSheet(btn_style)

        self.search_input.setStyleSheet(
            f"QLineEdit{{background-color: {t.SURFACE}; color: {t.FG}; "
            f"border: 1px solid {t.BORDER}; border-radius: 16px; "
            f"padding: 0 14px; font-size: 13px;}}"
            f"QLineEdit:focus{{border-color: {t.ACCENT};}}")

        self.list.setStyleSheet(f"""
            QListWidget {{
                background-color: {t.SURFACE};
                border: none; outline: none; padding: 4px 0;
            }}
            QListWidget::item {{
                background-color: {t.SURFACE};
                border: none; border-bottom: 1px solid {t.BORDER};
            }}
            QListWidget::item:hover {{ background-color: {t.BG}; }}
            QListWidget::item:selected {{ background-color: {t.ACCENT_SOFT}; }}
        """)

        self.empty_label.setStyleSheet(
            f"color: {t.MUTED}; font-size: 14px;")

    def restyle(self):
        """主题切换后由 MainWindow 调用。"""
        self._apply_styles()
        for i in range(self.list.count()):
            widget = self.list.itemWidget(self.list.item(i))
            if isinstance(widget, _ContactListItem):
                widget.apply_style()
