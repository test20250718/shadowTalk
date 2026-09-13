"""app_logger 测试：日志落盘 + 崩溃捕获"""
import faulthandler
import logging
import sys
import threading
import pytest
from logging.handlers import RotatingFileHandler
from shadowtalk.config.app_logger import setup_logging


@pytest.fixture(autouse=True)
def _reset_shadowtalk_logger():
    """每个测试前清空 shadowtalk logger 的 handler，测试后还原进程级全局状态。

    测试前清空：setup_logging() 带幂等检查（已存在 RotatingFileHandler 则早退），
    若不清空，后续测试中 monkeypatch 的 APP_LOG_PATH 不会生效
    （handler 仍指向上一个测试的 tmp 目录）。

    测试后还原：setup_logging() 会替换 sys/threading excepthook、enable
    faulthandler 并持有 _fault_file 句柄——这些是本模块写入的进程级全局状态，
    不还原会泄漏到本文件外的测试（test_logging_points 中有回归钉桩）。
    """
    from shadowtalk.config import app_logger

    logger = logging.getLogger("shadowtalk")
    for h in list(logger.handlers):
        logger.removeHandler(h)
        if isinstance(h, RotatingFileHandler):
            h.close()  # 释放 Windows 文件句柄，便于 pytest 清理 tmp 目录

    # 快照本模块将改写的全局状态（pytest 会话内其他插件可能已包装 threading
    # excepthook，还原到快照值即可）
    orig_sys_excepthook = sys.excepthook
    orig_thread_excepthook = threading.excepthook

    yield

    # ── teardown：还原全局状态 ──
    sys.excepthook = orig_sys_excepthook
    threading.excepthook = orig_thread_excepthook

    # 仅当 setup_logging 真正 enable 过 faulthandler 才禁用/关闭
    # （setup 失败的测试不会动 faulthandler，也不该替 pytest 的会话级
    # faulthandler 做任何事——只清自己装上的那个）
    fault_file = getattr(app_logger, "_fault_file", None)
    if fault_file is not None:
        faulthandler.disable()
        try:
            fault_file.close()
        finally:
            app_logger._fault_file = None

    # 移除 app_logger 挂上的 handler（RotatingFileHandler + 开发模式 StreamHandler），
    # 保留 caplog 等其他 handler
    for h in list(logger.handlers):
        if isinstance(h, (RotatingFileHandler, logging.StreamHandler)):
            logger.removeHandler(h)
            h.close()


def _file_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_logger_writes_to_app_log(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(
        "shadowtalk.config.app_logger.APP_LOG_PATH", log_file)
    setup_logging()
    logging.getLogger("shadowtalk").info("启动测试消息")
    assert "启动测试消息" in _file_text(log_file)


def test_excepthook_writes_traceback(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(
        "shadowtalk.config.app_logger.APP_LOG_PATH", log_file)
    setup_logging()
    try:
        raise ValueError("测试异常")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = _file_text(log_file)
    assert "测试异常" in text
    assert "Traceback" in text


def test_threading_excepthook_writes_traceback(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    monkeypatch.setattr(
        "shadowtalk.config.app_logger.APP_LOG_PATH", log_file)
    setup_logging()
    try:
        raise RuntimeError("线程异常")
    except RuntimeError:
        exc = sys.exc_info()
        # Python 3.11 的 ExceptHookArgs 是 structseq，仅接受
        # (sequence, dict) 构造（3.12+ 才支持关键字参数）
        threading.excepthook(
            threading.ExceptHookArgs(
                (RuntimeError, exc[1], exc[2], threading.current_thread())))
    text = _file_text(log_file)
    assert "线程异常" in text
    assert "Traceback" in text  # 消息本身含"线程异常"，须验证 exc_info 真的写入


def test_setup_failure_does_not_block(tmp_path, monkeypatch):
    """日志目录不可创建时，setup_logging 不抛异常"""
    # mkdir(parents=True) 会自建"不存在/x"目录，旧写法 except 分支从不触发
    block = tmp_path / "block"
    block.write_text("")
    monkeypatch.setattr(
        "shadowtalk.config.app_logger.APP_LOG_PATH",
        block / "x" / "app.log")  # 父路径是文件 → mkdir 抛 NotADirectoryError
    setup_logging()  # 不应抛异常
