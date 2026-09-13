"""首次启动使用声明（EULA）测试：未同意不可使用，同意后落库不再弹"""
import sys
from PySide6.QtWidgets import QApplication, QDialog

from shadowtalk.config.settings import Settings
from shadowtalk.ui.widgets.eula_dialog import EulaDialog, check_eula

app = QApplication.instance() or QApplication(sys.argv)


def test_dialog_contains_disclaimer_and_buttons():
    """声明对话框含 AI 免责关键文案与 同意/退出 双按钮"""
    dlg = EulaDialog()
    text = dlg.to_plain_text()
    assert "仅供参考" in text
    assert "审慎甄别" in text
    assert "本机" in text          # 数据本地存储说明
    assert dlg._accept_btn.text().startswith("同意")
    assert dlg._decline_btn.text().startswith("退出")


def test_check_eula_skips_when_already_accepted(monkeypatch):
    """已同意过（设置=1）→ 不再弹窗直接放行"""
    def boom(*a, **k):
        raise AssertionError("已同意过仍弹窗")
    monkeypatch.setattr("shadowtalk.ui.widgets.eula_dialog.EulaDialog", boom)
    Settings.set("eula_accepted", "1")
    try:
        assert check_eula() is True
    finally:
        Settings.set("eula_accepted", "")


def test_check_eula_accept_persists_setting(monkeypatch):
    """点同意 → 返回 True 且落库（下次不再弹）"""
    class FakeDlg:
        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("shadowtalk.ui.widgets.eula_dialog.EulaDialog", FakeDlg)
    Settings.set("eula_accepted", "")
    try:
        assert check_eula() is True
        assert Settings.get("eula_accepted") == "1"
    finally:
        Settings.set("eula_accepted", "")


def test_check_eula_decline_blocks(monkeypatch):
    """点退出（或 Esc/关窗）→ 返回 False，不落库"""
    class FakeDlg:
        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr("shadowtalk.ui.widgets.eula_dialog.EulaDialog", FakeDlg)
    Settings.set("eula_accepted", "")
    try:
        assert check_eula() is False
        assert Settings.get("eula_accepted") != "1"
    finally:
        Settings.set("eula_accepted", "")


def test_dialog_label_color_rule_dark():
    """深色模式下声明文字有显式颜色规则（QSS color 不向子控件传播）"""
    from shadowtalk.ui import theme
    theme.set_current("dark")
    dlg = EulaDialog()
    assert "#E8E6E1" in dlg.styleSheet()  # DARK.FG
    theme.set_current("light")  # 复位
