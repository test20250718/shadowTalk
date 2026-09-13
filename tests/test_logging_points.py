"""关键路径日志埋点测试：caplog 捕获 logging 调用"""
import logging
import sys
from shadowtalk.core.prompt_logger import log_conversation


def test_prompt_logger_emits_info(caplog, monkeypatch, tmp_path):
    monkeypatch.setattr("shadowtalk.core.prompt_logger.LOG_BASE_DIR",
                        tmp_path / "logs" / "chat_prompts")
    with caplog.at_level(logging.INFO, logger="shadowtalk"):
        log_conversation(
            friend_name="测试", friend_id=1,
            context=[{"role": "user", "content": "你好"}],
            user_message="你好", ai_reply="回复")
        assert any(
            "chat_prompts" in r.message and "测试" in r.message
            for r in caplog.records
            if r.name == "shadowtalk.core.prompt_logger")


def test_app_logger_teardown_restores_global_hooks():
    """test_app_logger 的 fixture teardown 必须还原进程级全局状态（M1）

    回归保护：setup_logging() 会替换 sys/threading excepthook 并 enable
    faulthandler（模块级 _fault_file 持有句柄）。若夹具不还原，这些状态
    会泄漏到本文件（按字母序在 test_app_logger.py 之后执行）乃至整个测试会话。
    注意：threading.excepthook 会被 pytest 自身包装，无法与 __excepthook__
    比对，故以 sys.excepthook（两者同时安装/还原）与 _fault_file 为泄漏判据。
    """
    assert sys.excepthook is sys.__excepthook__
    from shadowtalk.config import app_logger
    assert app_logger._fault_file is None
