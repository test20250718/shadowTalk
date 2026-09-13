# shadowtalk/ui/widgets/mail_compose_dialog.py
"""写信对话框：收件人/主题/正文输入，支持富文本与附件，点击发送后发射 send_requested 信号。

设计要点：
- V1.4 启用富文本 QTextEdit，顶部格式工具栏（B/I/U/S + 字体大小 + 颜色 + 列表 + 链接 + 图片）
- 工具栏分组：字符样式(B/I/U/S) | 字体大小/颜色 | 结构(列表/链接/图片)，组间分隔符
- 附件栏：添加/移除附件，单文件 10MB 限制
- 发送时若有附件，构建 MIMEMultipart MIME 消息（MailMessage.mime_message）
- 信号 send_requested(MailMessage) 由父窗口连接，实际发送逻辑不在对话框内
  （单一职责：对话框只负责收集用户输入并组装 MailMessage）
- 复用 SettingsDialog 的 QSS 风格（圆角输入框、accent 发送按钮），
  保证深色/浅色主题下视觉一致
"""
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTextEdit,
    QPushButton, QHBoxLayout, QLabel, QFrame, QComboBox,
    QColorDialog, QInputDialog, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QDialogButtonBox, QCompleter,
)
from PySide6.QtCore import Signal, Qt, QStringListModel, QSize
from PySide6.QtGui import QTextCharFormat, QFont, QColor, QTextListFormat

from shadowtalk.ui.theme import current as theme_current
from shadowtalk.config.i18n import tr


class MailComposeDialog(QDialog):
    """写信对话框（QDialog），支持富文本和附件。"""

    # 发送请求信号：MailMessage 对象（V1.4 由 (str,str,str) 改为 MailMessage）
    send_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("写信"))
        self.setMinimumSize(480, 560)

        # V1.4-Add：附件列表（文件路径）与内联图片列表
        self._attachments = []      # 普通附件路径列表
        self._inline_images = []    # 内联图片路径列表

        self._build_ui()
        self._apply_styles()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── 收件人（带常用联系人补全 + 选择按钮）──
        to_row = QHBoxLayout()
        to_row.setSpacing(6)
        to_label = QLabel(tr("收件人"))
        to_label.setObjectName("composeFieldLabel")
        to_row.addWidget(to_label)
        self.to_input = QLineEdit()
        self.to_input.setPlaceholderText(tr("例如：friend@example.com（输入自动补全）"))
        to_row.addWidget(self.to_input, 1)
        self.contacts_btn = QPushButton("👥")
        self.contacts_btn.setFixedSize(34, 34)
        self.contacts_btn.setToolTip(tr("从常用联系人选择"))
        self.contacts_btn.setCursor(Qt.PointingHandCursor)
        self.contacts_btn.clicked.connect(self._on_pick_contact)
        to_row.addWidget(self.contacts_btn)
        layout.addLayout(to_row)
        # 输入自动补全（前缀匹配地址；常用联系人按频率排序）
        self._completer_model = QStringListModel()
        self._completer = QCompleter()
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setModel(self._completer_model)
        self.to_input.setCompleter(self._completer)
        self._reload_contacts()

        # ── 主题 ──
        subject_row = QHBoxLayout()
        subject_row.setSpacing(6)
        subject_label = QLabel(tr("主题"))
        subject_label.setObjectName("composeFieldLabel")
        subject_row.addWidget(subject_label)
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText(tr("邮件主题"))
        subject_row.addWidget(self.subject_input, 1)
        layout.addLayout(subject_row)

        # V1.4-Add：格式工具栏（分组 + 分隔符）
        toolbar = self._build_toolbar()
        layout.addWidget(toolbar)

        # V1.4-Add：附件栏（添加/移除附件）
        self._attachment_bar = self._build_attachment_bar()
        layout.addWidget(self._attachment_bar)

        # 正文（V1.4 改为富文本）
        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText(tr("在这里输入邮件正文……"))
        self.body_input.setAcceptRichText(True)  # V1.4：启用富文本
        # 光标位置变化时同步工具栏状态（如加粗/斜体按钮的按下态）
        self.body_input.cursorPositionChanged.connect(self._on_cursor_position_changed)
        layout.addWidget(self.body_input, 1)  # 正文占满剩余空间

        # 底部取消/发送按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton(tr("取消"))
        send_btn = QPushButton(tr("发送"))
        send_btn.setObjectName("sendBtn")  # 用于 QSS 高亮为 accent 色
        cancel_btn.clicked.connect(self.reject)
        send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(send_btn)
        layout.addLayout(btn_row)

    def _build_toolbar(self) -> QFrame:
        """构建格式工具栏（分组 + 分隔符）。

        三组：字符样式(B/I/U/S) | 字体大小/颜色 | 结构(列表/链接/图片)。
        组间用 1px 竖直分隔符隔开，视觉上更清爽。
        """
        toolbar = QFrame()
        toolbar.setObjectName("composeToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(2)

        # ── 第一组：字符样式 ──
        self.bold_btn = QPushButton("B")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setToolTip(tr("加粗 (Ctrl+B)"))
        self.bold_btn.clicked.connect(self._toggle_bold)
        row.addWidget(self.bold_btn)

        self.italic_btn = QPushButton("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setToolTip(tr("斜体 (Ctrl+I)"))
        self.italic_btn.clicked.connect(self._toggle_italic)
        row.addWidget(self.italic_btn)

        self.underline_btn = QPushButton("U")
        self.underline_btn.setCheckable(True)
        self.underline_btn.setToolTip(tr("下划线 (Ctrl+U)"))
        self.underline_btn.clicked.connect(self._toggle_underline)
        row.addWidget(self.underline_btn)

        self.strike_btn = QPushButton("S")
        self.strike_btn.setCheckable(True)
        self.strike_btn.setToolTip(tr("删除线"))
        self.strike_btn.clicked.connect(self._toggle_strike)
        row.addWidget(self.strike_btn)

        # 分隔符
        row.addWidget(self._make_separator())

        # ── 第二组：字体大小 + 颜色 ──
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(["9", "10", "11", "12", "14", "16", "18", "24"])
        self.font_size_combo.setCurrentText("12")
        self.font_size_combo.currentTextChanged.connect(self._on_font_size_changed)
        row.addWidget(self.font_size_combo)

        self.color_btn = QPushButton("🎨")
        self.color_btn.setToolTip(tr("文字颜色"))
        self.color_btn.clicked.connect(self._on_color)
        row.addWidget(self.color_btn)

        # 分隔符
        row.addWidget(self._make_separator())

        # ── 第三组：结构（列表/链接/图片）──
        self.bullet_btn = QPushButton("•")
        self.bullet_btn.setToolTip(tr("无序列表"))
        self.bullet_btn.clicked.connect(self._insert_bullet_list)
        row.addWidget(self.bullet_btn)

        self.number_btn = QPushButton("1.")
        self.number_btn.setToolTip(tr("有序列表"))
        self.number_btn.clicked.connect(self._insert_number_list)
        row.addWidget(self.number_btn)

        self.link_btn = QPushButton("🔗")
        self.link_btn.setToolTip(tr("插入链接"))
        self.link_btn.clicked.connect(self._insert_link)
        row.addWidget(self.link_btn)

        self.image_btn = QPushButton("🖼️")
        self.image_btn.setToolTip(tr("插入图片"))
        self.image_btn.clicked.connect(self._insert_image)
        row.addWidget(self.image_btn)

        row.addStretch()
        return toolbar

    @staticmethod
    def _make_separator() -> QFrame:
        """工具栏分组分隔符（1px 竖线）。"""
        sep = QFrame()
        sep.setObjectName("composeToolbarSep")
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        sep.setFrameShape(QFrame.NoFrame)
        return sep

    def _build_attachment_bar(self) -> QFrame:
        """构建附件栏（添加按钮 + 附件标签列表）。"""
        bar = QFrame()
        bar.setObjectName("composeAttachmentBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.add_attachment_btn = QPushButton("📎 添加附件")
        self.add_attachment_btn.clicked.connect(self._on_add_attachment)
        layout.addWidget(self.add_attachment_btn)
        layout.addStretch()
        # 占位：附件按钮会插入到 stretch 之前
        return bar

    # ---- 格式方法 ----

    def _toggle_bold(self):
        cursor = self.body_input.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if self.bold_btn.isChecked() else QFont.Normal)
        cursor.mergeCharFormat(fmt)

    def _toggle_italic(self):
        cursor = self.body_input.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontItalic(self.italic_btn.isChecked())
        cursor.mergeCharFormat(fmt)

    def _toggle_underline(self):
        cursor = self.body_input.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontUnderline(self.underline_btn.isChecked())
        cursor.mergeCharFormat(fmt)

    def _toggle_strike(self):
        cursor = self.body_input.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(self.strike_btn.isChecked())
        cursor.mergeCharFormat(fmt)

    def _on_font_size_changed(self, text):
        cursor = self.body_input.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(text))
        cursor.mergeCharFormat(fmt)

    def _on_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            cursor = self.body_input.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.mergeCharFormat(fmt)

    def _insert_bullet_list(self):
        cursor = self.body_input.textCursor()
        cursor.insertList(QTextListFormat.ListDisc)

    def _insert_number_list(self):
        cursor = self.body_input.textCursor()
        cursor.insertList(QTextListFormat.ListDecimal)

    def _insert_link(self):
        url, ok = QInputDialog.getText(self, tr("插入链接"), tr("输入 URL："))
        if ok and url:
            cursor = self.body_input.textCursor()
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
            fmt.setForeground(QColor("#0000EE"))
            fmt.setFontUnderline(True)
            cursor.mergeCharFormat(fmt)

    def _insert_image(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, tr("插入图片"), "", "Images (*.png *.jpg *.jpeg *.gif *.bmp)"
        )
        if filepath:
            self._inline_images.append(filepath)
            cursor = self.body_input.textCursor()
            cursor.insertImage(filepath)

    # ---- 附件方法 ----

    def _on_add_attachment(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("选择附件"))
        for f in files:
            size = os.path.getsize(f)
            if size > 10 * 1024 * 1024:
                QMessageBox.warning(self, tr("提示"),
                                    f"{os.path.basename(f)}{tr(' 超过 10MB 限制')}")
                continue
            self._attachments.append(f)
            self._refresh_attachment_bar()

    def _refresh_attachment_bar(self):
        """刷新附件栏显示。保留添加按钮和 stretch，中间插入附件标签。"""
        layout = self._attachment_bar.layout()
        # 清除旧附件按钮（保留 index 0 的 add_attachment_btn 和末尾的 stretch）
        while layout.count() > 2:
            item = layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        for filepath in self._attachments:
            btn = QPushButton(f"📄 {os.path.basename(filepath)} ✕")
            btn.clicked.connect(lambda _=False, f=filepath: self._remove_attachment(f))
            layout.insertWidget(layout.count() - 1, btn)

    def _remove_attachment(self, filepath):
        self._attachments.remove(filepath)
        self._refresh_attachment_bar()

    # ---- 工具栏状态同步 ----

    def _on_cursor_position_changed(self):
        """光标位置变化时更新工具栏状态（如加粗/斜体按钮的按下态）。"""
        fmt = self.body_input.currentCharFormat()
        self.bold_btn.setChecked(fmt.fontWeight() == QFont.Bold)
        self.italic_btn.setChecked(fmt.fontItalic())
        self.underline_btn.setChecked(fmt.fontUnderline())
        self.strike_btn.setChecked(fmt.fontStrikeOut())

    # ---- 常用联系人 ----

    def _reload_contacts(self):
        """加载常用联系人到补全模型（每次打开对话框时调用，取最新）。"""
        from shadowtalk.data.repositories import MailContactRepository
        contacts = MailContactRepository.get_contacts(limit=100)
        # 补全候选：地址 + "名称 <地址>" 两种形式都给（输拼音/名字也能命中）
        candidates = []
        for c in contacts:
            addr = c.get("address", "")
            if not addr:
                continue
            candidates.append(addr)
            name = c.get("name", "")
            if name:
                candidates.append(f"{name} <{addr}>")
        self._completer_model.setStringList(candidates)

    def _on_pick_contact(self):
        """弹出常用联系人列表供点选，选中后填入收件人。"""
        from shadowtalk.data.repositories import MailContactRepository
        contacts = MailContactRepository.get_contacts(limit=200)
        if not contacts:
            QMessageBox.information(self, "常用联系人",
                                    "暂无联系人记录。\n\n收发邮件后会自动从邮件中提取。")
            return

        t = theme_current()
        dlg = QDialog(self)
        dlg.setWindowTitle("选择联系人")
        dlg.setMinimumSize(380, 420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)

        tip = QLabel(f"共 {len(contacts)} 位联系人（按往来频率排序）")
        v.addWidget(tip)

        lst = QListWidget()
        for c in contacts:
            name = c.get("name", "")
            addr = c.get("address", "")
            freq = c.get("frequency", 0)
            display = f"{name}  <{addr}>" if name else f"<{addr}>"
            item = QListWidgetItem(f"{display}   · {freq} 次")
            item.setData(Qt.UserRole, addr)
            item.setSizeHint(QSize(0, 40))
            lst.addItem(item)
        lst.itemDoubleClicked.connect(lambda _: dlg.accept())
        v.addWidget(lst, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {t.SURFACE}; color: {t.FG}; }}
            QLabel {{ color: {t.MUTED}; font-size: 12px; }}
            QListWidget {{
                background-color: {t.SURFACE}; color: {t.FG};
                border: 1px solid {t.BORDER}; border-radius: 8px;
                padding: 4px; font-size: 13px;
            }}
            QListWidget::item {{ padding: 8px; border-radius: 6px; }}
            QListWidget::item:selected {{ background-color: {t.ACCENT_SOFT}; }}
        """)

        if dlg.exec() == QDialog.Accepted:
            item = lst.currentItem()
            if item:
                self.to_input.setText(item.data(Qt.UserRole))

    # ---- 发送 ----

    def _on_send(self):
        """验证字段非空后构建 MailMessage 并发射信号，然后关闭。"""
        to = self.to_input.text().strip()
        subject = self.subject_input.text().strip()
        html_body = self.body_input.toHtml()
        plain_body = self.body_input.toPlainText().strip()

        if not to or not subject or not plain_body:
            QMessageBox.warning(self, "提示", "请填写收件人、主题和正文")
            return

        mail_msg = self._build_mail_message(to, subject, html_body, plain_body)
        self.send_requested.emit(mail_msg)
        self.accept()

    def _build_mail_message(self, to, subject, html_body, plain_body):
        """构建 MIME 邮件（含附件）。无附件时返回简单 MailMessage。"""
        from shadowtalk.core.mail_composer import MailMessage

        # 无附件时直接返回简单 MailMessage（保持向后兼容）
        if not self._attachments and not self._inline_images:
            return MailMessage(
                subject=subject,
                body_text=plain_body,
                message_id=f"compose-{to}@shadowtalk.local",
                extra_headers={},
                to=to,
            )

        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication
        from email.mime.image import MIMEImage

        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['To'] = to

        # 正文部分（alternative：plain + html）
        body_part = MIMEMultipart('alternative')
        body_part.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        body_part.attach(MIMEText(html_body, 'html', 'utf-8'))
        msg.attach(body_part)

        # 普通附件
        for filepath in self._attachments:
            with open(filepath, 'rb') as f:
                data = f.read()
            att = MIMEApplication(data, Name=os.path.basename(filepath))
            att['Content-Disposition'] = f'attachment; filename="{os.path.basename(filepath)}"'
            msg.attach(att)

        # 内联图片
        for i, filepath in enumerate(self._inline_images):
            with open(filepath, 'rb') as f:
                data = f.read()
            img = MIMEImage(data)
            cid = f"image{i+1:03d}@shadowtalk.local"
            img['Content-ID'] = f"<{cid}>"
            img['Content-Disposition'] = f'inline; filename="{os.path.basename(filepath)}"'
            msg.attach(img)

        return MailMessage(
            subject=subject,
            body_text=plain_body,
            message_id=f"compose-{to}@shadowtalk.local",
            extra_headers={},
            to=to,
            mime_message=msg,
        )

    def set_recipient(self, addr: str):
        """预填收件人（用于从联系人列表点选后打开对话框）"""
        self.to_input.setText(addr)

    def set_reply_to(self, email: dict):
        """预填回复（收件人/主题/引用正文）。

        主题保留原有 [ShadowTalk-xxxx] 短码——若这是分身同步邮件，
        短码是会话匹配的依据，去掉会导致回信无法归到对应好友。
        """
        addr = email.get("sender_addr", "") or email.get("sender", "")
        self.to_input.setText(addr)

        subject = email.get("subject", "") or ""
        # 避免 Re: Re: 嵌套（不区分大小写）
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}" if subject else "Re:"
        self.subject_input.setText(subject)

        # 引用正文：置于顶部供用户在上方撰写回复（邮箱惯例）
        received = email.get("received_at", "") or ""
        sender = email.get("sender", "") or addr
        orig = email.get("body_text", "") or ""
        quoted_lines = [f"> {line}" for line in orig.splitlines()]
        quote = (
            f"\n\n\n在 {received}，{sender} 写道：\n"
            + "\n".join(quoted_lines)
        )
        self.body_input.setPlainText(quote)
        # 光标移到开头，用户直接输入回复内容
        cursor = self.body_input.textCursor()
        cursor.setPosition(0)
        self.body_input.setTextCursor(cursor)

    def _apply_styles(self):
        """按当前主题设置 QSS，风格与 SettingsDialog 保持一致"""
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QDialog QLabel {{
                color: {t.FG};
                font-size: 14px;
            }}
            QLabel#composeFieldLabel {{
                color: {t.MUTED};
                font-size: 13px;
                min-width: 42px;
            }}
            QLineEdit {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
                padding: 0 13px;
                height: 40px;
                font-size: 14px;
                color: {t.FG};
            }}
            QLineEdit:focus {{
                border-color: {t.ACCENT};
            }}
            QLineEdit::placeholder {{
                color: {t.MUTED};
            }}
            QTextEdit {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
                padding: 10px 13px;
                font-size: 14px;
                color: {t.FG};
            }}
            QTextEdit:focus {{
                border-color: {t.ACCENT};
            }}
            QTextEdit::placeholder {{
                color: {t.MUTED};
            }}
            /* 工具栏整体 */
            QFrame#composeToolbar {{
                background-color: {t.BG};
                border-radius: 8px;
            }}
            /* 工具栏分组分隔符 */
            QFrame#composeToolbarSep {{
                background-color: {t.BORDER};
            }}
            /* 工具栏按钮：紧凑方形 */
            QFrame#composeToolbar QPushButton {{
                background-color: transparent;
                color: {t.FG};
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 3px 8px;
                min-width: 26px;
                height: 26px;
                font-size: 13px;
            }}
            QFrame#composeToolbar QPushButton:hover {{
                background-color: {t.SURFACE};
                border-color: {t.BORDER};
            }}
            QFrame#composeToolbar QPushButton:checked {{
                background-color: {t.ACCENT_SOFT};
                color: {t.ACCENT};
                border-color: {t.ACCENT};
            }}
            /* 字体大小下拉 */
            QFrame#composeToolbar QComboBox {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: 1px solid {t.BORDER};
                border-radius: 5px;
                padding: 2px 6px;
                height: 26px;
                min-width: 52px;
                font-size: 12px;
            }}
            QFrame#composeToolbar QComboBox:hover {{
                border-color: {t.MUTED};
            }}
            /* 通用按钮（取消/发送等） */
            QPushButton {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: 1px solid {t.BORDER};
                border-radius: 8px;
                padding: 8px 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
                border-color: {t.MUTED};
            }}
            QPushButton#sendBtn {{
                background-color: {t.ACCENT};
                color: white;
                border: none;
            }}
            QPushButton#sendBtn:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
        """)
