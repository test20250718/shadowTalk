# Task 16: UI — Settings Dialog

**Files:**
- Create: `shadowtalk/ui/widgets/settings_dialog.py`

## Interfaces
- Consumes: `Settings`, `BackgroundScanner`, `FriendRepository`
- Produces:
  - `SettingsDialog` with API config, memory params, data operations tabs

## Implementation

```python
# shadowtalk/ui/widgets/settings_dialog.py
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QSlider, QPushButton, QHBoxLayout, QLabel,
    QMessageBox, QWidget, QGroupBox
)
from PySide6.QtCore import Qt
from shadowtalk.config.settings import Settings
from shadowtalk.core.background_scanner import BackgroundScanner
from shadowtalk.data.repositories import FriendRepository


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_friend_id=None):
        super().__init__(parent)
        self.current_friend_id = current_friend_id
        self.setWindowTitle("设置")
        self.setMinimumWidth(450)
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Tab 1: API Config
        api_tab = QWidget()
        api_layout = QFormLayout()
        self.api_url_input = QLineEdit()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
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

        api_layout.addRow("API地址：", self.api_url_input)
        api_layout.addRow("API Key：", self.api_key_input)
        api_layout.addRow("模型名称：", self.model_input)
        api_layout.addRow("Temperature：", temp_row)
        api_layout.addRow("最大输出长度：", self.max_output_spin)
        api_tab.setLayout(api_layout)
        tabs.addTab(api_tab, "API 配置")

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
        self.word_limit_spin.setRange(20, 200)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1000, 32000)
        self.l2_limit_spin = QSpinBox()
        self.l2_limit_spin.setRange(1, 20)

        mem_layout.addRow("保留原文轮数：", self.raw_keep_spin)
        mem_layout.addRow("打包批次大小：", self.batch_spin)
        mem_layout.addRow("摘要有效期(天)：", self.valid_days_spin)
        mem_layout.addRow("摘要字数限制：", self.word_limit_spin)
        mem_layout.addRow("最大上下文Token：", self.max_tokens_spin)
        mem_layout.addRow("L2上限：", self.l2_limit_spin)
        mem_tab.setLayout(mem_layout)
        tabs.addTab(mem_tab, "记忆参数")

        # Tab 3: Data Operations
        op_tab = QWidget()
        op_layout = QVBoxLayout()
        scan_btn = QPushButton("手动扫描过期摘要")
        scan_btn.clicked.connect(self._on_scan_now)
        op_layout.addWidget(scan_btn)

        clear_btn = QPushButton("清空当前好友聊天记录")
        clear_btn.clicked.connect(self._on_clear_chat)
        op_layout.addWidget(clear_btn)
        op_layout.addStretch()
        op_tab.setLayout(op_layout)
        tabs.addTab(op_tab, "数据操作")

        layout.addWidget(tabs)

        # Bottom buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        save_btn = QPushButton("保存")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._on_save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _load_settings(self):
        self.api_url_input.setText(Settings.get("api_base_url"))
        self.api_key_input.setText(Settings.get("api_key"))
        self.model_input.setText(Settings.get("model_name"))
        self.temp_slider.setValue(int(Settings.get_float("temperature") * 100))
        self.max_output_spin.setValue(Settings.get_int("max_output_tokens"))

        self.raw_keep_spin.setValue(Settings.get_int("raw_keep_max"))
        self.batch_spin.setValue(Settings.get_int("summary_batch_size"))
        self.valid_days_spin.setValue(Settings.get_int("summary_valid_days"))
        self.word_limit_spin.setValue(Settings.get_int("daily_summary_word_limit"))
        self.max_tokens_spin.setValue(Settings.get_int("max_context_tokens"))
        self.l2_limit_spin.setValue(Settings.get_int("l2_limit"))

    def _on_save(self):
        Settings.set("api_base_url", self.api_url_input.text())
        Settings.set("api_key", self.api_key_input.text())
        Settings.set("model_name", self.model_input.text())
        Settings.set("temperature", str(self.temp_slider.value() / 100))
        Settings.set("max_output_tokens", str(self.max_output_spin.value()))

        Settings.set("raw_keep_max", str(self.raw_keep_spin.value()))
        Settings.set("summary_batch_size", str(self.batch_spin.value()))
        Settings.set("summary_valid_days", str(self.valid_days_spin.value()))
        Settings.set("daily_summary_word_limit", str(self.word_limit_spin.value()))
        Settings.set("max_context_tokens", str(self.max_tokens_spin.value()))
        Settings.set("l2_limit", str(self.l2_limit_spin.value()))

        self.accept()

    def _on_scan_now(self):
        BackgroundScanner().scan_now()
        QMessageBox.information(self, "完成", "扫描完成")

    def _on_clear_chat(self):
        if not self.current_friend_id:
            QMessageBox.warning(self, "提示", "请先选择一个好友")
            return
        friend = FriendRepository.get_by_id(self.current_friend_id)
        reply = QMessageBox.warning(
            self, "确认清空",
            f"确定清空与 {friend['name']} 的全部聊天记录？\n"
            f"（人设 Prompt 将保留）",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            from shadowtalk.data.database import Database
            with Database.transaction() as conn:
                conn.execute(
                    "DELETE FROM chat_messages WHERE friend_id=?",
                    (self.current_friend_id,)
                )
                conn.execute(
                    "DELETE FROM batch_summary WHERE friend_id=?",
                    (self.current_friend_id,)
                )
                conn.execute(
                    "DELETE FROM high_level_summary WHERE friend_id=?",
                    (self.current_friend_id,)
                )
            QMessageBox.information(self, "完成", "聊天记录已清空")
```

## Notes
- UI component, no TDD test
- Commit after implementation
