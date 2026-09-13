"""PythonExecutor 子进程沙箱测试"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from shadowtalk.core.python_executor import (
    ExecResult, _interpreter_args, scan_write_paths, run_code, run_with_approval
)


# ── C1：解释器解析——打包版工具执行不拉起第二个 GUI 实例 ──

def test_interpreter_args_dev_uses_current_executable():
    """非 frozen（开发模式）：沿用当前解释器，行为零变化"""
    assert _interpreter_args() == [sys.executable]


def test_interpreter_args_frozen_uses_bundled_runtime(tmp_path, monkeypatch):
    """frozen（打包版）：使用捆绑的 MEIPASS/python.exe，-I 隔离 + -X utf8"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert _interpreter_args() == [
        str(tmp_path / "python.exe"), "-I", "-X", "utf8"]


def test_interpreter_args_frozen_posix_uses_runtime_python3(tmp_path, monkeypatch):
    """frozen + Linux(.deb)：捆绑解释器在 MEIPASS/runtime/python3"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert _interpreter_args() == [
        str(tmp_path / "runtime" / "python3"), "-I", "-X", "utf8"]


def test_run_code_frozen_uses_bundled_interpreter(tmp_path, monkeypatch):
    """frozen：run_code 用捆绑解释器 + MEIPASS 沙箱前导执行，
    输出按 utf-8 解码，无控制台窗口"""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("shadowtalk.core.python_executor.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    result = run_code("print(1)", str(tmp_path))

    args = captured["args"]
    assert args[:4] == [str(tmp_path / "python.exe"), "-I", "-X", "utf8"]
    assert args[4] == str(tmp_path / "sandbox_prelude.py")  # MEIPASS 前导
    assert args[5] == str(tmp_path)                         # 工作目录已 resolve
    assert args[6] == "[]"                                  # 空审批白名单
    assert args[7].endswith(".py")                          # 用户代码临时文件
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"
    assert captured["kwargs"]["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert result.exit_code == 0


def test_run_code_dev_args_unchanged(tmp_path, monkeypatch):
    """非 frozen：subprocess 参数保持原样（无 encoding/errors，不改 GBK 解码行为）；
    用户代码经沙箱前导临时文件执行"""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("shadowtalk.core.python_executor.subprocess.run", fake_run)

    result = run_code("print(1)", str(tmp_path))

    args = captured["args"]
    assert args[0] == sys.executable
    assert args[1].endswith("sandbox_prelude.py")
    assert args[2] == str(tmp_path)
    assert args[3] == "[]"
    assert args[4].endswith(".py")
    assert "encoding" not in captured["kwargs"]
    assert "errors" not in captured["kwargs"]
    assert "creationflags" not in captured["kwargs"]
    assert result.exit_code == 0


def test_run_code_frozen_posix_uses_start_new_session(tmp_path, monkeypatch):
    """frozen + Linux：不用 Windows 独有的 CREATE_NO_WINDOW（POSIX 下
    该常量不存在，访问即 AttributeError），改用 start_new_session"""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr("shadowtalk.core.python_executor.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    result = run_code("print(1)", str(tmp_path))

    args = captured["args"]
    assert args[:4] == [str(tmp_path / "runtime" / "python3"), "-I", "-X", "utf8"]
    assert captured["kwargs"]["start_new_session"] is True
    assert "creationflags" not in captured["kwargs"]
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert result.exit_code == 0


def test_run_code_timeout_logs_workdir(tmp_path, monkeypatch, caplog):
    """超时分支记录告警日志（M6，含工作目录归因）"""
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr("shadowtalk.core.python_executor.subprocess.run", fake_run)

    with caplog.at_level(logging.WARNING, logger="shadowtalk"):
        result = run_code("sleep", str(tmp_path), timeout=2)

    assert result.timed_out is True
    assert any("工具执行超时" in r.message and str(tmp_path) in r.message
               for r in caplog.records)


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


# ── 扫描器加固：AI 常见的动态路径写法不得绕过审批（用户报告漏洞）──

def test_scan_detects_variable_path_write(tmp_path):
    """变量赋值路径：p = 'C:/x'; open(p, 'w') 必须检出（最常见绕过）"""
    outside = tmp_path.parent / "evil.txt"
    code = f"p = {str(outside)!r}\nopen(p, 'w').write('x')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_fstring_constant_path_write(tmp_path):
    """f-string 全常量拼接路径必须检出"""
    outside = tmp_path.parent / "evil.txt"
    base = str(tmp_path.parent).replace("\\", "/")
    code = f"open(f'{base}/evil.txt', 'w')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_concat_path_write(tmp_path):
    """字符串拼接 'a' + '/b.txt' 必须检出"""
    base = str(tmp_path.parent).replace("\\", "/")
    outside = tmp_path.parent / "evil.txt"
    code = f"open({base!r} + '/evil.txt', 'w')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_mode_keyword(tmp_path):
    """mode 作为关键字参数：open(path, mode='w') 必须检出"""
    outside = tmp_path.parent / "evil.txt"
    code = f"open({str(outside)!r}, mode='w')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_update_mode(tmp_path):
    """r+/w+ 等含 '+' 的模式会写文件，必须检出"""
    outside = tmp_path.parent / "evil.txt"
    code = f"open({str(outside)!r}, 'r+')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_path_open_write(tmp_path):
    """Path(...).open('w')：目标在接收者上而非 args[0]"""
    outside = tmp_path.parent / "evil.txt"
    code = f"from pathlib import Path\nPath({str(outside)!r}).open('w')"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_shutil_copyfile(tmp_path):
    """shutil.copyfile/copy2/copytree 此前完全漏检"""
    outside = tmp_path.parent / "evil.txt"
    code = f"import shutil\nshutil.copyfile('a.txt', {str(outside)!r})"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_detects_os_replace(tmp_path):
    """os.replace 此前漏检（只查了 rename）"""
    outside = tmp_path.parent / "evil.txt"
    code = f"import os\nos.replace('a.txt', {str(outside)!r})"
    paths = scan_write_paths(code, str(tmp_path))
    assert any(p == outside for p in paths)


def test_scan_variable_inside_write_not_flagged(tmp_path):
    """变量路径但落在工作目录内：不误报"""
    code = "p = 'ok.txt'\nopen(p, 'w')"
    assert scan_write_paths(code, str(tmp_path)) == []


def test_scan_dynamic_unresolvable_not_flagged(tmp_path):
    """完全动态路径（input/函数参数）：静态层放行，由运行时沙箱兜底"""
    code = "def w(name):\n    open(name, 'w')\nw('ok.txt')"
    assert scan_write_paths(code, str(tmp_path)) == []


# ── 运行时沙箱：审计钩子硬拦截（静态扫描追不完动态构造的路径）──

def test_run_code_blocks_dynamic_outside_write(tmp_path):
    """运行时拼接的目录外路径：静态扫描看不见，沙箱必须拦下且文件不落盘"""
    outside = tmp_path.parent / "evil.txt"
    base = str(tmp_path.parent).replace("\\", "/")
    code = (f"parts = ['{base}', '/', 'evil.txt']\n"
            f"open(''.join(parts), 'w').write('x')")
    result = run_code(code, str(tmp_path))
    assert result.exit_code != 0
    assert "未获用户授权" in result.stderr
    assert not outside.exists()


def test_run_code_blocks_relative_escape(tmp_path):
    """../ 相对路径逃逸工作目录：必须拦截"""
    outside = tmp_path.parent / "evil.txt"
    result = run_code("open('../evil.txt', 'w').write('x')", str(tmp_path))
    assert result.exit_code != 0
    assert not outside.exists()


def test_run_code_blocks_shutil_move_outside(tmp_path):
    """shutil.move 移动到目录外：必须拦截"""
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path.parent / "moved.txt"
    code = f"import shutil\nshutil.move({str(src)!r}, {str(dst)!r})"
    result = run_code(code, str(tmp_path))
    assert result.exit_code != 0
    assert not dst.exists()


def test_run_code_allows_approved_outside_write(tmp_path):
    """经用户审批的目录外路径：allowed_paths 白名单放行"""
    outside = tmp_path.parent / "approved.txt"
    code = f"open({str(outside)!r}, 'w').write('y')"
    result = run_code(code, str(tmp_path), allowed_paths=[str(outside)])
    assert result.exit_code == 0, result.stderr
    assert outside.exists()


def test_run_code_allows_inside_write_with_dynamic_name(tmp_path):
    """动态文件名但落在工作目录内：正常放行（不误伤日常用法）"""
    result = run_code(
        "name = 'out' + str(1) + '.txt'\n"
        "from pathlib import Path\n"
        "Path(name).write_text('ok', encoding='utf-8')",
        str(tmp_path))
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "out1.txt").exists()


# ── 工作目录自动创建（换机迁移自愈）──

def test_run_code_creates_missing_workdir(tmp_path):
    """工作目录不存在时自动创建。

    回归（用户报告：秘书/小女儿"文件操作功能暂时失灵"）：换机后
    work_dir 指向旧机器绝对路径，subprocess 的 cwd 不存在直接抛错。
    """
    workdir = tmp_path / "migrated" / "ai-works" / "6"
    assert not workdir.exists()

    result = run_code(
        "from pathlib import Path\n"
        "Path('report.txt').write_text('hello', encoding='utf-8')",
        str(workdir))

    assert result.exit_code == 0, result.summary()
    assert (workdir / "report.txt").read_text(encoding="utf-8") == "hello"


def test_run_with_approval_creates_missing_workdir(tmp_path):
    """审批入口同样自动创建缺失的工作目录"""
    workdir = tmp_path / "nested" / "dir"
    result = run_with_approval(
        "print('ok')", str(workdir), approver=lambda p, r: True)

    assert result.exit_code == 0, result.summary()
    assert workdir.is_dir()
