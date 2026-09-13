# shadowtalk/ui/widgets/friend_dialog.py
"""
ShadowTalk 好友新增/编辑对话框
设计参考：shadowtalk-chat.html — 圆角卡片 + pill 按钮
"""
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QHBoxLayout, QLabel, QFileDialog, QFrame,
    QComboBox, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from shadowtalk.core.tts_service import TTS_VOICES
from shadowtalk.ui.theme import current as theme_current
from shadowtalk.config.i18n import tr


class FriendDialog(QDialog):
    def __init__(self, parent=None, friend=None):
        super().__init__(parent)
        self.friend = friend
        self.avatar_path = friend["avatar_path"] if friend else ""
        self.setWindowTitle(tr("新增好友") if friend is None else tr("编辑好友"))
        self.setMinimumWidth(440)
        self._build_ui()
        if friend:
            self._fill_data(friend)

    def _build_ui(self):
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QDialog QLabel {{
                /* QSS color 不向子控件传播（同 QStatusBar 问题）：
                   表单行标签/头像标签须显式取 FG，否则深色下为默认黑字 */
                color: {t.FG};
            }}
            QCheckBox {{
                /* 邮件同步复选框文字同样须显式取 FG，否则深色下为默认黑字 */
                color: {t.FG};
                spacing: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(16)

        # 标题
        title = QLabel(tr("新增联系人") if self.friend is None else tr("编辑联系人"))
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {t.FG};")
        layout.addWidget(title)

        desc = QLabel(tr("添加一个新的本地联系人。") if self.friend is None
                      else tr("修改联系人名称与备注。"))
        desc.setStyleSheet(f"color: {t.MUTED};")
        layout.addWidget(desc)

        # 表单
        form = QFormLayout()
        form.setSpacing(14)
        form.setContentsMargins(0, 8, 0, 0)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("输入名称"))
        self.name_input.setMaxLength(12)
        self.name_input.setStyleSheet(_input_style())
        form.addRow(tr("联系人名称："), self.name_input)

        self.remark_input = QLineEdit()
        self.remark_input.setPlaceholderText(tr("例如：家人、同事"))
        self.remark_input.setMaxLength(30)
        self.remark_input.setStyleSheet(_input_style())
        form.addRow(tr("备注："), self.remark_input)

        self.ai_role_input = QLineEdit()
        self.ai_role_input.setPlaceholderText(tr("例如：朋友、老师、助手、心理咨询师..."))
        self.ai_role_input.setStyleSheet(_input_style())
        form.addRow(tr("AI 的角色："), self.ai_role_input)

        self.user_role_input = QLineEdit()
        self.user_role_input.setPlaceholderText(tr("例如：高中生、大学生、职场新人..."))
        self.user_role_input.setStyleSheet(_input_style())
        form.addRow(tr("我的角色："), self.user_role_input)

        self.work_dir_input = QLineEdit()
        self.work_dir_input.setPlaceholderText(tr("AI 可在此目录读写文件（留空则禁用文件操作）"))
        self.work_dir_input.setStyleSheet(_input_style())
        work_dir_row = QHBoxLayout()
        work_dir_row.addWidget(self.work_dir_input, 1)
        work_dir_btn = QPushButton(tr("浏览…"))
        work_dir_btn.setCursor(Qt.PointingHandCursor)
        work_dir_btn.setStyleSheet(_secondary_btn_style())
        work_dir_btn.clicked.connect(self._pick_work_dir)
        work_dir_row.addWidget(work_dir_btn)
        form.addRow(tr("工作目录："), work_dir_row)

        self.voice_combo = QComboBox()
        self.voice_combo.addItem(tr("默认（跟随全局）"), "")
        for v in TTS_VOICES:
            self.voice_combo.addItem(v["label"], v["voice"])
        self.voice_combo.setStyleSheet(_input_style())
        form.addRow(tr("语音："), self.voice_combo)

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText(tr("定义对方性格、说话语气、聊天禁忌..."))
        self.prompt_input.setMinimumHeight(100)
        self.prompt_input.setStyleSheet(_textarea_style())
        form.addRow(tr("AI人设Prompt："), self.prompt_input)

        avatar_row = QHBoxLayout()
        self.avatar_label = QLabel(tr("未选择"))
        avatar_btn = QPushButton(tr("选择头像"))
        avatar_btn.setCursor(Qt.PointingHandCursor)
        avatar_btn.setStyleSheet(_secondary_btn_style())
        avatar_btn.clicked.connect(self._pick_avatar)
        avatar_row.addWidget(self.avatar_label)
        avatar_row.addWidget(avatar_btn)
        form.addRow(tr("头像："), avatar_row)

        # ── 邮件同步（V1.4-Add）──
        # 资产导入的好友：只读展示；手动创建的好友：可编辑
        # 安全访问：sqlite3.Row 可能不含新列（旧测试数据），用 try/except 兜底
        self._is_asset_imported = False
        if self.friend is not None:
            try:
                self._is_asset_imported = bool(self.friend["authorizer_email"])
            except (IndexError, KeyError):
                self._is_asset_imported = False

        if self._is_asset_imported:
            # 只读展示：显示资产内置的邮件配置
            # 安全访问：sqlite3.Row 可能不含新列
            def _safe_get(row, key, default=""):
                try:
                    return row[key]
                except (IndexError, KeyError):
                    return default

            mail_sync = _safe_get(friend, "mail_sync_enable", 0)
            self.mail_sync_label = QLabel(tr("开启") if mail_sync else tr("关闭"))
            self.mail_sync_label.setStyleSheet(f"color: {t.FG};")
            form.addRow(tr("邮件同步："), self.mail_sync_label)

            mail_receiver = _safe_get(friend, "mail_receiver_address", "")
            self.mail_receiver_label = QLabel(mail_receiver or tr("（未设置）"))
            self.mail_receiver_label.setStyleSheet(f"color: {t.FG};")
            form.addRow(tr("接收邮箱："), self.mail_receiver_label)

            cycle_map = {"daily": tr("每日"), "weekly": tr("每周"), "monthly": tr("每月")}
            mail_cycle = _safe_get(friend, "mail_sync_cycle", "daily")
            self.mail_cycle_label = QLabel(cycle_map.get(mail_cycle, tr("每日")))
            self.mail_cycle_label.setStyleSheet(f"color: {t.FG};")
            form.addRow(tr("同步周期："), self.mail_cycle_label)

            hint = QLabel(tr("邮件同步配置由分身创建者预设，无法修改。"))
            hint.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
            form.addRow("", hint)
        else:
            # 可编辑：用户自由配置
            self.mail_sync_check = QCheckBox(tr("开启邮件同步"))
            self.mail_sync_check.setChecked(False)
            form.addRow(tr("邮件同步："), self.mail_sync_check)

            self.mail_receiver_input = QLineEdit()
            self.mail_receiver_input.setPlaceholderText(tr("接收聊天记录的邮箱地址"))
            self.mail_receiver_input.setStyleSheet(_input_style())
            form.addRow(tr("接收邮箱："), self.mail_receiver_input)

            self.mail_cycle_combo = QComboBox()
            self.mail_cycle_combo.addItem(tr("每日"), "daily")
            self.mail_cycle_combo.addItem(tr("每周"), "weekly")
            self.mail_cycle_combo.addItem(tr("每月"), "monthly")
            # 分钟级测试周期（仅手动创建好友可选，资产内置周期不含）
            self.mail_cycle_combo.addItem(tr("每5分钟（测试）"), "5min")
            self.mail_cycle_combo.setStyleSheet(_input_style())
            form.addRow(tr("同步周期："), self.mail_cycle_combo)

            # 未开启邮件同步时，禁用下方字段
            def _update_mail_fields_enabled():
                enabled = self.mail_sync_check.isChecked()
                self.mail_receiver_input.setEnabled(enabled)
                self.mail_cycle_combo.setEnabled(enabled)

            self.mail_sync_check.stateChanged.connect(_update_mail_fields_enabled)
            _update_mail_fields_enabled()  # 初始化状态

        layout.addLayout(form)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton(tr("取消"))
        cancel_btn.setFixedSize(80, 42)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(_secondary_btn_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton(tr("保存"))
        ok_btn.setFixedSize(80, 42)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setStyleSheet(_primary_btn_style())
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择头像"), "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.avatar_path = path
            self.avatar_label.setText(os.path.basename(path))

    def _pick_work_dir(self):
        path = QFileDialog.getExistingDirectory(self, tr("选择工作目录"))
        if path:
            self.work_dir_input.setText(path)

    def _fill_data(self, friend):
        self.name_input.setText(friend["name"])
        self.remark_input.setText(friend["remark"])
        self.ai_role_input.setText(friend["ai_role"])
        self.user_role_input.setText(friend["user_role"])
        self.work_dir_input.setText(friend["work_dir"])
        self.prompt_input.setPlainText(friend["system_prompt"])

        if friend["voice"]:
            idx = self.voice_combo.findData(friend["voice"])
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)

        # 邮件同步字段（仅手动创建的好友可编辑）
        if not self._is_asset_imported:
            try:
                self.mail_sync_check.setChecked(bool(friend["mail_sync_enable"]))
                self.mail_receiver_input.setText(friend["mail_receiver_address"])
                cycle_idx = self.mail_cycle_combo.findData(friend["mail_sync_cycle"])
                self.mail_cycle_combo.setCurrentIndex(cycle_idx if cycle_idx >= 0 else 0)
            except (IndexError, KeyError):
                pass  # 旧数据缺少新字段，使用默认值

    def get_data(self) -> dict:
        data = {
            "name": self.name_input.text().strip(),
            "remark": self.remark_input.text().strip(),
            "system_prompt": self.prompt_input.toPlainText().strip(),
            "ai_role": self.ai_role_input.text().strip(),
            "user_role": self.user_role_input.text().strip(),
            "work_dir": self.work_dir_input.text().strip(),
            "avatar_path": self.avatar_path,
            "voice": self.voice_combo.currentData() or "",
        }
        # 邮件同步字段（仅手动创建的好友可编辑）
        if not self._is_asset_imported:
            data["mail_sync_enable"] = 1 if self.mail_sync_check.isChecked() else 0
            data["mail_receiver_address"] = self.mail_receiver_input.text().strip()
            data["mail_sync_cycle"] = self.mail_cycle_combo.currentData() or "daily"
        return data

    def restyle(self):
        """主题切换时由主窗口调用：重设对话框样式（标签/输入框颜色）。"""
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QDialog QLabel {{
                color: {t.FG};
            }}
            QCheckBox {{
                color: {t.FG};
                spacing: 8px;
            }}
        """)


def _input_style() -> str:
    t = theme_current()
    return f"""
        QLineEdit {{
            background-color: {t.SURFACE};
            border: 1px solid {t.BORDER};
            border-radius: 12px;
            padding: 0 13px;
            height: 44px;
            font-size: 14px;
            color: {t.FG};
        }}
        QLineEdit:focus {{
            border-color: {t.ACCENT};
        }}
        QLineEdit::placeholder {{
            color: {t.MUTED};
        }}
        QComboBox {{
            background-color: {t.SURFACE};
            border: 1px solid {t.BORDER};
            border-radius: 12px;
            padding: 0 26px 0 13px;
            height: 44px;
            font-size: 14px;
            color: {t.FG};
        }}
        QComboBox:focus {{
            border-color: {t.ACCENT};
        }}
        QComboBox QAbstractItemView {{
            background-color: {t.SURFACE};
            color: {t.FG};
            border: 1px solid {t.BORDER};
            selection-background-color: {t.ACCENT_SOFT};
            selection-color: {t.FG};
        }}
    """


def _textarea_style() -> str:
    t = theme_current()
    return f"""
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
    """


def _primary_btn_style() -> str:
    t = theme_current()
    return f"""
        QPushButton {{
            background-color: {t.ACCENT};
            color: white;
            border: none;
            border-radius: 21px;
            font-size: 14px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t.ACCENT_HOVER};
        }}
        QPushButton:pressed {{
            background-color: {t.ACCENT_PRESSED};
        }}
    """


def _secondary_btn_style() -> str:
    t = theme_current()
    return f"""
        QPushButton {{
            background-color: {t.SURFACE};
            color: {t.FG};
            border: 1px solid {t.BORDER};
            border-radius: 21px;
            font-size: 14px;
        }}
        QPushButton:hover {{
            background-color: {t.BG};
            border-color: {t.MUTED};
        }}
    """
