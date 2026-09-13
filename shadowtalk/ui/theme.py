# shadowtalk/ui/theme.py
"""ShadowTalk 界面主题：颜色单一来源（浅色/深色两档，即时切换）

spec: docs/superpowers/specs/2026-08-14-dark-mode-design.md
注意：本模块属 ui 层，纯数据 + 字符串拼接，禁止 import 任何 Qt 类。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    BG: str
    SURFACE: str
    FG: str
    MUTED: str
    BORDER: str
    ACCENT: str
    ACCENT_SOFT: str
    SOFT: str
    ACCENT_HOVER: str        # 计划补充：发送按钮 hover（原硬编码 #268A4C）
    ACCENT_PRESSED: str      # 计划补充：发送按钮 pressed（原硬编码 #1F7A41）
    USER_BUBBLE: str
    USER_FG: str
    AI_BUBBLE: str
    AI_FG: str
    HUMAN_BUBBLE: str        # V1.4-Add：真人回信气泡（暖色调，区别于 user/ai）
    HUMAN_FG: str
    SCROLL_HANDLE: str
    SCROLL_HANDLE_HOVER: str


LIGHT = Theme(
    name="light",
    BG="#F9F8F6", SURFACE="#FFFFFF", FG="#37352F", MUTED="#A09B8C",
    BORDER="#E5E2DB", ACCENT="#2E9E57", ACCENT_SOFT="#E4F2EA", SOFT="#E8E5DE",
    ACCENT_HOVER="#268A4C", ACCENT_PRESSED="#1F7A41",
    USER_BUBBLE="#37352F", USER_FG="#FFFFFF", AI_BUBBLE="#FFFFFF",
    AI_FG="#37352F", HUMAN_BUBBLE="#F0E4D4", HUMAN_FG="#5C4033",
    SCROLL_HANDLE="#C9C5BC", SCROLL_HANDLE_HOVER="#A8A398",
)

DARK = Theme(
    name="dark",
    BG="#1A1A1E", SURFACE="#26262B", FG="#E8E6E1", MUTED="#8F8C85",
    BORDER="#3A3A40", ACCENT="#34C274", ACCENT_SOFT="#1E3A2A", SOFT="#3A3A40",
    ACCENT_HOVER="#2FB76B", ACCENT_PRESSED="#29A35F",
    USER_BUBBLE="#2E9E57", USER_FG="#FFFFFF", AI_BUBBLE="#2E2E34",
    AI_FG="#E8E6E1", HUMAN_BUBBLE="#3D2B1F", HUMAN_FG="#F0E4D4",
    SCROLL_HANDLE="#4A4A52", SCROLL_HANDLE_HOVER="#5A5A62",
)

_current = LIGHT


def current() -> Theme:
    return _current


def set_current(name: str) -> None:
    """"dark" → DARK；其余一切值（含非法/缺失）回落 LIGHT"""
    global _current
    _current = DARK if name == "dark" else LIGHT


def global_qss() -> str:
    """主窗口全局 QSS（内容 = 改造前 main_window.py 55-96 行，颜色改取当前主题）"""
    t = current()
    return f"""
        QMainWindow {{
            background-color: {t.SURFACE};
        }}
        QMenuBar {{
            background-color: {t.SURFACE};
            color: {t.FG};
            border-bottom: 1px solid {t.BORDER};
            padding: 2px 8px;
        }}
        QMenuBar::item:selected {{
            background-color: {t.BG};
            border-radius: 4px;
        }}
        QMenu {{
            background-color: {t.SURFACE};
            border: 1px solid {t.BORDER};
            padding: 4px 0;
        }}
        QMenu::item {{
            padding: 6px 24px;
            color: {t.FG};
        }}
        QMenu::item:selected {{
            background-color: {t.BG};
        }}
        QSplitter::handle {{
            background-color: {t.SURFACE};
            width: 5px;
        }}
        QSplitter::handle:hover {{
            background-color: {t.ACCENT_SOFT};
        }}
        QSplitter::handle:pressed {{
            background-color: {t.ACCENT};
        }}
        QStatusBar {{
            background-color: {t.SURFACE};
            color: {t.MUTED};
            border-top: 1px solid {t.BORDER};
        }}
        QStatusBar QLabel {{
            color: {t.MUTED};
        }}
        QToolTip {{
            background-color: {t.SURFACE};
            color: {t.FG};
            border: 1px solid {t.BORDER};
            padding: 4px 8px;
            border-radius: 4px;
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
    """
