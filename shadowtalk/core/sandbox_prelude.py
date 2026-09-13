# shadowtalk/core/sandbox_prelude.py
"""
子进程写沙箱前导：在执行 AI 生成代码前安装 sys.addaudithook，
拦截所有经 Python 的文件写/删/改名/复制操作——目标落在工作目录外
且不在用户审批白名单里 → PermissionError，文件不落盘。

用法: python sandbox_prelude.py <workdir> <approved-paths-json> <user-code.py>

与 python_executor.scan_write_paths 的分工：
- 静态扫描是 UX 层：能看穿的写法提前弹审批卡，用户点允许才执行；
- 本模块是运行时硬保证：AST 永远追不完动态构造的路径（变量拼接、
  函数传参、''.join(...) 等），审计钩子在真正打开文件那一刻校验，
  未授权的目录外写入不可能发生。

已知局限（权衡后接受）：
- sqlite3 等 C 扩展自带的文件 IO 不经 Python 审计事件；
- subprocess / os.system 的 shell 重定向不拦截（保留 AI 正常使用
  子进程的能力，如调用 pandoc 等外部工具）。
"""
import json
import os
import sys

workdir = os.path.realpath(sys.argv[1])
approved = [os.path.realpath(p) for p in json.loads(sys.argv[2])]
code_path = sys.argv[3]

# 先读用户代码再装钩子（读取不受限，且避免读文件本身触发校验）
with open(code_path, "r", encoding="utf-8") as f:
    code = f.read()

_WRITE_FLAGS = (os.O_WRONLY | os.O_RDWR | os.O_APPEND
                | os.O_CREAT | os.O_TRUNC)

# 目标 = 第二参数（源只读不动）的调用
_DST_ONLY = {"shutil.copyfile", "shutil.copy", "shutil.copy2",
             "shutil.copytree", "os.symlink", "os.link"}
# 源和目标都动（目标新建、源被删/改名）的调用
_BOTH = {"os.rename", "os.replace", "shutil.move"}


def _allowed(path) -> bool:
    try:
        s = os.fspath(path)
        if not isinstance(s, str):
            return False
        if not os.path.isabs(s):
            s = os.path.join(os.getcwd(), s)
        r = os.path.realpath(s)
    except Exception:
        return False  # 解析失败 → fail-closed
    if r == workdir or r.startswith(workdir + os.sep):
        return True
    return any(r == a or r.startswith(a + os.sep) for a in approved)


def _deny(path) -> None:
    raise PermissionError(
        f"ShadowTalk 沙箱：禁止写入工作目录外的路径 {path!s}（未获用户授权）。"
        "请改用工作目录内的相对路径；确需写目录外时，请在回复中向用户"
        "说明目标绝对路径以获取授权。")


def _audit(event, args):
    try:
        if event == "open":
            path, mode, flags = args
            if isinstance(mode, str):
                write = any(c in mode for c in "wax+")
            else:
                write = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
            if write and not _allowed(path):
                _deny(path)
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.makedirs",
                       "os.truncate", "shutil.rmtree"):
            if args and not _allowed(args[0]):
                _deny(args[0])
        elif event in _BOTH:
            for p in args[:2]:
                if not _allowed(p):
                    _deny(p)
        elif event in _DST_ONLY:
            if len(args) >= 2 and not _allowed(args[1]):
                _deny(args[1])
    except PermissionError:
        raise  # 拦截信号，向上传播阻断本次写操作
    except Exception:
        pass  # 钩子自身异常不得误伤非写入操作


sys.addaudithook(_audit)
sys.argv = [code_path]
exec(compile(code, code_path, "exec"), {"__name__": "__main__",
                                        "__file__": code_path})
