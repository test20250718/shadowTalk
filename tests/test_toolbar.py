"""顶部工具栏测试：模型切换 + 主题切换。"""
import sys

from PySide6.QtWidgets import QApplication

from shadowtalk.config.settings import Settings
from shadowtalk.ui import theme
from shadowtalk.ui.widgets.toolbar import Toolbar

app = QApplication.instance() or QApplication(sys.argv)


def _new_toolbar():
    """创建工具栏并重置到已知状态。"""
    theme.set_current("light")
    return Toolbar()


def test_toolbar_theme_button_toggles():
    """主题按钮：浅色显示 ☀️，点击后变深色 🌙。"""
    tb = _new_toolbar()
    assert tb._theme_btn.text() == "☀️"
    tb._theme_btn.click()
    assert theme.current().name == "dark"
    assert tb._theme_btn.text() == "🌙"
    tb._theme_btn.click()
    assert theme.current().name == "light"
    assert tb._theme_btn.text() == "☀️"


def test_toolbar_model_combo_populated():
    """模型下拉框应从 Settings 加载配置列表。"""
    tb = _new_toolbar()
    configs = Settings.get_api_configs()
    assert tb.model_combo.count() == len(configs)
    assert tb.model_combo.currentIndex() == Settings.get_active_api_index()


def test_toolbar_restyle_applies_dark_theme():
    """restyle() 在深色模式下应把工具栏背景设为深色。"""
    from shadowtalk.ui import theme
    tb = _new_toolbar()
    theme.set_current("dark")
    tb.restyle()
    # 深色背景色 #26262B (DARK.SURFACE) 应出现在工具栏样式中
    assert "#26262B" in tb.styleSheet()
    # 复位
    theme.set_current("light")
    tb.restyle()
    assert "#FFFFFF" in tb.styleSheet()  # LIGHT.SURFACE


def test_toolbar_model_change_updates_settings():
    """切换模型下拉框应写入 active_api_index 并同步 flat keys。"""
    tb = _new_toolbar()
    configs = Settings.get_api_configs()
    if len(configs) < 2:
        # 只有一套配置时新增一套再测
        Settings.save_api_configs(configs + [{
            "name": "第二套", "base_url": "https://example.com",
            "api_key": "test-key", "model_name": "test-model",
            "temperature": "0.5", "max_output_tokens": "1000",
            "max_tool_calls": "5", "tool_timeout": "60",
        }])
        tb.refresh()
    # 切到索引 1
    tb.model_combo.setCurrentIndex(1)
    assert Settings.get_active_api_index() == 1
    assert Settings.get("model_name") == "test-model"
    # 复位
    tb.model_combo.setCurrentIndex(0)
    assert Settings.get_active_api_index() == 0
    Settings.set("model_name", "LongCat-2.0")
