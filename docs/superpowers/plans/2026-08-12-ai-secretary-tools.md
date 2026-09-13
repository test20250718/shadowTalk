# AI 秘书工具调用（Tool Calling）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI 通过 Function Calling 执行 Python 代码（子进程沙箱，30s 超时），工作目录内自由读写、目录外写需聊天内确认。

**Architecture:** 新增 `PythonExecutor`（子进程 + AST 写路径扫描 + 审批回调）；`AIClient` 增加 `chat_with_tools` 多轮循环；`AIWorker` 通过 `QEventLoop` 把审批请求发到主线程弹确认卡片；设置对话框加工作目录配置。

**Tech Stack:** PySide6（已装），openai>=2.50.0（已装，支持 tools），pytest（已有）。

## Global Constraints

- 工作目录内 AI 自由读写；目录外读自由、**写需聊天内确认卡片批准**
- 单次代码执行超时 **30 秒**（kill）；每轮对话工具调用上限 **5 次**
- 允许联网（用户已确认接受风险）
- 新增配置项 `work_dir`，默认 `shadowtalk/workdir/`，启动时自动创建
- 所有 UI 文案中文；新组件注释中文（项目惯例）
- 保持 `AIClient.chat()` 原接口不变（向后兼容）

---

### Task 1: PythonExecutor 子进程沙箱（含 AST 扫描 + 审批回调）

**Files:**
- Create: `shadowtalk/core/python_executor.py`
- Test: `tests/test_python_executor.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class ExecResult`：字段 `stdout: str`、`stderr: str`、`exit_code: int`、`timed_out: bool`、`user_denied: bool`（默认 False）
  - `scan_write_paths(code: str, workdir: str) -> list[Path]`：返回代码中写操作的目标路径（绝对路径，仅目录外）
  - `run_code(code: str, workdir: str, timeout: int = 30) -> ExecResult`：子进程执行
  - `run_with_approval(code: str, workdir: str, approver: Callable[[list[Path], str], bool]) -> ExecResult`：扫描→审批→执行（reason 参数为固定字符串 `"AI 请求执行代码"`，实际 reason 由上层传递——签名改为 `run_with_approval(code, workdir, approver, reason="")`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_python_executor.py
"""PythonExecutor 子进程沙箱测试"""
import os
import time
from pathlib import Path
from shadowtalk.core.python_executor import (
    ExecResult, scan_write_paths, run_code, run_with_approval
)


def test_run_code_success(tmp_path):
    code = "print('hello from sandbox')"
    result = run_code(code, str(tmp_path))
    assert result.exit_code == 0
    assert "hello from sandbox" in result.stdout
    assert result.timed_out is False
    assert result.user_denied is False


def test_run_code_returns_error():
    code = "1/0"
    result = run_code(code, str(Path(".").resolve()))
    assert result.exit_code != 0
    assert "ZeroDivisionError" in result.stderr


def test_run_code_syntax_error():
    code = "def broken(:"
    result = run_code(code, str(Path(".").resolve()))
    assert result.exit_code != 0
    assert "SyntaxError" in result.stderr


def test_run_code_timeout(tmp_path):
    code = "import time; time.sleep(10)"
    start = time.time()
    result = run_code(code, str(tmp_path), timeout=2)
    assert result.timed_out is True
    assert time.time() - start < 5


def test_run_code_writes_inside_workdir(tmp_path):
    """工作目录内写文件：允许，无审批"""
    code = "from pathlib import Path; Path('out.txt').write_text('hi')"
    result = run_code(code, str(tmp_path))
    assert result.exit_code == 0
    assert (tmp_path / "out.txt").exists()


def test_scan_detects_outside_write(tmp_path):
    outside = tmp_path.parent / "evil.txt"
    code = f"open({str(outside)!r}, 'w').write('x')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_ignores_inside_write(tmp_path):
    code = "open('ok.txt', 'w').write('x')"
    paths = scan_write_paths(code, str(tmp_path))
    assert paths == []


def test_run_with_approval_denied_does_not_execute(tmp_path):
    outside = tmp_path.parent / "blocked.txt"
    code = f"open({str(outside)!r}, 'w').write('x')"
    result = run_with_approval(code, str(tmp_path),
                               approver=lambda paths, reason: False)
    assert result.user_denied is True
    assert not outside.exists()


def test_run_with_approval_granted_executes(tmp_path):
    outside = tmp_path.parent / "allowed.txt"
    code = f"open({str(outside)!r}, 'w').write('y')"
    result = run_with_approval(code, str(tmp_path),
                               approver=lambda paths, reason: True)
    assert result.user_denied is False
    assert outside.exists()
    assert outside.read_text() == "y"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_python_executor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 python_executor.py**

```python
# shadowtalk/core/python_executor.py
"""
Python 子进程沙箱：AI 工具调用的代码执行器
- 子进程隔离执行，30 秒超时
- AST 扫描写操作目标，目录外写入需审批回调
"""
import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    user_denied: bool = False

    def summary(self) -> str:
        """返回给模型的文本摘要"""
        if self.user_denied:
            return "用户拒绝了写入请求，未执行代码。请改用工作目录内路径，或询问用户。"
        if self.timed_out:
            return "代码执行超时（30 秒），已强制终止。请尝试简化任务或减少数据量。"
        parts = []
        if self.stdout:
            parts.append(f"标准输出:\n{self.stdout}")
        if self.stderr:
            parts.append(f"标准错误:\n{self.stderr}")
        parts.append(f"退出码: {self.exit_code}")
        return "\n".join(parts)


def _resolve_target(node, workdir: Path, code: str) -> list[Path]:
    """从 AST 节点尽力解析目标路径（绝对路径列表）"""
    try:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            raw = node.value
            p = Path(raw)
            if not p.is_absolute():
                p = workdir / p
            return [p]
    except Exception:
        pass
    return []


def scan_write_paths(code: str, workdir: str) -> list[Path]:
    """
    AST 扫描代码中的写操作目标路径，返回工作目录外的绝对路径列表。
    支持的写操作：open(..., 'w'/'a'/'x')、Path.write_text/write_bytes、
    Path.open、os.rename/move/copy/mkdir/makedirs、shutil.copy/move
    """
    workdir = Path(workdir).resolve()
    targets: list[Path] = []

    def collect(node) -> None:
        # open(path, mode) / open(path, 'w')
        if isinstance(node, ast.Call):
            fn = node.func
            fname = ""
            if isinstance(fn, ast.Name):
                fname = fn.id
            elif isinstance(fn, ast.Attribute):
                fname = fn.attr
            # open(path, 'w'|'a'|'x')
            if fname == "open" and len(node.args) >= 2:
                mode = node.args[1]
                if isinstance(mode, ast.Constant) and str(mode.value).startswith(("w", "a", "x")):
                    targets.extend(_resolve_target(node.args[0], workdir, code))
            # write_text / write_bytes / mkdir / makedirs
            if fname in ("write_text", "write_bytes", "mkdir", "makedirs"):
                targets.extend(_resolve_target(node.args[0], workdir, code))
            # os.rename/move/copy/mkdir/makedirs: 目标通常是第二个参数
            if fname in ("rename", "move", "copy"):
                if len(node.args) >= 2:
                    targets.extend(_resolve_target(node.args[1], workdir, code))

    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            collect(node)
    except SyntaxError:
        return []  # 语法错误由子进程报告

    # 仅保留工作目录外的绝对路径
    return [p.resolve() for p in targets
            if p.resolve() not in [workdir] and not p.resolve().is_relative_to(workdir)]


def run_code(code: str, workdir: str, timeout: int = 30) -> ExecResult:
    """子进程执行代码，超时 kill"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ExecResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as e:
        return ExecResult(
            stdout=e.stdout.decode() if isinstance(e.stdout, bytes) and e.stdout else "",
            stderr=e.stderr.decode() if isinstance(e.stderr, bytes) and e.stderr else "",
            exit_code=-9,
            timed_out=True,
        )


def run_with_approval(code: str, workdir: str,
                      approver, reason: str = "") -> ExecResult:
    """
    扫描→审批→执行。
    approver: Callable[[list[Path], str], bool] 返回 True 允许 / False 拒绝
    """
    outside_paths = scan_write_paths(code, workdir)
    if outside_paths:
        allowed = approver(outside_paths, reason)
        if not allowed:
            return ExecResult(user_denied=True)
    return run_code(code, workdir)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_python_executor.py -v`
Expected: PASS（10 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/core/python_executor.py tests/test_python_executor.py
git commit -m "feat: add PythonExecutor subprocess sandbox with write approval"
```

---

### Task 2: AIClient.chat_with_tools 多轮循环

**Files:**
- Modify: `shadowtalk/core/ai_client.py`
- Test: `tests/test_ai_client.py`（追加）

**Interfaces:**
- Consumes: `ExecResult`（Task 1）
- Produces: `AIClient.chat_with_tools(messages: list[dict], tool_runner: Callable[[str, str], str], max_tool_calls: int = 5) -> str`
  - `tool_runner(code: str, reason: str) -> str`：执行代码并返回给模型的文本摘要（UI 层注入，内部用 ExecResult.summary()）
  - 模型响应含 tool_calls 时循环执行；无 tools 支持时回退 `chat()`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_ai_client.py`：

```python
def test_chat_with_tools_executes_tool_call():
    """模型请求工具 → 执行 → 结果回传 → 返回最终文本"""
    from unittest.mock import MagicMock, patch

    # 第一次调用返回 tool_calls，第二次返回最终文本
    tool_msg = MagicMock()
    tool_msg.content = None
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = "run_python"
    tool_call.function.arguments = '{"code": "print(1)", "reason": "测试"}'
    tool_msg.tool_calls = [tool_call]

    final_msg = MagicMock()
    final_msg.content = "完成！"
    final_msg.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=tool_msg), MagicMock(message=final_msg)]

    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_instance.chat.completions.create.side_effect = [mock_response.choices[0].message, mock_response.choices[1].message]
        # 修正：side_effect 应为完整响应列表

        client = AIClient(base_url="https://t", api_key="k", model="m")
        executed = []
        result = client.chat_with_tools(
            [{"role": "user", "content": "你好"}],
            tool_runner=lambda code, reason: executed.append(code) or "输出: 1"
        )

    assert executed == ["print(1)"]
    assert result == "完成！"


def test_chat_with_tools_falls_back_without_tools_support():
    """模型不支持 tools（抛异常）→ 回退 chat()"""
    from unittest.mock import MagicMock, patch
    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "纯文本回复"
        mock_response.choices[0].message.tool_calls = None
        mock_instance.chat.completions.create.side_effect = [mock_response]

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "你好"}],
            tool_runner=lambda c, r: "x"
        )
    assert result == "纯文本回复"


def test_chat_with_tools_limits_loop_to_5():
    """循环上限 5 次"""
    from unittest.mock import MagicMock, patch
    with patch("openai.OpenAI") as MockOpenAI:
        mock_instance = MockOpenAI.return_value
        tool_msg = MagicMock()
        tool_msg.content = None
        tool_call = MagicMock()
        tool_call.id = "call_x"
        tool_call.function.name = "run_python"
        tool_call.function.arguments = '{"code": "x", "reason": "r"}'
        tool_msg.tool_calls = [tool_call]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=tool_msg)]
        mock_instance.chat.completions.create.return_value = mock_response

        client = AIClient(base_url="https://t", api_key="k", model="m")
        result = client.chat_with_tools(
            [{"role": "user", "content": "hi"}],
            tool_runner=lambda c, r: "out"
        )
    # 循环 5 次后强制停止，返回最后一次的文本摘要
    assert "5" in result  # 提示达到上限
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_ai_client.py -v`
Expected: FAIL — `AttributeError: 'AIClient' object has no attribute 'chat_with_tools'`

- [ ] **Step 3: 实现 chat_with_tools**

在 `ai_client.py` 追加：

```python
    def chat_with_tools(self, messages: list[dict],
                        tool_runner, max_tool_calls: int = 5) -> str:
        """
        带工具调用的多轮对话。
        tool_runner: Callable[[code: str, reason: str], str] 执行代码返回文本结果
        模型不支持 tools 时回退纯文本 chat()
        """
        clean_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
        ]
        tools = [{
            "type": "function",
            "function": {
                "name": "run_python",
                "description": "在用户指定的工作目录下执行 Python 代码（可读写文件、处理数据、生成文档）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string",
                                 "description": "要执行的 Python 代码"},
                        "reason": {"type": "string",
                                   "description": "执行目的说明（展示给用户）"},
                    },
                    "required": ["code", "reason"],
                },
            },
        }]

        for _ in range(max_tool_calls):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=clean_messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    tools=tools,
                )
            except Exception:
                # 模型/网关不支持 tools → 回退纯文本
                return self.chat(messages)

            if not response.choices:
                raise ValueError("API returned empty choices")
            message = response.choices[0].message

            if not getattr(message, "tool_calls", None):
                return message.content or ""

            # 执行工具调用
            clean_messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })
            for tc in message.tool_calls:
                name = tc.function.name
                import json as _json
                try:
                    args = _json.loads(tc.function.arguments or "{}")
                except _json.JSONDecodeError:
                    args = {}
                if name == "run_python":
                    code = args.get("code", "")
                    reason = args.get("reason", "")
                    try:
                        result_text = tool_runner(code, reason)
                    except Exception as e:
                        result_text = f"工具执行异常: {e}"
                else:
                    result_text = f"未知工具: {name}"
                clean_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        return ("已达到单轮工具调用上限（5 次）。"
                "请直接给出当前已完成工作的结果摘要。")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_ai_client.py -v`
Expected: PASS（原 2 个 + 新 3 个）

注意：测试里 mock 的 `create.side_effect` 是响应对象列表，而实现里访问 `response.choices[0].message`——mock 需要正确的嵌套。实现时若测试失败，调整测试的 mock 结构以匹配 `response.choices[0].message` 的真实形态（`side_effect=[resp1, resp2]`，每个 resp 有 `.choices[0].message`）。

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/core/ai_client.py tests/test_ai_client.py
git commit -m "feat: add chat_with_tools multi-turn loop to AIClient"
```

---

### Task 3: AIWorker 集成（QEventLoop 审批 + 工具执行）

**Files:**
- Modify: `shadowtalk/ui/threads/ai_worker.py`
- Modify: `shadowtalk/ui/main_window.py`
- Test: `tests/test_python_executor.py` 追加（executor 层已测；worker 层人工冒烟）

**Interfaces:**
- Consumes: `AIClient.chat_with_tools`（Task 2）、`PythonExecutor.run_with_approval`（Task 1）
- Produces: `AIWorker.__init__(friend_id, user_message, ai_client, messages, work_dir, approval_requested: Signal, approval_answered: Signal)`；`MainWindow` 中连接审批信号与确认卡片

- [ ] **Step 1: 修改 AIWorker**

```python
# shadowtalk/ui/threads/ai_worker.py
from PySide6.QtCore import QThread, Signal
from shadowtalk.core.python_executor import run_with_approval


class AIWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, friend_id, user_message, ai_client, messages,
                 work_dir="", approval_requested=None, approval_answered=None):
        super().__init__()
        self.friend_id = friend_id
        self.user_message = user_message
        self.ai_client = ai_client
        self.messages = messages
        self.work_dir = work_dir
        self._approval_requested = approval_requested
        self._approval_answered = approval_answered

    def run(self):
        try:
            reply = self.ai_client.chat_with_tools(
                self.messages,
                tool_runner=self._run_tool,
            )
            self.finished.emit(reply)
        except Exception as e:
            self.failed.emit(str(e))

    def _run_tool(self, code: str, reason: str) -> str:
        """执行工具代码，目录外写需经 UI 审批"""
        if not self.work_dir or not self._approval_requested:
            # 无工作目录配置或 UI 不可用 → 仅执行目录内写入
            from shadowtalk.core.python_executor import run_with_approval
            return run_with_approval(
                code, self.work_dir or ".",
                approver=lambda paths, r: False, reason=reason
            ).summary()

        from PySide6.QtCore import QEventLoop, QObject
        loop = QEventLoop()

        def on_answer(allowed: bool):
            loop.quit()
            self._approved = allowed

        self._approved = False
        self._approval_requested.emit(code, reason)  # 发到主线程
        self._approval_answered.connect(on_answer)
        loop.exec()  # 嵌套事件循环，等待用户点击
        self._approval_answered.disconnect(on_answer)
        return run_with_approval(
            code, self.work_dir,
            approver=lambda paths, r: self._approved,
            reason=reason
        ).summary()
```

- [ ] **Step 2: 修改 MainWindow 连接审批**

在 `main_window.py` 中：`MainWindow` 类级定义两个信号，`__init__` 中连接，`_on_message_sent` 创建 worker 时传入：

```python
# MainWindow 类级信号
approval_requested = Signal(list, str)   # (paths, reason)
approval_answered = Signal(bool)

# __init__ 中连接
self.approval_requested.connect(self._on_approval_requested)
self.approval_answered.connect(self._on_approval_answered)
```

```python
    def _on_approval_requested(self, paths, reason):
        """弹出确认卡片：添加到聊天区"""
        self.chat_area.show_approval_card(paths, reason)

    def _on_approval_answered(self, allowed: bool):
        """确认卡片结果 → AIWorker 的 QEventLoop 收到"""
        pass  # 实际由卡片直接 emit 到 worker 的 approval_answered
```

确认卡片实现（`chat_area.py` 或 `message_bubble.py`）：

```python
class ApprovalCard(QWidget):
    """写文件确认卡片：路径列表 + 允许/拒绝"""

    approved = Signal(bool)

    def __init__(self, paths, reason, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel(f"✋ 秘书想写入以下文件：")
        title.setStyleSheet(f"color: {FG}; font-weight: bold;")
        layout.addWidget(title)
        for p in paths:
            layout.addWidget(QLabel(f"· {p}"))
        if reason:
            layout.addWidget(QLabel(f"说明：{reason}",
                                    wordWrap=True,
                                    styleSheet=f"color: {MUTED};"))
        btn_row = QHBoxLayout()
        allow = QPushButton("允许")
        allow.setStyleSheet(f"background: {ACCENT}; color: white; border-radius: 6px; padding: 4px 14px;")
        deny = QPushButton("拒绝")
        deny.setStyleSheet(f"background: {BORDER}; color: {FG}; border-radius: 6px; padding: 4px 14px;")
        allow.clicked.connect(lambda: self.approved.emit(True))
        deny.clicked.connect(lambda: self.approved.emit(False))
        btn_row.addWidget(allow)
        btn_row.addWidget(deny)
        btn_row.addStretch()
        layout.addLayout(btn_row)
```

- [ ] **Step 3: 冒烟验证**

Run: `python -m shadowtalk.main`
Expected: 定义秘书好友 → 让其"在工作目录写个文档" → 工具调用执行 → 目录外写入时弹出确认卡片 → 允许/拒绝后 AI 继续回复

- [ ] **Step 4: 提交**

```bash
git add shadowtalk/ui/threads/ai_worker.py shadowtalk/ui/main_window.py shadowtalk/ui/widgets/message_bubble.py shadowtalk/ui/widgets/chat_area.py
git commit -m "feat: integrate tool execution and approval card into AIWorker"
```

---

### Task 4: 工作目录配置（settings + 启动创建）

**Files:**
- Modify: `shadowtalk/config/settings.py`
- Modify: `shadowtalk/ui/widgets/settings_dialog.py`
- Modify: `shadowtalk/main.py`（启动创建目录）
- Test: `tests/test_settings.py` 追加

**Interfaces:**
- Consumes: `Settings` 既有机制
- Produces: `Settings.get("work_dir")`（默认 `shadowtalk/workdir/`）；设置对话框"工作目录"行

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_settings.py`：

```python
def test_work_dir_default():
    from shadowtalk.config.settings import Settings
    assert Settings.get("work_dir") == "shadowtalk/workdir/"


def test_work_dir_set_and_get():
    from shadowtalk.config.settings import Settings
    Settings.set("work_dir", "D:/my_work")
    assert Settings.get("work_dir") == "D:/my_work"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL（默认值不存在）

- [ ] **Step 3: 实现**

`settings.py` DEFAULTS 追加：

```python
        "work_dir": "shadowtalk/workdir/",
```

`main.py` 启动创建：

```python
def main():
    Database.get_connection()
    Settings.init_defaults()
    os.makedirs(Settings.get("work_dir"), exist_ok=True)
```

`settings_dialog.py` API 标签页追加一行（参照现有 `api_url_input` 模式）：

```python
        self.work_dir_input = QLineEdit()
        self.work_dir_input.setPlaceholderText("AI 秘书可自由读写此目录")
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_work_dir)
        work_row = QHBoxLayout()
        work_row.addWidget(self.work_dir_input, 1)
        work_row.addWidget(browse_btn)
        api_layout.addRow("工作目录：", work_row)
```

```python
    def _browse_work_dir(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "选择工作目录")
        if path:
            self.work_dir_input.setText(path)
```

保存/加载逻辑同步（`set_text`/`get_data` 模式参照 api_url_input）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add shadowtalk/config/settings.py shadowtalk/ui/widgets/settings_dialog.py shadowtalk/main.py tests/test_settings.py
git commit -m "feat: add work_dir setting with directory browser"
```

---

### Task 5: 回归验证与收尾

**Files:**
- Test: `tests/`（全量）

**Interfaces:**
- Consumes: 全部
- Produces: 无

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS（原 53 + 新 ~13 = ~66 个）

- [ ] **Step 2: 清理检查**

Run: `grep -rn "chat_with_tools\|run_with_approval\|ApprovalCard" shadowtalk/ tests/ | grep -v __pycache__`
Expected: 仅预期引用，无死代码

- [ ] **Step 3: 提交（如有遗漏）**

```bash
git add -A
git commit -m "test: verify tool calling regression" --allow-empty
```
