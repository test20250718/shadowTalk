import sys
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from shadowtalk.config.settings import Settings
from shadowtalk.ui.widgets.settings_dialog import SettingsDialog
from shadowtalk.ui import theme


def test_settings_dialog_dark_styles():
    """回归：设置窗口此前整个无 QSS，深色模式下为系统默认白底黑字。
    必须显式覆盖各控件颜色（QSS color 不向子控件传播）。"""
    theme.set_current("dark")
    dlg = SettingsDialog()
    qss = dlg.styleSheet()
    assert "QDialog QLabel" in qss   # 表单行标签
    assert "QTabBar::tab" in qss     # 选项卡文字
    assert "QComboBox" in qss        # 下拉框 QSS 规则（保留，供未来复用）
    assert "QSpinBox" in qss         # 数值输入
    assert "QCheckBox" in qss        # 自动朗读
    assert "QSlider" in qss          # Temperature
    assert "QMessageBox" in qss      # 清空确认弹窗
    assert "color: #E8E6E1" in qss   # DARK.FG
    assert "color: #26262B" in qss   # DARK.SURFACE 底
    theme.set_current("light")
