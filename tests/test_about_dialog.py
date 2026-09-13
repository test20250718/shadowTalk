"""关于对话框与版本号一致性测试"""
import sys
from PySide6.QtWidgets import QApplication, QLabel

import shadowtalk
from shadowtalk.ui.widgets.about_dialog import AboutDialog

app = QApplication.instance() or QApplication(sys.argv)


def test_about_dialog_shows_version_and_name():
    dlg = AboutDialog()
    labels = [l.text() for l in dlg.findChildren(QLabel)]
    assert any("ShadowTalk 影聊" in t for t in labels)
    assert any(f"v{shadowtalk.__version__}" in t for t in labels)
    assert any("AI 输出仅供参考" in t for t in labels)   # 免责声明
    assert any("数据目录" in t for t in labels)


def test_statusbar_label_uses_package_version():
    """状态栏版本号来自包定义（不写死）"""
    from shadowtalk.ui.main_window import MainWindow
    w = MainWindow()
    assert f"v{shadowtalk.__version__}" in w._status_label.text()


def test_about_dialog_dark_rules():
    from shadowtalk.ui import theme
    theme.set_current("dark")
    dlg = AboutDialog()
    assert "#E8E6E1" in dlg.styleSheet()   # DARK.FG
    theme.set_current("light")
