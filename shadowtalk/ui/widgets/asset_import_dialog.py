# shadowtalk/ui/widgets/asset_import_dialog.py
"""
ShadowTalk 数字分身资产导入对话框

用户粘贴从网页复制得到的 Base64 密文字符串。
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPlainTextEdit, QPushButton,
    QHBoxLayout, QLabel, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from shadowtalk.ui.theme import current as theme_current


class AssetImportDialog(QDialog):
    """粘贴 Base64 密文对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入网页数字分身资产")
        self.setMinimumWidth(480)
        self.setMinimumHeight(360)
        self._build_ui()

    def _build_ui(self):
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
                color: {t.FG};
            }}
            QDialog QLabel {{
                color: {t.FG};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(16)

        # 标题
        title = QLabel("导入网页数字分身资产")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {t.FG};")
        layout.addWidget(title)

        desc = QLabel("请粘贴从网页复制的数字分身密文字符串。")
        desc.setStyleSheet(f"color: {t.MUTED};")
        layout.addWidget(desc)

        # 密文输入框
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("在此粘贴 Base64 密文字符串…")
        self.text_input.setMinimumHeight(180)
        self.text_input.setStyleSheet(_textarea_style())
        layout.addWidget(self.text_input, 1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 42)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(_secondary_btn_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        next_btn = QPushButton("下一步")
        next_btn.setFixedSize(90, 42)
        next_btn.setCursor(Qt.PointingHandCursor)
        next_btn.setStyleSheet(_primary_btn_style())
        next_btn.clicked.connect(self._on_next)
        btn_row.addWidget(next_btn)

        layout.addLayout(btn_row)

    def _on_next(self):
        """校验非空后接受对话框（预览在 MainWindow 串联中处理）。"""
        text = self.text_input.toPlainText().strip()
        if not text:
            # 空输入提示
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先粘贴数字分身密文字符串")
            return
        self.accept()

    def get_ciphertext(self) -> str:
        """返回用户粘贴的密文字符串。"""
        return self.text_input.toPlainText().strip()


def _textarea_style() -> str:
    t = theme_current()
    return f"""
        QPlainTextEdit {{
            background-color: {t.SURFACE};
            border: 1px solid {t.BORDER};
            border-radius: 12px;
            padding: 12px 14px;
            font-size: 13px;
            font-family: Menlo, Consolas, monospace;
            color: {t.FG};
        }}
        QPlainTextEdit:focus {{
            border-color: {t.ACCENT};
        }}
        QPlainTextEdit::placeholder {{
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
