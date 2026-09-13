# ShadowTalk.spec — 便携打包。datas 不携带任何应用运行时数据
# （数据库、日志、头像、提示词日志均不收集，首启自动创建空库）。
# 例外 1：捆绑 Python 3.11 运行时（python.exe + 标准库 Lib + DLLs），
# 使 frozen 模式下 AI 工具子进程执行可用（见设计文档第 3 节）。
# 例外 2：sandbox_prelude.py（AI 工具子进程的写沙箱前导，
# python_executor._prelude_path 在 frozen 下从 MEIPASS 根读取）。
import os
import sys
from pathlib import Path


# 排除不需要的 DLL：
# - opengl32sw.dll: Mesa 软件 OpenGL，现代机器都有显卡不需要（-7.3 MB）
# - tcl86t.dll / tk86t.dll: tkinter 运行时，应用不使用（-1.5 MB）
# 全部小写，过滤时统一 lower() 比较
_QTDLL_SKIP = {
    "opengl32sw.dll",
    "tcl86t.dll", "tk86t.dll",
}
_QTMODULE_SKIP = {
    "qt6pdf.dll", "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6qmlmeta.dll", "qt6qmlworkerscript.dll",
    "qt6virtualkeyboard.dll",
    # qt6multimedia.dll 保留：TTS 播放器使用 QMediaPlayer/QAudioOutput
    "qt6designer.dll", "qt6designercomponents.dll",
    "qt6labs.dll", "qt6labsanimation.dll", "qt6labsfolderlistmodel.dll",
    "qt6labsqmlmodels.dll", "qt6labssettings.dll", "qt6labswavefrontmesh.dll",
    "qt3danimation.dll", "qt3dcore.dll", "qt3dextras.dll", "qt3dinput.dll",
    "qt3dlogic.dll", "qt3dquick.dll", "qt3dquickanimation.dll", "qt3dquickextras.dll",
    "qt3dquickinput.dll", "qt3dquickrender.dll", "qt3dquickscene2d.dll", "qt3drender.dll",
    "qt6charts.dll", "qt6datavisualization.dll", "qt6graphs.dll",
    "qt6httpserver.dll", "qt6location.dll", "qt6nfc.dll",
    "qt6positioning.dll", "qt6quick3d.dll",
    "qt6remoteobjects.dll", "qt6scxml.dll", "qt6sensors.dll",
    "qt6serialbus.dll", "qt6serialport.dll", "qt6statemachine.dll",
    "qt6texttospeech.dll", "qt6webchannel.dll",
    "qt6webenginecore.dll", "qt6webenginewidgets.dll",
    "qt6websockets.dll", "qt6webview.dll",
}
_QTPLUGIN_SKIP = {
    "qdirect2d.dll",
    "qtga.dll", "qwbmp.dll", "qtiff.dll",
}


def _collect_python_runtime() -> list:
    """从构建环境 sys.base_prefix 收集 Python 运行时文件。"""
    base = Path(sys.base_prefix)
    datas = []
    for name in ("python.exe",
                 f"python{sys.version_info.major}{sys.version_info.minor}.dll",
                 "python3.dll",
                 "vcruntime140.dll",
                 "vcruntime140_1.dll"):
        p = base / name
        if p.exists():
            datas.append((str(p), "."))
    _lib_skip = ("site-packages", "__pycache__", "test", "tests",
                 "idlelib", "tkinter", "turtle", "turtledemo", "tcl", "tk",
                 "distutils", "lib2to3", "ensurepip",
                 "unittest", "pydoc_data", "msilib", "setuptools")
    for sub in ("Lib", "DLLs"):
        src = base / sub
        if not src.is_dir():
            continue
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in _lib_skip]
            rel = Path(root).relative_to(src)
            dest = sub if rel == Path(".") else str(Path(sub) / rel)
            for f in files:
                datas.append((str(Path(root) / f), dest))
    return datas


_AI_EXCLUDES = [
    "numpy", "scipy", "PIL", "matplotlib", "pytest",
    "_pytest", "pluggy", "iniconfig",
    "PySide6.QtPdf", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtQmlModels",
    # PySide6.QtMultimedia 保留：TTS 播放器 QMediaPlayer/QAudioOutput（tts_player.py）
    "PySide6.QtVirtualKeyboard",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DQuick",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtHttpServer", "PySide6.QtLocation", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtDesigner",
    "setuptools",
]


a = Analysis(
    ["shadowtalk/main.py"],
    pathex=["."],
    binaries=[],
    datas=_collect_python_runtime() + [
        (os.path.join(SPECPATH, "shadowtalk", "core", "sandbox_prelude.py"), "."),
        (os.path.join(SPECPATH, "resources"), "resources"),
    ],
    hiddenimports=["openai"],
    hookspath=[],
    runtime_hooks=[],
    excludes=_AI_EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

# 过滤 binaries：排除不需要的 Qt 模块 DLL 和系统 DLL
def _filter_binaries(binaries):
    filtered = []
    for b in binaries:
        # b = (dest_name, src_path, typecode)
        dest = b[0]
        name = os.path.basename(dest).lower()
        if name in _QTDLL_SKIP:
            continue
        if name in _QTMODULE_SKIP:
            continue
        if name in _QTPLUGIN_SKIP:
            continue
        filtered.append(b)
    return filtered

a.binaries = _filter_binaries(a.binaries)

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
    console=False,
    disable_windowed_traceback=False,
    # exe 文件图标（多尺寸 ico，由 resources/shadowtalk_logo.png 生成）
    icon=os.path.join(SPECPATH, "resources", "shadowtalk.ico"),
)
