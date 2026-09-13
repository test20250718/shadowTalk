# AI 秘书工具调用（Tool Calling）设计

日期：2026-08-12
状态：已获用户批准（方案 A：子进程执行沙箱）

## 背景

ShadowTalk 目前是纯对话模式（`AIClient.chat()` 只发 role/content 消息，无 tools 声明）。用户希望定义一位"秘书"类 AI 时，它能执行 Python 代码来写文档、处理数据等。经确认的安全模型与交互：

- **工作目录内**（设置中配置，默认 `shadowtalk/workdir/`）：AI 自由读写，无需授权
- **工作目录外**：读文件无需授权，**写文件必须经用户在聊天内确认**
- **网络**：允许联网（用户已知晓"联网+读任意文件=数据可能外泄"风险）
- **限制**：单次代码执行 30 秒超时；每轮对话最多 5 次工具调用
- **授权形式**：聊天内确认卡片（AI 气泡下方显示"秘书想写文件 X，允许吗？"）

## 设计目标

- 让 AI 能通过 Function Calling 执行 Python 代码，并把结果（输出/错误/超时）回传给模型继续对话
- 代码在子进程沙箱中运行，卡死/崩溃不影响主 UI
- 写操作按"工作目录内自由、目录外需确认"规则管控

## 架构

### 组件 1：`shadowtalk/core/python_executor.py`（纯 Python，无 UI 依赖）

```
PythonExecutor.run_with_approval(code, workdir, approver) -> ExecResult
```

- **AST 预扫描** `scan_write_paths(code, workdir) -> list[Path]`：解析代码的写操作目标——
  - `open(path, 'w'|'a'|...)`（含 `Path.open`）
  - `Path.write_text/write_bytes`、`os.rename/move/copy`、`os.mkdir/makedirs`、`shutil.copy/move`
  - 相对路径按 workdir 解析
  - 判定：目标在 workdir 内 → 直接放行；目录外 → 列入待审批
- **审批回调**：扫描到目录外写 → 调 `approver(paths) -> bool`（UI 层注入）；拒绝 → 返回 `ExecResult(user_denied=True)` 而不执行
- **子进程执行**：`subprocess.Popen([sys.executable, "-c", code], cwd=workdir, timeout=30)`，捕获 stdout/stderr/退出码；超时 kill 并标记 `timed_out=True`
- 执行后兜底：检查进程退出码与是否超时，如实回传

### 组件 2：`AIClient` 扩展（`ai_client.py`）

- 新增 `chat_with_tools(messages, tool_runner) -> str`：
  1. 声明工具 schema：`run_python(code: str, reason: str)`（reason 让模型说明意图，展示给用户）
  2. 多轮循环：调用带 `tools` 参数 → 若响应含 `tool_calls` → 逐个执行（经 `tool_runner`，UI 注入）→ 追加 `role:"tool"` 消息 → 再调用；循环上限 5 次
  3. 最终返回模型最终文本
- 保持 `chat()` 原样（向后兼容）；模型不支持 tools 时 catch 异常回退 `chat()`

### 组件 3：`AIWorker` 扩展（`ai_worker.py`）

- 构造函数增加参数：`work_dir`、`approval_requested`（Signal(list[Path], str reason)）、`approval_answered`（由主线程接收确认卡片结果）
- `run()`：改用 `chat_with_tools`，工具执行时把审批请求经信号发到主线程，用 `QEventLoop` 嵌套事件循环阻塞等待用户批准/拒绝（主线程仍响应 UI 点击）

### 组件 4：UI 确认卡片（`message_bubble.py` 新增 `ApprovalCard(QWidget)`）

- 显示：文件路径列表 + 模型给的 reason + [允许] [拒绝] 按钮
- 点击后发出 `approved = Signal(bool)`，主线程回传 AIWorker

### 组件 5：设置（`settings.py` / `settings_dialog.py`）

- 新增配置项 `work_dir`，默认 `shadowtalk/workdir/`（程序启动时自动创建）
- 设置对话框新增"工作目录"输入框 + 浏览按钮（QFileDialog）

### 数据流

```
用户消息 → build_context → AIWorker.run()
  → AIClient.chat_with_tools(messages, tool_runner)
    → 模型请求 run_python(code, reason)
    → PythonExecutor.run_with_approval
      → scan_write_paths: 目录内→执行 / 目录外→approver 回调
        → (UI) ApprovalCard 显示 → 用户批准/拒绝 → 回传
    → 结果 {stdout, stderr, exit_code, timed_out, user_denied} 追加 tool 消息
    → 模型继续 → 最终文本 → finished 信号 → 聊天区显示
```

## 错误处理

| 场景 | 处理 |
|------|------|
| 模型不支持 tools | catch 异常 → 回退 `chat()` 纯文本 |
| 代码超时 30s | 返回 `执行超时（30s）` 给模型 |
| 用户拒绝写入 | 返回 `用户拒绝了写入，请改用工作目录内路径或询问用户` |
| 子进程崩溃/语法错误 | 返回退出码 + stderr |
| 工具循环超 5 次 | 强制停止，返回已执行结果摘要 |

## 测试

- `python_executor`：目录内写直接执行；目录外写触发审批回调；拒绝时不执行；30s 超时 kill；语法错误返回 stderr
- `AIClient.chat_with_tools`：mock 响应含 tool_calls → fake runner 执行 → 断言追加了 tool 消息并最终返回文本；循环超 5 次停止；tools 不支持回退
- UI ApprovalCard：允许/拒绝信号流转（可选，offscreen 测试）

## 范围外（YAGNI）

- Docker/容器沙箱
- 非 Python 语言执行
- 工具执行的撤销/回滚
- 历史工具调用记录 UI
