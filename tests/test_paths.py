"""get_base_dir / resource_path 测试：frozen（打包态）与开发态"""
import sys
from pathlib import Path
from shadowtalk.config.paths import get_base_dir, resource_path


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


def test_frozen_posix_uses_home_shadowtalk(monkeypatch):
    """Linux 打包版（.deb 装在 /opt）：数据根目录必须落用户主目录
    ~/.shadowtalk —— /opt 普通用户不可写，落在安装目录会启动即崩"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("shadowtalk.config.paths.Path.home",
                        lambda: Path("/home/gene"))
    assert get_base_dir() == Path("/home/gene/.shadowtalk")


def test_frozen_windows_platform_unchanged(monkeypatch):
    """回归：Windows 打包版仍落 exe 目录（便携设计不变）"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable",
                        "D:/ShadowTalk/ShadowTalk.exe")
    assert get_base_dir() == Path("D:/ShadowTalk")


# ── resource_path：静态资源（logo/图标）定位 ──

def test_resource_path_dev_is_repo_root(monkeypatch):
    """开发模式：资源相对仓库根解析，与运行时 cwd 无关"""
    import os
    monkeypatch.delattr(sys, "frozen", raising=False)
    repo_root = Path(__file__).resolve().parents[1]
    p = resource_path(os.path.join("resources", "shadowtalk_logo.png"))
    assert p == repo_root / "resources" / "shadowtalk_logo.png"
    assert p.exists()  # 仓库自带该资源


def test_resource_path_frozen_uses_meipass(monkeypatch):
    """打包模式：资源从 PyInstaller 的 MEIPASS 提取目录读取"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "D:/extract/_MEI123", raising=False)
    assert resource_path("resources/logo.png") == \
        Path("D:/extract/_MEI123/resources/logo.png")
