"""
ShadowTalk 源码打包工具
=======================
把项目源码（不含数据/日志/构建产物/虚拟环境）打包成 zip，方便拷贝到另一台电脑继续开发。

用法：
    python tools/pack_source.py              # 输出到 dist/ShadowTalk_src_<版本>.zip
    python tools/pack_source.py D:/backup    # 输出到指定目录
"""
import os
import sys
import zipfile
from pathlib import Path

# ── 排除规则（目录名 / 文件后缀 / 精确文件名） ──
EXCLUDE_DIRS = {
    ".git", "__pycache__", "venv", ".venv", "build", "dist",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
    "node_modules", ".claude",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".mp3"}
EXCLUDE_FILES = {
    "todo.txt", "shadowtalk.db", "shadowtalk.db-wal", "shadowtalk.db-shm",
}

# ── 只打包这些目录下的内容（白名单） ──
INCLUDE_DIRS = ["shadowtalk", "tests", "tools"]
INCLUDE_ROOT_FILES = [
    "requirements.txt", "README.md", "CLAUDE.md",
    "build_exe.bat", "build_deb.sh", "ShadowTalk.spec",
    "ShadowTalk_Recover.spec", ".gitignore",
]


def pack(output_dir: Path) -> Path:
    """打包源码到 zip，返回 zip 路径。"""
    # 版本号
    version = "unknown"
    init_file = Path("shadowtalk/__init__.py")
    if init_file.exists():
        for line in init_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("__version__"):
                version = line.split("=")[1].strip().strip("'\"")
                break

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"ShadowTalk_src_{version}.zip"

    repo_root = Path.cwd()
    added = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. 白名单目录
        for include_dir in INCLUDE_DIRS:
            d = repo_root / include_dir
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if not f.is_file():
                    continue
                # 跳过排除的目录
                if any(part in EXCLUDE_DIRS for part in f.relative_to(repo_root).parts):
                    continue
                # 跳过后缀
                if f.suffix.lower() in EXCLUDE_SUFFIXES:
                    continue
                # 跳过精确文件名
                if f.name in EXCLUDE_FILES:
                    continue
                arcname = f.relative_to(repo_root).as_posix()
                zf.write(f, arcname)
                added += 1

        # 2. 根目录文件
        for fname in INCLUDE_ROOT_FILES:
            f = repo_root / fname
            if f.is_file():
                zf.write(f, fname)
                added += 1

    return zip_path, added, version


def main():
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist")
    zip_path, count, version = pack(output_dir)
    size_kb = zip_path.stat().st_size // 1024
    print(f"[OK] Source packed")
    print(f"  Version : v{version}")
    print(f"  Files   : {count}")
    print(f"  Size    : {size_kb} KB")
    print(f"  Path    : {zip_path}")


if __name__ == "__main__":
    main()
