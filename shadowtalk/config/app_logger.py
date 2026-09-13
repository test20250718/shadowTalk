# shadowtalk/config/app_logger.py
"""本地日志：轮转文件 + 未捕获异常/线程异常钩子 + faulthandler"""
import logging
import sys
import threading
import faulthandler
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shadowtalk.config.paths import get_base_dir

APP_LOG_PATH = get_base_dir() / "data" / "logs" / "app.log"
FAULT_LOG_PATH = get_base_dir() / "data" / "logs" / "faulthandler.log"

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_fault_file = None  # faulthandler 文件句柄：进程生命周期持有，勿在 with 块中关闭


def setup_logging():
    """初始化日志（幂等，失败不阻塞启动）。main() 开头调用一次。"""
    global _fault_file
    try:
        APP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger("shadowtalk")
        if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            return  # 已初始化（幂等）
        handler = RotatingFileHandler(
            APP_LOG_PATH, maxBytes=2_000_000, backupCount=5,
            encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        if not getattr(sys, "frozen", False):
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter(_FORMAT))
            root.addHandler(console)
    except Exception as e:
        print(f"[app_logger] 日志初始化失败: {e}")
        return

    # ── 未捕获异常钩子 ──
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("shadowtalk").critical(
            "未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_excepthook(args):
        logging.getLogger("shadowtalk").critical(
            f"线程异常 ({args.thread.name})",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook

    # ── 原生崩溃转储（死锁/段错误）──
    try:
        FAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 句柄必须保持到进程生命周期（模块级 _fault_file 持有）：
        # with 块退出即 close，fd 会被 sqlite/app.log 复用，
        # 崩溃时 dump 将写入复用该 fd 的文件（可能污染数据库）
        _fault_file = open(FAULT_LOG_PATH, "w", encoding="utf-8")
        faulthandler.enable(_fault_file)
    except Exception as e:
        print(f"[app_logger] faulthandler 初始化失败: {e}")
