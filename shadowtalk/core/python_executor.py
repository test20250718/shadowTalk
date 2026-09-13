# shadowtalk/core/python_executor.py
"""
Python 子进程沙箱：AI 工具调用的代码执行器
- 子进程隔离执行，30 秒超时
- AST 扫描写操作目标，目录外写入需审批回调
"""
import ast
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


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


def _literal(node, consts: dict):
    """尽力把 AST 表达式折叠成字符串常量：str 常量 / 已知变量 /
    f-string（全常量片段）/ 字符串拼接。折叠不出来返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                s = _literal(v.value, consts)
                if not isinstance(s, str):
                    return None
                parts.append(s)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left, consts)
        right = _literal(node.right, consts)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    return None


def _string_consts(tree) -> dict:
    """模块级简单常量传播：NAME = <可折叠字符串>（AI 常见写法
    p = r"C:/x.txt"; open(p, "w")，不传播则审批被完全绕过）"""
    consts: dict = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            v = _literal(node.value, consts)
            if isinstance(v, str):
                consts[node.targets[0].id] = v
    return consts


def _module_alias(node, aliases: dict) -> bool:
    """attr 调用的接收者是否是 os/shutil 模块（含 import 别名）"""
    fn = node.func
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        return aliases.get(fn.value.id) in ("os", "shutil", "posixpath")
    return False


def scan_write_paths(code: str, workdir: str) -> list[Path]:
    """
    AST 扫描代码中的写操作目标路径，返回工作目录外的绝对路径列表。

    支持的写操作（含目标为变量/f-string/拼接的常量传播）：
    open(..., 'w'/'a'/'x'/'+')、Path.write_text/write_bytes/mkdir/unlink/
    rmdir/touch、Path(...).open('w')、os.rename/replace/move/copy*、
    shutil.copy*/move/rmtree/makedirs。

    静态层只负责尽早弹出审批卡（UX）；完全动态的路径放行，
    由 sandbox_prelude 的运行时审计钩子硬拦截兜底。
    """
    workdir = Path(workdir).resolve()
    targets: list[Path] = []
    aliases: dict = {}   # import os as o → {o: "os"}
    consts: dict = {}

    def resolve(expr) -> list[Path]:
        raw = _literal(expr, consts)
        if isinstance(raw, str):
            p = Path(raw)
            if not p.is_absolute():
                p = workdir / p
            return [p]
        return []

    def receiver_path(call) -> list[Path]:
        """Path(...).open('w') 等接收者上的目标路径"""
        fn = call.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Call):
            inner = fn.value.func
            iname = inner.attr if isinstance(inner, ast.Attribute) else (
                inner.id if isinstance(inner, ast.Name) else "")
            if iname == "Path" and fn.value.args:
                return resolve(fn.value.args[0])
        return []

    def mode_is_write(mode_node) -> bool:
        if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
            return any(c in mode_node.value for c in "wax+")
        return False

    ONE_ARG = ("write_text", "write_bytes", "mkdir", "makedirs", "remove",
               "unlink", "rmdir", "rmtree", "touch", "truncate")
    TWO_ARG = ("rename", "replace", "move", "copy", "copy2", "copyfile",
               "copytree")

    def collect(node) -> None:
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in ("os", "shutil", "posixpath"):
                    aliases[a.asname or a.name] = a.name
            return
        if isinstance(node, ast.ImportFrom) and node.module in ("os", "shutil"):
            for a in node.names:
                aliases[a.asname or a.name] = node.module
            return
        if not isinstance(node, ast.Call):
            return
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else (
            fn.attr if isinstance(fn, ast.Attribute) else "")
        if not fname:
            return

        # open(path, mode) / open(path, mode=...)；Path(...).open(mode)
        if fname == "open":
            if isinstance(fn, ast.Attribute):
                # Path(...).open('w')：mode 在 args[0]，目标在接收者
                if node.args and mode_is_write(node.args[0]):
                    targets.extend(receiver_path(node))
                return
            mode_node = node.args[1] if len(node.args) >= 2 else None
            for kw in node.keywords:
                if kw.arg == "mode":
                    mode_node = kw.value
            if mode_node is not None and mode_is_write(mode_node) and node.args:
                targets.extend(resolve(node.args[0]))
            return

        if fname in ONE_ARG:
            # Path 对象方法 → 接收者优先；os.makedirs/remove → args[0]
            got = receiver_path(node)
            if got:
                targets.extend(got)
            elif node.args:
                targets.extend(resolve(node.args[0]))
            return

        if fname in TWO_ARG:
            # os.rename/replace、shutil.move/copy*：目标是第二个参数。
            # 排除 str.replace 等同名方法——仅模块调用或裸函数名
            if isinstance(fn, ast.Attribute) and not _module_alias(node, aliases):
                return
            if len(node.args) >= 2:
                targets.extend(resolve(node.args[1]))

    try:
        tree = ast.parse(code)
        consts = _string_consts(tree)
        for node in ast.walk(tree):
            collect(node)
    except SyntaxError:
        return []  # 语法错误由子进程报告

    # 仅保留工作目录外的绝对路径
    return [p.resolve() for p in targets
            if p.resolve() != workdir and not p.resolve().is_relative_to(workdir)]


def _interpreter_args() -> list[str]:
    """子进程解释器命令前缀。

    frozen（PyInstaller 打包版）：使用随包捆绑的 Python 运行时，
    -I 隔离模式 + -X utf8 保证输出按 utf-8 解码、跨机器确定性；
    避免使用 sys.executable（打包版下是应用本身，
    会拉起第二个 GUI 实例）。
    - Windows：MEIPASS/python.exe（ShadowTalk.spec 的 datas 收集）
    - Linux(.deb)：MEIPASS/runtime/python3（packaging/linux 组装）
    非 frozen（开发模式）：沿用当前解释器，行为零变化。
    """
    if getattr(sys, "frozen", False):
        exe = (Path(sys._MEIPASS) / "python.exe" if sys.platform == "win32"
               else Path(sys._MEIPASS) / "runtime" / "python3")
        return [str(exe), "-I", "-X", "utf8"]
    return [sys.executable]


def _prelude_path() -> Path:
    """沙箱前导脚本路径（frozen 由 spec datas 携带到 MEIPASS 根）"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "sandbox_prelude.py"
    return Path(__file__).with_name("sandbox_prelude.py")


def run_code(code: str, workdir: str, timeout: int = 30,
             allowed_paths: list | None = None) -> ExecResult:
    """子进程执行代码（经 sandbox_prelude 审计钩子），超时 kill。

    allowed_paths: 用户已审批放行的目录外绝对路径（运行时白名单）；
    其余目录外写入在子进程内被 PermissionError 拦截。
    """
    # 工作目录不存在时自动创建（含多级父目录）。换机/迁移后 work_dir
    # 常指向旧机器的绝对路径，subprocess 的 cwd 不存在会直接抛错，
    # AI 端表现为"文件操作功能暂时失灵"（用户报告：秘书/小女儿均中招）
    try:
        os.makedirs(workdir, exist_ok=True)
    except OSError as e:
        logger.error("工作目录创建失败: %s：%s", workdir, e)
        return ExecResult(
            stderr=f"工作目录无法创建: {workdir}（{e}）\n"
                   f"请让用户在好友设置中修正工作目录后重试。",
            exit_code=-1,
        )

    frozen = getattr(sys, "frozen", False)
    # 用户代码落临时文件，由前导脚本读取执行（避免 -c 引号转义与
    # 编码问题）；父进程写临时文件不受沙箱限制（不在子进程内）
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8", newline="\n") as f:
        f.write(code)
        code_file = f.name
    argv = [
        str(_prelude_path()),
        str(Path(workdir).resolve()),
        json.dumps([str(p) for p in (allowed_paths or [])], ensure_ascii=False),
        code_file,
    ]
    kwargs = dict(cwd=workdir, capture_output=True, text=True, timeout=timeout)
    if frozen:
        # 捆绑解释器以 -X utf8 启动：子进程输出按 utf-8 解码（跨机器确定）。
        # 仅 frozen 时附加——开发路径保持原样，不改动 GBK 环境的既有解码行为。
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"
        # Windows：python.exe 是控制台子系统程序，从 windowed exe 拉起时
        # 避免闪现黑框；Linux：新会话脱离当前终端与信号组，效果对等。
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
    try:
        proc = subprocess.run(
            [*_interpreter_args(), *argv],
            **kwargs,
        )
        result = ExecResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )
        logger.info("工具执行: 退出码=%s 输出=%s字符", proc.returncode,
                    len(proc.stdout or "") + len(proc.stderr or ""))
        return result
    except subprocess.TimeoutExpired as e:
        logger.warning("工具执行超时: 工作目录=%s", workdir)
        return ExecResult(
            stdout=e.stdout.decode() if isinstance(e.stdout, bytes) and e.stdout else "",
            stderr=e.stderr.decode() if isinstance(e.stderr, bytes) and e.stderr else "",
            exit_code=-9,
            timed_out=True,
        )
    finally:
        try:
            os.unlink(code_file)
        except OSError:
            pass


def run_with_approval(code: str, workdir: str,
                      approver, reason: str = "",
                      timeout: int = 30) -> ExecResult:
    """
    扫描→审批→执行。
    approver: Callable[[list[Path], str], bool] 返回 True 允许 / False 拒绝。
    审批通过的目录外路径作为运行时白名单传入子进程沙箱；
    timeout 透传给子进程执行（AIWorker 按设置传入，默认 30 秒）。
    """
    outside_paths = scan_write_paths(code, workdir)
    if outside_paths:
        allowed = approver(outside_paths, reason)
        if not allowed:
            return ExecResult(user_denied=True)
        return run_code(code, workdir, allowed_paths=outside_paths,
                        timeout=timeout)
    return run_code(code, workdir, timeout=timeout)
