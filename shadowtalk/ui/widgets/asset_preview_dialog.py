# shadowtalk/ui/widgets/asset_preview_dialog.py
"""
ShadowTalk 数字分身预览确认对话框

只读展示解密后的分身信息：昵称、人设摘要、授权方邮箱、邮件同步配置。
用户确认后执行导入。
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QHBoxLayout,
    QLabel, QFrame, QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from shadowtalk.ui.theme import current as theme_current
from shadowtalk.core.asset_import_service import AssetBundle


class AssetPreviewDialog(QDialog):
    """预览确认对话框：只读展示分身信息 + 确认/取消。"""

    def __init__(self, bundle: AssetBundle, is_update: bool = False, parent=None):
        super().__init__(parent)
        self.bundle = bundle
        self.is_update = is_update
        self.setWindowTitle(
            "检测到新版本分身" if is_update else "确认导入分身"
        )
        self.setMinimumWidth(460)
        self.setMinimumHeight(400)
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
        if self.is_update:
            title = QLabel("检测到新版本分身")
            subtitle = QLabel("角色人设与邮件同步配置将会被更新")
        else:
            title = QLabel("确认导入分身")
            subtitle = QLabel("以下是解密后的分身信息，请确认后导入。")

        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {t.FG};")
        layout.addWidget(title)

        subtitle.setStyleSheet(f"color: {t.MUTED};")
        layout.addWidget(subtitle)

        # 信息展示区
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {t.BG};
                border-radius: 12px;
                padding: 4px;
            }}
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 16, 16, 16)
        info_layout.setSpacing(12)

        # 昵称
        info_layout.addWidget(self._make_row("昵称", self.bundle.nickname))
        # 授权方邮箱
        info_layout.addWidget(self._make_row(
            "授权方邮箱", self.bundle.authorizer_email
        ))
        # 需求方邮箱
        info_layout.addWidget(self._make_row(
            "需求方邮箱", self.bundle.recipient_email
        ))
        # 人设摘要（截断显示）
        persona_text = self.bundle.persona[:200]
        if len(self.bundle.persona) > 200:
            persona_text += "…"
        info_layout.addWidget(self._make_row("人设摘要", persona_text))
        # 邮件同步配置（只读展示）
        sync_status = "开启" if self.bundle.mail_sync_enable else "关闭"
        info_layout.addWidget(self._make_row("邮件同步", sync_status))
        if self.bundle.mail_sync_enable:
            info_layout.addWidget(self._make_row(
                "接收邮箱", self.bundle.mail_receiver_address or "（未设置）"
            ))
            cycle_label = {"daily": "每日", "weekly": "每周", "monthly": "每月"}.get(
                self.bundle.mail_sync_cycle, self.bundle.mail_sync_cycle
            )
            info_layout.addWidget(self._make_row("同步周期", cycle_label))

        layout.addWidget(info_frame)

        # 邮件同步只读提示
        hint = QLabel("邮件同步配置由分身创建者预设，无法修改。")
        hint.setStyleSheet(f"color: {t.MUTED}; font-size: 12px;")
        layout.addWidget(hint)

        layout.addStretch()

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

        ok_btn = QPushButton("确认导入" if not self.is_update else "确认更新")
        ok_btn.setFixedSize(100, 42)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setStyleSheet(_primary_btn_style())
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def _make_row(label: str, value: str):
        """构造一个标签 + 值的展示行。"""
        t = theme_current()
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        lbl = QLabel(label + "：")
        lbl.setStyleSheet(f"color: {t.MUTED}; font-size: 13px; min-width: 90px;")
        row_layout.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(f"color: {t.FG}; font-size: 13px;")
        val.setWordWrap(True)
        val.setMinimumWidth(200)
        row_layout.addWidget(val, 1)

        return row


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
