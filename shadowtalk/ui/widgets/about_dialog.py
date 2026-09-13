# shadowtalk/ui/widgets/about_dialog.py
"""关于对话框：logo + 版本号 + 简介 + 免责声明 + 数据位置"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)

import shadowtalk
from shadowtalk.config.paths import get_base_dir, resource_path
from shadowtalk.config.i18n import tr
from shadowtalk.ui.theme import current as theme_current


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        # logo
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        pix_path = resource_path("resources/shadowtalk_logo.png")
        if pix_path.exists():
            pix = QPixmap(str(pix_path))
            logo.setPixmap(pix.scaled(96, 96, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation))
        layout.addWidget(logo)

        name = QLabel("ShadowTalk 影聊")
        name.setAlignment(Qt.AlignCenter)
        f = name.font()
        f.setPointSize(15)
        f.setBold(True)
        name.setFont(f)
        layout.addWidget(name)

        ver = QLabel(f"版本 v{shadowtalk.__version__}")
        ver.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver)

        desc = QLabel(tr(
            "本机优先的 AI 桌面聊天：消息仅保存在本机，\n"
            "支持沉浸式聊天（咖啡馆场景）与语音朗读。"))
        desc.setAlignment(Qt.AlignCenter)
        layout.addWidget(desc)

        data_dir = QLabel(f"{tr('数据目录：')}{get_base_dir()}")
        data_dir.setAlignment(Qt.AlignCenter)
        layout.addWidget(data_dir)

        disclaimer = QLabel(tr("AI 输出仅供参考，请审慎甄别，切勿直接采信。"))
        disclaimer.setAlignment(Qt.AlignCenter)
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton(tr("好的"))
        ok_btn.setObjectName("okBtn")
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        self._apply_styles()

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
                padding: 6px 22px;
            }}
            QPushButton:hover {{
                background-color: {t.BG};
            }}
            QPushButton#okBtn {{
                background-color: {t.ACCENT};
                color: white;
                border: none;
                font-weight: bold;
            }}
            QPushButton#okBtn:hover {{
                background-color: {t.ACCENT_HOVER};
            }}
        """)

    def version_text(self) -> str:
        return f"v{shadowtalk.__version__}"
