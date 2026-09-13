# shadowtalk/ui/widgets/toolbar.py
"""顶部工具栏：模型配置切换 + 主题切换。

位于菜单栏与主界面之间（MainWindow.addToolBar 插入），
替代原聊天区头部的主题按钮，并新增多套 API 模型切换功能。
"""
from PySide6.QtWidgets import (
    QToolBar, QComboBox, QPushButton, QWidget, QHBoxLayout, QLabel,
    QMessageBox,
)
from PySide6.QtCore import Signal, Qt

from shadowtalk.config.settings import Settings
from shadowtalk.config.i18n import tr, set_language, on_language_changed, language, LANGUAGES
from shadowtalk.ui.theme import current as theme_current, set_current


class Toolbar(QToolBar):
    """顶部工具栏。

    model_changed(int)：用户切换了激活配置（携带新索引）。
    """
    model_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self._build_ui()
        self._refresh_models()

    def _build_ui(self):
        # 居中布局的占位容器
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(12)

        # —— 模型切换 ——
        self._label = QLabel(tr("模型："))
        layout.addWidget(self._label)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        layout.addWidget(self.model_combo)

        layout.addSpacing(16)
        layout.addStretch()

        # —— 主题切换 ——
        self._theme_btn = QPushButton()
        self._theme_btn.setFixedSize(36, 36)
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.clicked.connect(self._on_theme_toggle)
        layout.addWidget(self._theme_btn)

        # —— 语言切换 ——
        layout.addSpacing(8)
        self._lang_label = QLabel(tr("语言："))
        layout.addWidget(self._lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(90)
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        # 选中当前语言
        idx = self.lang_combo.findData(language())
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self.lang_combo)

        self.addWidget(container)
        self._sync_theme_button()
        self.restyle()
        # 注册语言切换回调（刷新自身文本）
        on_language_changed(self._retranslate)

    # ── 模型配置 ───────────────────────────────────────────────────

    def _refresh_models(self):
        """从 Settings 刷新模型下拉框（保留当前选中）。"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        configs = Settings.get_api_configs()
        for cfg in configs:
            name = cfg.get("name", "") or "(未命名)"
            self.model_combo.addItem(name)
        # 选中当前激活
        active = Settings.get_active_api_index()
        if 0 <= active < len(configs):
            self.model_combo.setCurrentIndex(active)
        self.model_combo.blockSignals(False)

    def refresh(self):
        """公开方法：设置保存后刷新工具栏（模型列表 + 主题按钮）。"""
        self._refresh_models()
        self._sync_theme_button()

    def restyle(self):
        """主题切换时由主窗口调用：重设工具栏及子控件样式。"""
        t = theme_current()
        # 工具栏背景（与菜单栏/状态栏同色）
        self.setStyleSheet(f"""
            QToolBar {{
                background-color: {t.SURFACE};
                border: none;
                border-bottom: 1px solid {t.BORDER};
                padding: 0 4px;
            }}
        """)
        # 标签（模型 + 语言）
        self._label.setStyleSheet(f"color: {t.FG}; font-size: 13px;")
        self._lang_label.setStyleSheet(f"color: {t.FG}; font-size: 13px;")
        # 下拉框
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {t.SURFACE};
                border: 1px solid {t.BORDER};
                border-radius: 10px;
                padding: 0 12px;
                height: 32px;
                font-size: 13px;
                color: {t.FG};
            }}
            QComboBox:focus {{
                border-color: {t.ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: 1px solid {t.BORDER};
                selection-background-color: {t.ACCENT_SOFT};
                selection-color: {t.FG};
            }}
        """)
        # 主题按钮（透明底 + 圆角 hover）
        self._theme_btn.setStyleSheet(f"""
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
        """)

    def _on_model_changed(self, index):
        """模型下拉框切换：写入激活索引 + 同步 flat keys + 通知主窗口。"""
        if index < 0:
            return
        configs = Settings.get_api_configs()
        if not (0 <= index < len(configs)):
            return
        Settings.set_active_api_index(index)
        self.model_changed.emit(index)

    def _on_language_changed(self, index):
        """语言下拉框切换。"""
        lang = self.lang_combo.itemData(index)
        if lang:
            set_language(lang)

    def _retranslate(self):
        """语言切换后刷新工具栏自身文本。"""
        self._label.setText(tr("模型："))
        self._lang_label.setText(tr("语言："))
        self._sync_theme_button()
        # 同步下拉框选中项（语言代码 → 行号）
        idx = self.lang_combo.findData(language())
        if idx >= 0:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.blockSignals(False)

    # ── 主题切换 ───────────────────────────────────────────────────

    def _on_theme_toggle(self):
        """主题按钮点击：直接执行全局换肤。"""
        target = "light" if theme_current().name == "dark" else "dark"
        set_current(target)
        # 通知主窗口应用主题（重设 QSS + 各组件 restyle）
        parent = self.parent()
        if parent and hasattr(parent, '_apply_theme'):
            parent._apply_theme()
        self._sync_theme_button()

    def _sync_theme_button(self):
        """同步主题按钮图标 + 提示。"""
        is_dark = theme_current().name == "dark"
        self._theme_btn.setText("🌙" if is_dark else "☀️")
        self._theme_btn.setToolTip(
            "当前深色，点击切到浅色" if is_dark else "当前浅色，点击切到深色")
