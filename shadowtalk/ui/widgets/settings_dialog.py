# shadowtalk/ui/widgets/settings_dialog.py
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QSlider, QPushButton, QHBoxLayout, QLabel,
    QMessageBox, QWidget, QGroupBox, QCheckBox, QListWidget,
    QListWidgetItem
)
from PySide6.QtCore import Qt, Signal
from shadowtalk.config.settings import Settings
from shadowtalk.config.i18n import tr, on_language_changed
from shadowtalk.ui.theme import current as theme_current


class SettingsDialog(QDialog):
    """设置对话框。

    settings_saved 信号：保存成功后发射，通知主窗口刷新工具栏模型列表
    （API 配置增删/切换后，工具栏下拉框需同步）。
    """
    settings_saved = Signal()

    def __init__(self, parent=None, current_friend_id=None):
        super().__init__(parent)
        self.current_friend_id = current_friend_id
        self.setWindowTitle("设置")
        self.setMinimumWidth(680)
        self.resize(760, 560)
        # 内存中的 API 配置列表（编辑期间操作此列表，保存时回写 Settings）
        self._api_configs = []
        self._current_edit_index = -1   # 当前正在编辑的配置索引（-1 = 未选中）
        self._build_ui()
        self._load_settings()
        # 语言切换时刷新（对话框打开期间）
        on_language_changed(self._retranslate_ui)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Tab 1: API Config（多套配置：左侧列表 + 右侧编辑）
        api_tab = QWidget()
        api_main_layout = QHBoxLayout()
        api_main_layout.setContentsMargins(0, 0, 0, 0)

        # —— 左侧：配置列表 + 增删按钮 ——
        list_col = QVBoxLayout()
        self._list_label = QLabel(tr("API 配置："))
        list_col.addWidget(self._list_label)
        self.api_config_list = QListWidget()
        self.api_config_list.setFixedWidth(170)
        self.api_config_list.currentRowChanged.connect(self._on_config_selected)
        list_col.addWidget(self.api_config_list)
        list_btns = QHBoxLayout()
        self.add_config_btn = QPushButton(tr("新增"))
        self.add_config_btn.clicked.connect(self._on_add_config)
        self.del_config_btn = QPushButton(tr("删除"))
        self.del_config_btn.clicked.connect(self._on_delete_config)
        list_btns.addWidget(self.add_config_btn)
        list_btns.addWidget(self.del_config_btn)
        list_col.addLayout(list_btns)
        api_main_layout.addLayout(list_col)

        # —— 右侧：编辑字段 ——
        edit_col = QFormLayout()
        self.api_name_input = QLineEdit()
        self.api_name_input.setPlaceholderText(tr("例如：我的 DeepSeek"))
        self.api_url_input = QLineEdit()
        self.api_url_input.setPlaceholderText(tr("例如：https://api.longcat.chat/openai/v1"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText(tr("例如：ak_xxxxxxxxxxxxxxxx"))
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText(tr("例如：LongCat-2.0"))
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_label = QLabel("0.70")
        self.temp_slider.valueChanged.connect(
            lambda v: self.temp_label.setText(f"{v/100:.2f}")
        )
        temp_row = QHBoxLayout()
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_label)
        self.max_output_spin = QSpinBox()
        self.max_output_spin.setRange(100, 32000)
        self.max_output_spin.setValue(2000)
        self.tool_calls_spin = QSpinBox()
        self.tool_calls_spin.setRange(1, 50)
        self.tool_calls_spin.setValue(15)
        self.tool_calls_spin.setToolTip(
            "AI 单轮对话最多执行多少次工具。太小会频繁触发\"掉线\"，"
            "太大可能长时间无响应（可随时发新消息中断）")
        self.tool_timeout_spin = QSpinBox()
        self.tool_timeout_spin.setRange(5, 600)
        self.tool_timeout_spin.setValue(120)
        self.tool_timeout_spin.setSuffix(" 秒")
        self.tool_timeout_spin.setToolTip(
            "单次工具执行的超时时间。读写大文件、生成图片等慢任务需要更长时间")

        edit_col.addRow(tr("配置名称："), self.api_name_input)
        edit_col.addRow(tr("API 地址："), self.api_url_input)
        edit_col.addRow(tr("API Key："), self.api_key_input)
        edit_col.addRow(tr("模型名称："), self.model_input)
        edit_col.addRow(tr("Temperature："), temp_row)
        edit_col.addRow(tr("最大输出长度："), self.max_output_spin)
        edit_col.addRow(tr("工具调用上限："), self.tool_calls_spin)
        edit_col.addRow(tr("工具执行超时："), self.tool_timeout_spin)
        api_main_layout.addLayout(edit_col)
        api_tab.setLayout(api_main_layout)
        tabs.addTab(api_tab, tr("API 配置"))

        # Tab 2: Memory Params
        mem_tab = QWidget()
        mem_layout = QFormLayout()
        self.raw_keep_spin = QSpinBox()
        self.raw_keep_spin.setRange(10, 200)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(10, 100)
        self.valid_days_spin = QSpinBox()
        self.valid_days_spin.setRange(7, 365)
        self.word_limit_spin = QSpinBox()
        self.word_limit_spin.setRange(50, 1000)
        self.word_limit_spin.setToolTip("L1 摘要的目标字数（软目标：超出也保留全文，不截断）")
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1000, 32000)
        self.l2_limit_spin = QSpinBox()
        self.l2_limit_spin.setRange(1, 20)

        mem_layout.addRow(tr("保留原文轮数："), self.raw_keep_spin)
        mem_layout.addRow(tr("打包批次大小："), self.batch_spin)
        mem_layout.addRow(tr("摘要有效期(天)："), self.valid_days_spin)
        mem_layout.addRow(tr("摘要目标字数："), self.word_limit_spin)
        mem_layout.addRow(tr("最大上下文Token："), self.max_tokens_spin)
        mem_layout.addRow(tr("L2上限："), self.l2_limit_spin)
        mem_tab.setLayout(mem_layout)
        tabs.addTab(mem_tab, tr("记忆参数"))

        # Tab 5: Mail Config
        mail_tab = QWidget()
        mail_layout = QFormLayout()

        # SMTP 配置
        self.smtp_host_input = QLineEdit()
        self.smtp_host_input.setPlaceholderText("例如：smtp.qq.com")
        self.smtp_port_spin = QSpinBox()
        self.smtp_port_spin.setRange(1, 65535)
        self.smtp_port_spin.setValue(587)
        self.smtp_tls_check = QCheckBox("使用 SSL/TLS（生产环境开启）")
        self.smtp_tls_check.setChecked(True)
        self.smtp_user_input = QLineEdit()
        self.smtp_user_input.setPlaceholderText("发件邮箱账号")
        self.smtp_password_input = QLineEdit()
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        self.smtp_password_input.setPlaceholderText("发件邮箱密码/授权码")

        mail_layout.addRow(tr("SMTP 服务器："), self.smtp_host_input)
        mail_layout.addRow(tr("SMTP 端口："), self.smtp_port_spin)
        mail_layout.addRow(tr("加密连接："), self.smtp_tls_check)
        mail_layout.addRow(tr("SMTP 账号："), self.smtp_user_input)
        mail_layout.addRow(tr("SMTP 密码："), self.smtp_password_input)

        # IMAP 配置
        self.imap_host_input = QLineEdit()
        self.imap_host_input.setPlaceholderText("例如：imap.qq.com")
        self.imap_port_spin = QSpinBox()
        self.imap_port_spin.setRange(1, 65535)
        self.imap_port_spin.setValue(993)
        self.imap_user_input = QLineEdit()
        self.imap_user_input.setPlaceholderText(tr("收件邮箱账号"))
        self.imap_password_input = QLineEdit()
        self.imap_password_input.setEchoMode(QLineEdit.Password)
        self.imap_password_input.setPlaceholderText(tr("收件邮箱密码/授权码"))

        mail_layout.addRow(tr("IMAP 服务器："), self.imap_host_input)
        mail_layout.addRow(tr("IMAP 端口："), self.imap_port_spin)
        mail_layout.addRow(tr("IMAP 账号："), self.imap_user_input)
        mail_layout.addRow(tr("IMAP 密码："), self.imap_password_input)

        # 轮询间隔
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(30, 3600)
        self.poll_interval_spin.setValue(180)
        self.poll_interval_spin.setSuffix(" 秒")
        self.poll_interval_spin.setToolTip(tr("生产环境建议≥180秒，避免触发邮箱风控"))
        mail_layout.addRow(tr("轮询间隔："), self.poll_interval_spin)

        # 开发模式
        self.dev_mode_check = QCheckBox(tr("开发模式（MailHog：SMTP 1025 / IMAP 1143 / 无 SSL）"))
        self.dev_mode_check.setToolTip(tr("开启后使用 MailHog 预设值，全部邮件本地闭环"))
        mail_layout.addRow(tr("测试模式："), self.dev_mode_check)

        mail_tab.setLayout(mail_layout)
        tabs.addTab(mail_tab, tr("邮件配置"))

        layout.addWidget(tabs)

        # Bottom buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton(tr("取消"))
        save_btn = QPushButton(tr("保存"))
        save_btn.setObjectName("saveBtn")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._on_save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._apply_styles()

    def _apply_styles(self):
        """按当前主题设置整体深色样式（此前整个对话框无 QSS，
        深色模式下为系统默认白底黑字）"""
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QDialog QLabel {{
                /* QSS color 不向子控件传播：表单行标签须显式取 FG */
                color: {t.FG};
            }}
            QTabWidget::pane {{
                border: none;
                background-color: {t.BG};
            }}
            QTabBar::tab {{
                background-color: {t.BG};
                color: {t.MUTED};
                padding: 8px 18px;
                border: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QTabBar::tab:selected {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QTabBar::tab:hover {{
                color: {t.FG};
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
            QComboBox {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 12px;
                padding: 0 26px 0 13px;
                height: 40px;
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
            QListWidget {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 10px;
                padding: 4px;
                font-size: 14px;
                color: {t.FG};
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background-color: {t.ACCENT_SOFT};
                color: {t.FG};
            }}
            QListWidget::item:hover {{
                background-color: {t.BG};
            }}
            QSpinBox {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 10px;
                padding: 0 8px;
                height: 38px;
                font-size: 14px;
                color: {t.FG};
            }}
            QSpinBox:focus {{
                border-color: {t.ACCENT};
            }}
            QCheckBox {{
                color: {t.FG};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {t.BORDER};
                border-radius: 4px;
                background-color: {t.SURFACE};
            }}
            QCheckBox::indicator:checked {{
                background-color: {t.ACCENT};
                border-color: {t.ACCENT};
            }}
            QSlider::sub-page:horizontal {{
                background-color: {t.ACCENT};
                border-radius: 2px;
            }}
            QSlider::add-page:horizontal {{
                background-color: {t.SOFT};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -5px 0;
                background-color: {t.ACCENT};
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
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
            QPushButton#saveBtn {{
                background-color: {t.ACCENT};
                color: white;
                border: none;
            }}
            QPushButton#saveBtn:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
            QMessageBox {{
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

    def _load_settings(self):
        # —— API 多套配置 ——
        self._api_configs = Settings.get_api_configs()
        self._refresh_config_list()
        # 选中当前激活的配置
        active_idx = Settings.get_active_api_index()
        if 0 <= active_idx < len(self._api_configs):
            self.api_config_list.setCurrentRow(active_idx)
        self._sync_edit_fields_from_list()

        self.raw_keep_spin.setValue(Settings.get_int("raw_keep_max"))
        self.batch_spin.setValue(Settings.get_int("summary_batch_size"))
        self.valid_days_spin.setValue(Settings.get_int("summary_valid_days"))
        self.word_limit_spin.setValue(Settings.get_int("summary_target_chars"))
        self.max_tokens_spin.setValue(Settings.get_int("max_context_tokens"))
        self.l2_limit_spin.setValue(Settings.get_int("l2_limit"))

        # 邮件配置
        self.smtp_host_input.setText(Settings.get("mail_smtp_host"))
        self.smtp_port_spin.setValue(Settings.get_int("mail_smtp_port"))
        self.smtp_tls_check.setChecked(Settings.get("mail_smtp_use_tls") == "1")
        self.smtp_user_input.setText(Settings.get("mail_smtp_user"))
        self.smtp_password_input.setText(Settings.get("mail_smtp_password"))
        self.imap_host_input.setText(Settings.get("mail_imap_host"))
        self.imap_port_spin.setValue(Settings.get_int("mail_imap_port"))
        self.imap_user_input.setText(Settings.get("mail_imap_user"))
        self.imap_password_input.setText(Settings.get("mail_imap_password"))
        self.poll_interval_spin.setValue(Settings.get_int("mail_poll_interval_seconds"))
        self.dev_mode_check.setChecked(Settings.get("mail_dev_mode") == "1")

    def _on_save(self):
        # —— 保存前先回写当前编辑的配置到列表 ——
        self._commit_edit_fields_to_config()

        # 保存 API 配置列表
        Settings.save_api_configs(self._api_configs)

        # 同步激活配置到 flat keys（供 AIClient 读取）
        active_idx = Settings.get_active_api_index()
        if 0 <= active_idx < len(self._api_configs):
            Settings.set_active_api_index(active_idx)

        Settings.set("raw_keep_max", str(self.raw_keep_spin.value()))
        Settings.set("summary_batch_size", str(self.batch_spin.value()))
        Settings.set("summary_valid_days", str(self.valid_days_spin.value()))
        Settings.set("summary_target_chars", str(self.word_limit_spin.value()))
        Settings.set("max_context_tokens", str(self.max_tokens_spin.value()))
        Settings.set("l2_limit", str(self.l2_limit_spin.value()))

        # 邮件配置
        Settings.set("mail_smtp_host", self.smtp_host_input.text().strip())
        Settings.set("mail_smtp_port", str(self.smtp_port_spin.value()))
        Settings.set("mail_smtp_use_tls", "1" if self.smtp_tls_check.isChecked() else "0")
        Settings.set("mail_smtp_user", self.smtp_user_input.text().strip())
        Settings.set("mail_smtp_password", self.smtp_password_input.text())
        Settings.set("mail_imap_host", self.imap_host_input.text().strip())
        Settings.set("mail_imap_port", str(self.imap_port_spin.value()))
        Settings.set("mail_imap_user", self.imap_user_input.text().strip())
        Settings.set("mail_imap_password", self.imap_password_input.text())
        Settings.set("mail_poll_interval_seconds", str(self.poll_interval_spin.value()))
        Settings.set("mail_dev_mode", "1" if self.dev_mode_check.isChecked() else "0")

        self.settings_saved.emit()
        self.accept()

    # ── API 配置列表编辑辅助方法 ───────────────────────────────────

    def _refresh_config_list(self):
        """根据 self._api_configs 刷新左侧列表显示。"""
        self.api_config_list.blockSignals(True)
        self.api_config_list.clear()
        for cfg in self._api_configs:
            name = cfg.get("name", "") or "(未命名)"
            item = QListWidgetItem(name)
            self.api_config_list.addItem(item)
        self.api_config_list.blockSignals(False)

    def _sync_edit_fields_from_list(self):
        """把当前选中配置的值同步到右侧编辑字段。"""
        row = self.api_config_list.currentRow()
        if 0 <= row < len(self._api_configs):
            cfg = self._api_configs[row]
            self._current_edit_index = row
            self.api_name_input.setText(cfg.get("name", ""))
            self.api_url_input.setText(cfg.get("base_url", ""))
            self.api_key_input.setText(cfg.get("api_key", ""))
            self.model_input.setText(cfg.get("model_name", ""))
            self.temp_slider.setValue(
                int(float(cfg.get("temperature", "0.7")) * 100))
            self.max_output_spin.setValue(
                int(cfg.get("max_output_tokens", "20000")))
            self.tool_calls_spin.setValue(
                int(cfg.get("max_tool_calls", "15")))
            self.tool_timeout_spin.setValue(
                int(cfg.get("tool_timeout", "120")))
        else:
            self._current_edit_index = -1

    def _commit_edit_fields_to_config(self):
        """把右侧编辑字段的当前值写回 self._api_configs 中正在编辑的项。"""
        row = self._current_edit_index
        if not (0 <= row < len(self._api_configs)):
            return
        cfg = self._api_configs[row]
        cfg["name"] = self.api_name_input.text().strip() or "(未命名)"
        cfg["base_url"] = self.api_url_input.text().strip()
        cfg["api_key"] = self.api_key_input.text()
        cfg["model_name"] = self.model_input.text().strip()
        cfg["temperature"] = str(self.temp_slider.value() / 100)
        cfg["max_output_tokens"] = str(self.max_output_spin.value())
        cfg["max_tool_calls"] = str(self.tool_calls_spin.value())
        cfg["tool_timeout"] = str(self.tool_timeout_spin.value())
        # 同步更新列表项显示名
        self.api_config_list.item(row).setText(cfg["name"])

    def _on_config_selected(self, row):
        """选中配置切换前，先回写上一份编辑到列表。"""
        if row < 0 or row >= len(self._api_configs):
            return
        self._commit_edit_fields_to_config()
        self.api_config_list.blockSignals(True)
        self.api_config_list.setCurrentRow(row)
        self.api_config_list.blockSignals(False)
        self._sync_edit_fields_from_list()

    def _on_add_config(self):
        """新增一套空白配置并选中编辑。"""
        self._commit_edit_fields_to_config()
        new_cfg = {
            "name": tr("新配置"),
            "base_url": "",
            "api_key": "",
            "model_name": "",
            "temperature": "0.7",
            "max_output_tokens": "20000",
            "max_tool_calls": "15",
            "tool_timeout": "120",
        }
        self._api_configs.append(new_cfg)
        self._refresh_config_list()
        self.api_config_list.blockSignals(True)
        self.api_config_list.setCurrentRow(len(self._api_configs) - 1)
        self.api_config_list.blockSignals(False)
        self._sync_edit_fields_from_list()

    def _on_delete_config(self):
        """删除当前选中的配置（至少保留一套）。"""
        row = self.api_config_list.currentRow()
        if not (0 <= row < len(self._api_configs)):
            return
        if len(self._api_configs) <= 1:
            QMessageBox.warning(self, tr("提示"), tr("至少保留一套 API 配置。"))
            return
        name = self._api_configs[row].get("name", "")
        reply = QMessageBox.question(
            self, tr("删除配置"), f"{tr('确定删除配置「')}{name}{tr('」吗？')}",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._api_configs.pop(row)
        # 调整激活索引
        active = Settings.get_active_api_index()
        if active >= len(self._api_configs):
            Settings.set_active_api_index(len(self._api_configs) - 1)
        elif active == row and row > 0:
            Settings.set_active_api_index(active - 1)
        self._refresh_config_list()
        new_row = min(row, len(self._api_configs) - 1)
        self.api_config_list.blockSignals(True)
        self.api_config_list.setCurrentRow(new_row)
        self.api_config_list.blockSignals(False)
        self._sync_edit_fields_from_list()

    def _retranslate_ui(self):
        """语言切换后刷新设置对话框文本（对话框打开时生效）。

        注：设置对话框每次打开都是新创建的，正常流程已能跟上语言；
        此回调仅处理「对话框打开时切换语言」的边界情况。
        """
        self.setWindowTitle(tr("设置"))
        self._list_label.setText(tr("API 配置："))
        self.add_config_btn.setText(tr("新增"))
        self.del_config_btn.setText(tr("删除"))
        # 刷新列表显示（配置名可能含翻译占位）
        self._refresh_config_list()
        # 重新设置占位符与提示
        self.api_name_input.setPlaceholderText(tr("例如：我的 DeepSeek"))
        self.api_url_input.setPlaceholderText(tr("例如：https://api.longcat.chat/openai/v1"))
        self.api_key_input.setPlaceholderText(tr("例如：ak_xxxxxxxxxxxxxxxx"))
        self.model_input.setPlaceholderText(tr("例如：LongCat-2.0"))
        self.dev_mode_check.setText(tr("开发模式（MailHog：SMTP 1025 / IMAP 1143 / 无 SSL）"))
        # 底部按钮文本
        for btn in self.findChildren(QPushButton):
            if btn.objectName() == "saveBtn":
                btn.setText(tr("保存"))
            elif btn.text() in ("取消", "Cancel"):
                btn.setText(tr("取消"))
