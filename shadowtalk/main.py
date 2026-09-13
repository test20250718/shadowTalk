import sys
import os
import logging

from shadowtalk.config.paths import get_base_dir, resource_path
from shadowtalk.config.app_logger import setup_logging

os.makedirs(get_base_dir() / "data" / "avatars", exist_ok=True)
os.makedirs(get_base_dir() / "data" / "logs", exist_ok=True)

from PySide6.QtWidgets import QApplication
from shadowtalk.data.database import Database
from shadowtalk.config.settings import Settings
from shadowtalk.ui.main_window import MainWindow
from shadowtalk.ui.theme import set_current as theme_set_current


def main():
    setup_logging()
    logging.getLogger("shadowtalk").info(
        "ShadowTalk 启动: base_dir=%s frozen=%s",
        get_base_dir(), getattr(sys, "frozen", False))
    Database.get_connection()
    Settings.init_defaults()

    # 先应用持久化主题再构造 UI（spec 3.5）
    theme_set_current(Settings.get("theme"))
    # 加载界面语言（必须在构造 UI 前）
    from shadowtalk.config.i18n import load as i18n_load
    i18n_load()

    app = QApplication(sys.argv)
    # 窗口/任务栏图标（logo 缺失时静默用默认图标）
    from PySide6.QtGui import QIcon
    logo = resource_path("resources/shadowtalk_logo.png")
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))

    # 首次启动使用声明：同意后方可使用（同意结果落库，此后不再弹）
    from shadowtalk.ui.widgets.eula_dialog import check_eula
    if not check_eula():
        Database.close()
        return 0

    window = MainWindow()
    window.show()

    exit_code = app.exec()

    Database.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
