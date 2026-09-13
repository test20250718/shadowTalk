# ShadowTalk 便携打包与本地日志 — 设计文档

日期：2026-08-13
状态：已批准（用户确认：exe 旁便携目录 + 全量运行日志）

## 目标

1. 用 PyInstaller 将 ShadowTalk 编译为 Windows exe，可在另一台电脑双击运行。
2. 全量运行日志落盘到本地文件，使无控制台的 exe 环境下可监控 bug（异常堆栈、运行轨迹、AI 工具执行记录）。
3. 数据（数据库、日志、头像）统一放在 exe 所在目录，便携可带走。

## 背景与现状

- 项目完全依赖 `print` 输出诊断信息（无 `logging` 模块）——windowed exe 无控制台，print 不可见。
- 数据路径全部是相对路径：`DB_PATH = "shadowtalk.db"`、`"data/avatars"`、`"data/logs"`、`"logs/chat_prompts"`——双击 exe 时工作目录不确定，数据会散落或找不到。
- PythonExecutor 子进程输出已捕获（`capture_output=True`，stdout/stderr 返回给 AI），但未落盘。
- 无 `sys.excepthook` / `threading.excepthook` / `faulthandler`，异常不可追踪。

## 架构

三个组件，互相独立：

```
┌─────────────────────┐   ┌──────────────────────────┐   ┌──────────────────┐
│ shadowtalk/config/  │   │ shadowtalk/config/       │   │ ShadowTalk.spec  │
│ paths.py            │   │ app_logger.py            │   │ (PyInstaller)    │
│ 基目录抽象          │   │ 日志 + 崩溃捕获           │   │ 打包配置         │
└─────────────────────┘   └──────────────────────────┘   └──────────────────┘
        │                             │
        ▼                             ▼
  database.py / main.py /       main_window.py / ai_worker.py /
  friend_service.py /           python_executor.py /
  prompt_logger.py              background_scanner.py
```

### 1. 基目录抽象 `shadowtalk/config/paths.py`

```python
def get_base_dir() -> Path:
    """数据根目录：打包后为 exe 所在目录（便携），开发时为当前工作目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()
```

调用点改造（全部改为 `get_base_dir() / ...`）：

| 文件 | 现状 | 改为 |
|---|---|---|
| `shadowtalk/data/database.py:5` | `DB_PATH = "shadowtalk.db"` | `DB_PATH = str(get_base_dir() / "shadowtalk.db")` |
| `shadowtalk/main.py:4-5` | `os.makedirs("data/avatars")` / `"data/logs"` | `os.makedirs(get_base_dir()/"data"/"avatars")` 等 |
| `shadowtalk/core/friend_service.py:9` | `AVATAR_DIR = "data/avatars"` | `AVATAR_DIR = str(get_base_dir()/"data"/"avatars")` |
| `shadowtalk/core/prompt_logger.py:22` | `"logs", "chat_prompts"` | `get_base_dir()/"logs"/"chat_prompts"` |

兼容性：开发时 cwd = 项目根，行为零变化；已有数据库 `shadowtalk.db` 在项目根，位置不变。打包后数据全在 exe 旁。

### 2. 日志模块 `shadowtalk/config/app_logger.py`

提供 `setup_logging()`，在 `main.py` 的 `main()` 开头调用：

- **运行日志**：`logging` + `RotatingFileHandler` → `data/logs/app.log`
  - `maxBytes=2_000_000`（2MB）、`backupCount=5`
  - **`encoding="utf-8"`**（Windows 默认 GBK，中文日志必坑）
  - 格式：`%(asctime)s %(levelname)s %(name)s: %(message)s`
  - 开发时（非 frozen）加 `StreamHandler` 镜像到控制台，保留现有 print 可见性
- **未捕获异常**：安装 `sys.excepthook` 与 `threading.excepthook`，写入 `logger.critical` 完整堆栈（含 `threading.excepthook` 的线程名）——AIWorker 跑在 QThread，线程异常靠它兜住
- **原生崩溃**：`faulthandler.enable(open(data/logs/faulthandler.log, "w"))`，覆盖致命信号（Windows 上为访问违规/段错误、FPE、ABRT、ILL、BUS、TERM）与未处理异常导致进程终止时，转储全部线程堆栈；faulthandler 的死锁检测（`dump_traceback_later` 看门狗定时转储）仅 Unix 可用，Windows 下不可用
- 顶层 `shadowtalk` logger 命名空间，模块内 `logger = logging.getLogger(__name__)`
- handlers 仅挂在 `shadowtalk` 命名空间下：openai / httpx / requests 等第三方库的日志不入 app.log（后续需要可通过 logging 配置单独补上）

关键路径日志（全量）：

| 调用点 | 级别 | 内容 |
|---|---|---|
| `main_window._on_message_sent` | info | 好友名、消息长度 |
| `main_window._on_ai_reply` / `_on_ai_failed` | info / error | 回复长度或错误信息 |
| `main_window` 构建上下文异常（241-243 行 print） | error | 异常堆栈 |
| `ai_worker._run_tool` | info | 工具执行请求（代码片段、原因） |
| `ai_worker` 空目录拒绝分支 | warning | 拒绝文案 |
| `python_executor.run_with_approval` | info | 退出码 + stdout/stderr 摘要（截断） |
| `python_executor` 目录外写审批 | info | 审批请求路径列表 + 结果 |
| `background_scanner` | info | 扫描结果（归档消息数） |
| `prompt_logger.log_conversation` | info | 日志文件路径 |

现有 `print` 保留不动（开发 console 仍可见；关键处已在 logging 覆盖）。

### 3. PyInstaller 打包 `ShadowTalk.spec`

项目根新建 `ShadowTalk.spec`（参考 `aiworkspace15/xTools.spec` 的结构）：

- `EXE(..., console=False)`：windowed，无黑框
- PySide6 插件与 openai 依赖：PyInstaller 6.x 自动收集（内置 hooks），无需手写 hiddenimports；若缺则补 `--collect-all`（见冒烟验证）
- **捆绑 Python 运行时**：frozen 版工具执行不再拉起第二个 GUI 实例——spec 的 `datas` 从构建环境 `sys.base_prefix` 收集 `python.exe`、`python311.dll`、`python3.dll`、`vcruntime140*.dll`（→ MEIPASS 根）以及 `Lib/`（仅标准库，排除 site-packages）与 `DLLs/`；frozen 模式子进程用 `MEIPASS/python.exe -I -X utf8` 启动（`-I` 隔离模式，输出按 utf-8 解码，`CREATE_NO_WINDOW` 避免黑框闪现）。产物实测增大 ~16MB（68→84MB，UPX 压缩标准库）；AI 工具执行在打包版完整可用
- 产物：`dist/ShadowTalk/ShadowTalk.exe`，拷贝即用

## 错误处理与边界

- **Windows 中文路径**：`data` 目录可能含中文用户名路径（`C:\Users\张三\...`），logging 与数据库均用 utf-8；测试覆盖中文路径用例。
- **日志轮转**：文件被占用（杀毒软件/编辑器打开）时 RotatingFileHandler 可能报错——`setup_logging` 内 try/except，日志失败不阻塞程序启动。
- **frozen 判断**：`getattr(sys, "frozen", False)` 是 PyInstaller 标准检测；开发时永远走 cwd 分支。
- **exe 重复启动**：SQLite WAL 模式允许多进程但易锁——日志功能不处理该问题（范围外）。

## 测试策略

| 测试 | 内容 |
|---|---|
| `tests/test_paths.py` | monkeypatch `sys.frozen=True` + `sys.executable` → base_dir 为 exe 目录；未 frozen → cwd；中文路径 |
| `tests/test_app_logger.py` | setup_logging 写文件；RotatingFileHandler 配置；excepthook 触发后日志含堆栈；线程 excepthook |
| `tests/test_database.py` 追加 | DB 文件落在 base_dir 下 |
| 全量回归 | 现有 80 测试全绿 |
| 打包冒烟 | `pyinstaller ShadowTalk.spec` 后运行 exe：正常启动、`data/logs/app.log` 出现、窗口显示 |

## 打包数据策略（空数据库）

**打包产物不携带任何运行时数据**——数据库、日志、头像、提示词日志一律不收集：

- `ShadowTalk.spec` 的 `datas` 保持为空（不收集 `shadowtalk.db`、`data/`、`logs/`、`logs/chat_prompts/`）。
- exe 首启自动创建空库（`Database.get_connection()` 的 CREATE IF NOT EXISTS + `_migrate`），表结构完整、无任何数据；`app_config` 无 api_key（用户在新机器上自行填写）。
- 开发机上的测试数据（聊天记录、AI 上下文、API key、头像、提示词日志）**不会进入产物**。
- 打包冒烟验证增加一项：exe 首启后 `shadowtalk.db` 存在且 `friends` / `chat_messages` 表为空、`app_config` 中 `api_key` 为空。

## 迁移说明（用户文档）

- 开发/源码运行：数据库位置不变（项目根 `shadowtalk.db`）。
- exe 使用原聊天记录：将 `shadowtalk.db` 复制到 exe 所在目录即可（关闭程序后复制；注意会带上 API key 与测试记录，按需取舍）。
- 日志位置：`<exe目录>/data/logs/app.log`、`faulthandler.log`；上下文提示词日志 `<exe目录>/logs/chat_prompts/`。

## 范围外（YAGNI）

- 自动更新、崩溃报告上传、远程日志
- exe 图标与版本资源（可后续单加）
- 数据迁移工具（手动复制文件即可）
- 多实例锁
