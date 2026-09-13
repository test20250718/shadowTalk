"""AIWorker 工作目录守卫测试"""

from shadowtalk.ui.threads.ai_worker import AIWorker


def test_ai_worker_denies_tool_when_work_dir_empty():
    worker = AIWorker(friend_id=1, user_message="", ai_client=None,
                      messages=[], work_dir="")
    reply = worker._run_tool("print('hi')", "随便")
    # 拒绝文案的两个关键片段（源码为跨行拼接的单一字符串）
    assert "当前好友未配置工作目录" in reply
    assert "即可让我读写文件" in reply


# ── 干活限额接线：调用上限/执行超时从设置读取（用户：AI 干活
#    需要时间长，软件没给够时间 → 频繁触发"掉线"）──

class _CaptureClient:
    """记录 chat_with_tools 收到的参数"""
    def __init__(self):
        self.kwargs = None

    def chat_with_tools(self, messages, tool_runner=None, max_tool_calls=5):
        self.kwargs = {"max_tool_calls": max_tool_calls}
        return "done"


def test_ai_worker_passes_configured_max_tool_calls():
    from shadowtalk.config.settings import Settings
    Settings.set("max_tool_calls", "20")
    try:
        client = _CaptureClient()
        worker = AIWorker(friend_id=1, user_message="x", ai_client=client,
                          messages=[], work_dir="D:/w")
        worker.run()
        assert client.kwargs["max_tool_calls"] == 20
    finally:
        Settings.set("max_tool_calls", "15")


def test_ai_worker_passes_configured_tool_timeout(monkeypatch):
    """_run_tool 把设置里的超时传给执行器（三次调用路径都要带）"""
    from shadowtalk.config.settings import Settings
    captured = []

    class _FakeResult:
        def summary(self):
            return "ok"

    def fake_run(code, workdir, approver=None, reason="", timeout=30):
        captured.append(timeout)
        return _FakeResult()

    monkeypatch.setattr("shadowtalk.core.python_executor.run_with_approval",
                        fake_run)
    monkeypatch.setattr(
        "shadowtalk.core.python_executor.scan_write_paths",
        lambda code, wd: [])

    Settings.set("tool_timeout", "180")
    try:
        worker = AIWorker(friend_id=1, user_message="x", ai_client=None,
                          messages=[], work_dir="D:/w")
        worker._run_tool("print(1)", "测试")
        assert captured == [180]
    finally:
        Settings.set("tool_timeout", "120")


# ── 工作过程可见（用户：干活时看不到动静，怕卡死）──

def test_run_emits_thinking_activity():
    """run() 开始即报告"正在思考"（工作卡初始文字）"""
    events = []
    client = _CaptureClient()
    worker = AIWorker(friend_id=1, user_message="x", ai_client=client,
                      messages=[], work_dir="")
    worker.activity.connect(events.append)
    worker.run()
    assert any("思考" in e for e in events)


def test_run_tool_emits_activity_steps(monkeypatch):
    """执行工具前后发活动信号：执行中(带说明) → 完成(带耗时)"""

    class _FakeResult:
        def summary(self):
            return "ok"

    monkeypatch.setattr(
        "shadowtalk.core.python_executor.run_with_approval",
        lambda code, workdir, approver=None, reason="", timeout=30: _FakeResult())
    monkeypatch.setattr(
        "shadowtalk.core.python_executor.scan_write_paths",
        lambda code, wd: [])

    events = []
    worker = AIWorker(friend_id=1, user_message="x", ai_client=None,
                      messages=[], work_dir="D:/w")
    worker.activity.connect(events.append)
    worker._run_tool("print(1)", "生成天气报告")

    assert any("生成天气报告" in e for e in events)
    assert any("完成" in e for e in events)


