# shadowtalk/ui/widgets/eula_dialog.py
"""首次启动使用声明：用户同意后方可使用，同意结果落库不再弹"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)
from shadowtalk.ui.theme import current as theme_current
from shadowtalk.config.settings import Settings

_EULA_TEXT = (
    "欢迎使用 ShadowTalk 影聊。首次使用前，请阅读以下声明：\n"
    "\n"
    "1. 本软件由 AI 大模型驱动。AI 生成的内容（文字、代码、文件等）"
    "可能存在错误、过时或不准确之处，仅供参考，请审慎甄别，"
    "切勿直接采信；重要事项请自行核实。\n"
    "\n"
    "2. AI 可在你为好友指定的工作目录内读写文件；写入目录外位置时，"
    "需要你逐次授权确认。\n"
    "\n"
    "3. 聊天记录与设置仅保存在本机，不上传；对话内容会发送至你配置的 "
    "AI 服务商以生成回复。\n"
    "\n"
    "4. 你应为使用本软件产生的结果自行负责。\n"
)


class EulaDialog(QDialog):
    """使用声明对话框：同意 / 退出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用声明")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("使用声明")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        body = QLabel(_EULA_TEXT)
        body.setWordWrap(True)
        layout.addWidget(body, 1)
        self._body = body

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._decline_btn = QPushButton("退出")
        self._accept_btn = QPushButton("同意并使用")
        self._accept_btn.setObjectName("acceptBtn")
        self._accept_btn.setDefault(True)
        self._accept_btn.clicked.connect(self.accept)
        self._decline_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._decline_btn)
        btn_row.addWidget(self._accept_btn)
        layout.addLayout(btn_row)

        self._apply_styles()

    def to_plain_text(self) -> str:
        return self._body.text()

    def _apply_styles(self):
        """按当前主题设色（QSS color 不向子控件传播，需显式规则）"""
        t = theme_current()
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {t.SURFACE};
            }}
            QDialog QLabel {{
                color: {t.FG};
            }}
            QPushButton {{
                background-color: {t.SURFACE};
                color: {t.FG};
                border: 1px solid {t.BORDER};
                border-radius: 6px;
                padding: 6px 18px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
            }}
            QPushButton#acceptBtn {{
                background-color: {t.ACCENT};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton#acceptBtn:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
        """)


def check_eula() -> bool:
    """首启门槛：未同意时弹声明框；返回是否可以继续使用。

    同意 → 落库 eula_accepted=1（此后不再弹）；退出/Esc/关窗 → False。
    """
    if Settings.get("eula_accepted") == "1":
        return True
    if EulaDialog().exec() == QDialog.Accepted:
        Settings.set("eula_accepted", "1")
        return True
    return False
