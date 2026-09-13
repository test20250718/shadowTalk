# shadowtalk/config/paths.py
"""数据根目录定位：
- Windows 打包版：exe 所在目录（便携，随 U 盘走）
- Linux 打包版（.deb 装在 /opt）：用户主目录 ~/.shadowtalk（/opt 普通用户不可写）
- 开发模式：当前工作目录
"""
import sys
from pathlib import Path


def get_base_dir() -> Path:
    frozen = getattr(sys, "frozen", False)
    if frozen and sys.platform != "win32":
        return Path.home() / ".shadowtalk"
    if frozen:
        return Path(sys.executable).parent
    return Path.cwd()


def resource_path(rel: str) -> Path:
    """静态资源（图标/logo 等）定位：
    - 打包版：PyInstaller datas 携带到 MEIPASS（见 ShadowTalk.spec）
    - 开发模式：仓库根（本文件位于 shadowtalk/config/，上溯两级），
      与运行时 cwd 无关
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / rel
    return Path(__file__).resolve().parents[2] / rel
