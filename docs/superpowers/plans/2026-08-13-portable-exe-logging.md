# ShadowTalk 便携打包与本地日志 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 PyInstaller 把 ShadowTalk 编译为便携 exe（数据全在 exe 旁、产物零数据），并把全量运行日志落盘到 `data/logs/`，使无控制台环境下可监控 bug。

**Architecture:** 三个独立组件——`shadowtalk/config/paths.py`（基目录抽象，frozen 检测）、`shadowtalk/config/app_logger.py`（logging 轮转文件 + 崩溃捕获钩子）、`ShadowTalk.spec`（PyInstaller 打包配置）。日志通过 `logging` 命名空间埋点，不改动现有业务逻辑。

**Tech Stack:** Python 3.11、PySide6、PyInstaller（需 `pip install pyinstaller`，当前未安装）、pytest。

## Global Constraints

- 打包产物**不携带任何运行时数据**：spec 的 `datas` 为空，不收集 `shadowtalk.db`、`data/`、`logs/`、`logs/chat_prompts/`；exe 首启自动建空库
- 数据根目录：打包后 = exe 所在目录（`sys.frozen` 时 `Path(sys.executable).parent`）；开发时 = 当前工作目录（行为零变化）
- 日志文件编码 **utf-8**（Windows 默认 GBK，中文日志必乱码）
- `setup_logging()` 内 try/except：日志初始化失败不阻塞程序启动
- 现有 `print` 保留不动；关键路径新增 logging 调用
- 所有测试遵守现有 conftest 的临时 DB 隔离（monkeypatch `shadowtalk.data.database.DB_PATH`）

---

### Task 1: 基目录抽象 — paths.py + 4 个调用点

**Files:**
- Create: `shadowtalk/config/paths.py`
- Modify: `shadowtalk/data/database.py:5`（DB_PATH）
- Modify: `shadowtalk/main.py:4-5`（makedirs）
- Modify: `shadowtalk/core/friend_service.py:9`（AVATAR_DIR）
- Modify: `shadowtalk/core/prompt_logger.py:22`（logs/chat_prompts）
- Test: `tests/test_paths.py`（新建）、`tests/test_database.py`（追加）

**Interfaces:**
- Produces: `get_base_dir() -> pathlib.Path` — 数据根目录。`sys.frozen` 时为 `Path(sys.executable).parent`，否则 `Path.cwd()`。Task 2 的 app_logger 依赖它定位 `data/logs`。

- [ ] **Step 1: 写失败测试 `tests/test_paths.py`**

```python
"""get_base_dir 测试：frozen（打包态）与开发态"""
import sys
from pathlib import Path
from shadowtalk.config.paths import get_base_dir


def test_returns_cwd_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr("shadowtalk.config.paths.Path.cwd",
                        lambda: Path("C:/work/aiworkspace18"))
    assert get_base_dir() == Path("C:/work/aiworkspace18")


def test_returns_exe_dir_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable",
                        "D:/ShadowTalk/ShadowTalk.exe")
    assert get_base_dir() == Path("D:/ShadowTalk")


def test_exe_dir_with_chinese_path(monkeypatch):
    """Windows 中文路径（用户名等）下定位正确"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable",
                        "C:/Users/张三/桌面/影聊/ShadowTalk.exe")
    assert get_base_dir() == Path("C:/Users/张三/桌面/影聊")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadowtalk.config.paths'`

- [ ] **Step 3: 实现 `shadowtalk/config/paths.py`**

```python
# shadowtalk/config/paths.py
"""数据根目录定位：打包后为 exe 所在目录（便携），开发时为当前工作目录"""
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_paths.py -v`
Expected: 3 passed

- [ ] **Step 5: 改造 4 个调用点**

`shadowtalk/data/database.py:5`：
```python
from shadowtalk.config.paths import get_base_dir
DB_PATH = str(get_base_dir() / "shadowtalk.db")
```
（import 放在文件顶部现有 import 区）

`shadowtalk/main.py:4-5`：
```python
from shadowtalk.config.paths import get_base_dir
os.makedirs(get_base_dir() / "data" / "avatars", exist_ok=True)
os.makedirs(get_base_dir() / "data" / "logs", exist_ok=True)
```

`shadowtalk/core/friend_service.py:9`：
```python
AVATAR_DIR = str(get_base_dir() / "data" / "avatars")
```
（friend_service.py 需新增 `from shadowtalk.config.paths import get_base_dir`；检查 AVATAR_DIR 是否被其他模块 import，若被 import 则字符串值保持不变）

`shadowtalk/core/prompt_logger.py:22`（`log_conversation` 内）：
```python
base_dir = get_base_dir()
folder = base_dir / "logs" / "chat_prompts" / folder_name
```

- [ ] **Step 6: 追加数据库落位测试 `tests/test_database.py`**

```python
def test_db_path_under_base_dir(monkeypatch):
    """DB 文件应位于基目录下（打包后 = exe 目录）"""
    import shadowtalk.data.database as db_module
    base = db_module.get_base_dir()
    assert db_module.DB_PATH == str(base / "shadowtalk.db")
```

- [ ] **Step 7: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（现有 80 + 新 4）

```bash
git add shadowtalk/config/paths.py shadowtalk/data/database.py shadowtalk/main.py \
        shadowtalk/core/friend_service.py shadowtalk/core/prompt_logger.py \
        tests/test_paths.py tests/test_database.py
git commit -m "feat: base-dir abstraction for portable data location"
```

注意：`git add` 只加上述文件，绝不 `git add -A`（工作区有 `../aiworkspace15/`、`.pyc`、`shadowtalk/workdir/` 等无关文件）。

---

### Task 2: 日志模块 — app_logger.py + 启动接入

**Files:**
- Create: `shadowtalk/config/app_logger.py`
- Modify: `shadowtalk/main.py`（main() 开头调用 setup_logging）
- Test: `tests/test_app_logger.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `get_base_dir()`（定位 `data/logs`）
- Produces: `setup_logging() -> None` — 配置 RotatingFileHandler + 崩溃捕获钩子。Task 3 埋点直接用 `logging.getLogger(__name__)`，无需再配置。

- [ ] **Step 1: 写失败测试 `tests/test_app_logger.py`**

```python
"""app_logger 测试：日志落盘 + 崩溃捕获"""
import logging
import sys
import threading
from shadowtalk.config.app_logger import setup_logging


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
        threading.excepthook(
            threading.ExceptHookArgs(
                exc_type=RuntimeError, exc_value=sys.exc_info()[1],
                exc_traceback=sys.exc_info()[2], thread=threading.current_thread()))
    text = _file_text(log_file)
    assert "线程异常" in text


def test_setup_failure_does_not_block(tmp_path, monkeypatch):
    """日志目录不可创建时，setup_logging 不抛异常"""
    monkeypatch.setattr(
        "shadowtalk.config.app_logger.APP_LOG_PATH",
        tmp_path / "不存在" / "x" / "app.log")  # 父目录不存在
    setup_logging()  # 不应抛异常
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_app_logger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadowtalk.config.app_logger'`

- [ ] **Step 3: 实现 `shadowtalk/config/app_logger.py`**

```python
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


def setup_logging():
    """初始化日志（幂等，失败不阻塞启动）。main() 开头调用一次。"""
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
        with open(FAULT_LOG_PATH, "w", encoding="utf-8") as f:
            faulthandler.enable(f)
    except Exception as e:
        print(f"[app_logger] faulthandler 初始化失败: {e}")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_app_logger.py -v`
Expected: 4 passed

- [ ] **Step 5: `main.py` 接入**

在 `main()` 第一行加：
```python
from shadowtalk.config.app_logger import setup_logging
setup_logging()
```
（import 放模块顶部 import 区；调用放 `main()` 内 `Database.get_connection()` 之前）

- [ ] **Step 6: 冒烟验证**

Run: `timeout 8 python -X utf8 -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from shadowtalk.main import main; main()"`（8 秒后 timeout 杀掉阻塞的 GUI 事件循环；`main()` 中 setup_logging 在 `app.exec()` 之前已执行，日志已写入）
Expected: `data/logs/app.log` 与 `faulthandler.log` 文件存在且非空。验证后删除生成的文件（仅删 `data/logs/` 下本次生成内容，`data/avatars` 保留）。

- [ ] **Step 7: 提交**

```bash
git add shadowtalk/config/app_logger.py shadowtalk/main.py tests/test_app_logger.py
git commit -m "feat: local file logging with crash capture hooks"
```

---

### Task 3: 关键路径日志埋点

**Files:**
- Modify: `shadowtalk/ui/main_window.py`（`_on_message_sent`、`_on_ai_reply`、`_on_ai_failed`、构建上下文异常）
- Modify: `shadowtalk/ui/threads/ai_worker.py`（`_run_tool` 请求与空目录拒绝）
- Modify: `shadowtalk/core/python_executor.py`（`run_with_approval` 结果）
- Modify: `shadowtalk/core/prompt_logger.py`（`log_conversation` 返回路径）
- Modify: `shadowtalk/core/background_scanner.py`（`scan_now` 结果）
- Test: `tests/test_logging_points.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 logging 配置（已生效）。各模块内 `logger = logging.getLogger(__name__)`。

- [ ] **Step 1: 写失败测试 `tests/test_logging_points.py`**

```python
"""关键路径日志埋点测试：caplog 捕获 logging 调用"""
import logging
from shadowtalk.core.prompt_logger import log_conversation


def test_prompt_logger_emits_info(caplog):
    with caplog.at_level(logging.INFO, logger="shadowtalk"):
        log_conversation(
            friend_name="测试", friend_id=1,
            context=[{"role": "user", "content": "你好"}],
            user_message="你好", ai_reply="回复")
        assert any(
            "chat_prompts" in r.message and "测试" in r.message
            for r in caplog.records
            if r.name == "shadowtalk.core.prompt_logger")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_logging_points.py -v`
Expected: FAIL — caplog 无匹配记录

- [ ] **Step 3: 埋点（每个文件顶部加 `logger = logging.getLogger(__name__)`，`import logging` 若无）**

`prompt_logger.py`（`log_conversation` 成功返回 filepath 前）：
```python
logger.info("提示词日志已写入: %s", filepath)
```

`main_window.py`：
- `_on_message_sent`（MessageRepository.insert 后）：
  ```python
  logger.info("发消息: 好友=%s 长度=%d", self._pending_friend_name, len(text))
  ```
- 构建上下文异常分支（原 print 处）：
  ```python
  logger.error("构建上下文失败: %s", e, exc_info=True)
  ```
- `_on_ai_reply`（add_message 后）：
  ```python
  logger.info("AI 回复: 好友=%s 长度=%d", self._pending_friend_name, len(reply))
  ```
- `_on_ai_failed`：
  ```python
  logger.error("AI 回复失败: %s", error)
  ```

`ai_worker.py` `_run_tool`：
- 空目录拒绝分支（return 前）：
  ```python
  logger.warning("拒绝工具执行: 未配置工作目录")
  ```
- 正常执行前：
  ```python
  logger.info("执行工具: reason=%s", reason)
  ```

`python_executor.py` `run_code`（第 106-110 行，`ExecResult` 构造后 return 前）：
```python
logger.info("工具执行: 退出码=%s 输出=%s字符", proc.returncode,
            len(proc.stdout or "") + len(proc.stderr or ""))
```
（`run_code` 第 99 行 `proc = subprocess.run(...)` 处已有 returncode 可用；拒绝分支 `run_with_approval:130` 的 `user_denied` 结果在 ai_worker 的审批逻辑里已有返回，无需另加）

`background_scanner.py` `scan_now`（第 21 行循环后，函数末尾）：
```python
logger.info("摘要扫描完成: %d 个好友", len(friends))
```
（文件顶部加 `import logging` + `logger = logging.getLogger(__name__)`；`_scan_friend` 的 expired 分支不加——正常扫描无过期属预期，避免噪音）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_logging_points.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

```bash
git add shadowtalk/ui/main_window.py shadowtalk/ui/threads/ai_worker.py \
        shadowtalk/core/python_executor.py shadowtalk/core/prompt_logger.py \
        shadowtalk/core/background_scanner.py tests/test_logging_points.py
git commit -m "feat: instrument key paths with file logging"
```

---

### Task 4: PyInstaller 打包 + 冒烟验证

**Files:**
- Create: `ShadowTalk.spec`
- 产物（不提交）: `build/`、`dist/ShadowTalk/ShadowTalk.exe`

- [ ] **Step 1: 安装 PyInstaller**

Run: `pip install pyinstaller`
Expected: 安装成功

- [ ] **Step 2: 写 `ShadowTalk.spec`**

```python
# ShadowTalk.spec — 便携打包。datas 为空：产物不携带任何运行时数据
# （数据库、日志、头像、提示词日志均不收集，首启自动创建空库）
a = Analysis(
    ["shadowtalk/main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["openai"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ShadowTalk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed：无黑框
    disable_windowed_traceback=False,
)
```

（若 `upx=True` 打包报错或 UPX 不存在，改为 `upx=False` 重试）

- [ ] **Step 3: 打包**

Run: `pyinstaller --noconfirm ShadowTalk.spec`
Expected: `dist/ShadowTalk/ShadowTalk.exe` 生成

- [ ] **Step 4: 冒烟验证（关键验收）**

在**空目录**下运行打包产物（确保不依赖开发环境 cwd）：
```bash
mkdir -p /c/work/aiworkspace18/smoke && cp dist/ShadowTalk/ShadowTalk.exe smoke/
cd smoke && timeout 15 ./ShadowTalk.exe &
sleep 12
ls data/ 2>/dev/null          # 期望: avatars/ logs/
ls data/logs/app.log          # 期望: 存在且非空
ls shadowtalk.db 2>/dev/null  # 期望: 存在（首启自动建空库）
```

然后用 Python 检查空库（无测试数据）：
```bash
python -X utf8 -c "
import sqlite3
conn = sqlite3.connect('smoke/shadowtalk.db')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
print('tables:', tables)
print('friends:', conn.execute('SELECT COUNT(*) FROM friends').fetchone()[0])
print('messages:', conn.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0])
print('api_key:', repr(conn.execute('SELECT value FROM app_config WHERE key=?', ('api_key',)).fetchone()))
conn.close()"
```
Expected: friends=0、messages=0、api_key=None（或空）、日志文件存在。

若 `ShadowTalk.exe` 无法在当前 shell 直接拉起（GUI 程序挂起/超时被 timeout 杀），改用后台启动 + `sleep` 后检查文件再 `taskkill //F //IM ShadowTalk.exe`（注意 kill 时机，确保首启建库与写日志已完成）。

- [ ] **Step 5: 清理冒烟产物**

Run: `rm -rf smoke/ build/`（`dist/ShadowTalk/ShadowTalk.exe` 保留供用户试用；若用户不要产物也可删除，询问用户）

- [ ] **Step 6: 提交 spec 文件**

```bash
git add ShadowTalk.spec
git commit -m "build: add PyInstaller spec for portable ShadowTalk exe"
```

注意：`build/`、`dist/`、`smoke/` 绝不提交（`git status` 确认后按需追加 `*.spec` 之外的忽略规则——不修改 .gitignore，仅确保不 add）。

---

## 收尾

全部任务完成后：
1. 全量回归 `python -m pytest tests/ -q`（预期 80 + 3 任务新增 ≈ 90）
2. 用 superpowers:subagent-driven-development 走完任务审查 + 最终 whole-branch review
3. 用 superpowers:finishing-a-development-branch 收尾（与上次相同：无 remote/feature branch，保持 master 现状）
4. 向用户报告：exe 位置、空库验证结果、日志文件位置、迁移说明
