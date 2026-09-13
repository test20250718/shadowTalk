"""Theme 模块测试：字段齐全、切换/回落、global_qss 取色"""
from dataclasses import fields
from shadowtalk.ui.theme import (
    Theme, LIGHT, DARK, current, set_current, global_qss
)


def test_theme_fields_nonempty():
    for t in (LIGHT, DARK):
        for f in fields(t):
            assert getattr(t, f.name) != "", f"{t.name}.{f.name} 为空"


def test_light_matches_legacy_constants():
    """浅色值必须与改造前 message_bubble 常量一致（外观零变化）"""
    assert LIGHT.BG == "#F9F8F6"
    assert LIGHT.SURFACE == "#FFFFFF"
    assert LIGHT.FG == "#37352F"
    assert LIGHT.MUTED == "#A09B8C"
    assert LIGHT.BORDER == "#E5E2DB"
    assert LIGHT.ACCENT == "#2E9E57"
    assert LIGHT.ACCENT_SOFT == "#E4F2EA"
    assert LIGHT.SOFT == "#E8E5DE"
    assert LIGHT.USER_BUBBLE == "#37352F"
    assert LIGHT.USER_FG == "#FFFFFF"
    assert LIGHT.AI_BUBBLE == "#FFFFFF"
    assert LIGHT.AI_FG == "#37352F"
    assert LIGHT.SCROLL_HANDLE == "#C9C5BC"
    assert LIGHT.SCROLL_HANDLE_HOVER == "#A8A398"
    assert LIGHT.ACCENT_HOVER == "#268A4C"
    assert LIGHT.ACCENT_PRESSED == "#1F7A41"


def test_dark_palette_from_spec():
    """深色值锁定 spec 表 2.1（含计划补充字段）"""
    assert DARK.BG == "#1A1A1E"
    assert DARK.SURFACE == "#26262B"
    assert DARK.FG == "#E8E6E1"
    assert DARK.MUTED == "#8F8C85"
    assert DARK.BORDER == "#3A3A40"
    assert DARK.ACCENT == "#34C274"
    assert DARK.ACCENT_SOFT == "#1E3A2A"
    assert DARK.SOFT == "#3A3A40"
    assert DARK.USER_BUBBLE == "#2E9E57"
    assert DARK.USER_FG == "#FFFFFF"
    assert DARK.AI_BUBBLE == "#2E2E34"
    assert DARK.AI_FG == "#E8E6E1"
    assert DARK.SCROLL_HANDLE == "#4A4A52"
    assert DARK.SCROLL_HANDLE_HOVER == "#5A5A62"
    assert DARK.ACCENT_HOVER == "#2FB76B"
    assert DARK.ACCENT_PRESSED == "#29A35F"


def test_set_current_and_fallback():
    set_current("dark")
    assert current().name == "dark"
    set_current("light")
    assert current().name == "light"
    set_current("非法值")
    assert current().name == "light"  # 非法回落浅色
    set_current("light")  # 复位


def test_global_qss_contains_theme_color():
    set_current("dark")
    assert "#26262B" in global_qss()  # DARK.SURFACE
    assert "#E8E6E1" in global_qss()  # DARK.FG
    set_current("light")
    assert "#FFFFFF" in global_qss()


def test_global_qss_messagebox_rules():
    """回归：QMessageBox（确认/提示弹窗）须有深色规则，
    否则深色模式下为系统默认白底黑字"""
    set_current("dark")
    qss = global_qss()
    assert "QMessageBox" in qss
    assert "QMessageBox QLabel" in qss
    assert "QMessageBox QPushButton" in qss
    assert "color: #E8E6E1" in qss  # DARK.FG
    set_current("light")


def test_global_qss_statusbar_label_color():
    """回归：状态栏内的 QLabel 不继承 QStatusBar 的 QSS color（Qt 行为），
    必须显式 QStatusBar QLabel 规则，否则深色下状态栏文字仍是黑色"""
    for name, muted in (("light", "#A09B8C"), ("dark", "#8F8C85")):
        set_current(name)
        qss = global_qss()
        assert "QStatusBar QLabel" in qss
        assert f"color: {muted}" in qss
    set_current("light")  # 复位
