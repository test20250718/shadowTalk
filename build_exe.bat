@echo off
REM ============================================================
REM  ShadowTalk build script - pack into single-file exe
REM  Usage: double-click, or run from terminal:  build_exe.bat
REM  Output: dist\ShadowTalk.exe (portable, no Python needed)
REM  Note: takes about 2-10 minutes. Bundles the venv's Python
REM  runtime (used by the AI tool sandbox subprocess).
REM
REM  All steps run in .\venv (auto-created on first run). Never
REM  install into the global interpreter: MS Store Python's user
REM  site-packages path is so deep that PySide6's internal paths
REM  exceed Windows MAX_PATH (260) and pip aborts with OSError.
REM ============================================================
setlocal

cd /d "%~dp0"

set "PY=%~dp0venv\Scripts\python.exe"

echo.
echo [1/4] Checking dependencies...
if not exist "%PY%" (
    echo   ^> venv not found, creating...
    python -m venv venv
    if errorlevel 1 (
        echo   [ABORT] Failed to create venv. Install Python 3.11+ and retry.
        pause
        exit /b 1
    )
)
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo   ^> PyInstaller not found, installing...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo   [ABORT] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)
"%PY%" -c "import PySide6, openai, edge_tts" >nul 2>&1
if errorlevel 1 (
    echo   ^> Missing dependencies, installing requirements.txt...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo   [ABORT] pip install failed. If PySide6 dies with a
        echo   long-path OSError, enable Windows Long Path support:
        echo   https://pip.pypa.io/warnings/enable-long-paths
        pause
        exit /b 1
    )
)
echo   OK
"%PY%" -c "import shadowtalk;print('   Version: v'+shadowtalk.__version__)"

echo.
echo [2/4] Running tests (abort build on failure)...
"%PY%" -m pytest tests/ -q --ignore=tests/test_main_window.py
if errorlevel 1 (
    echo   [ABORT] Tests failed. Fix issues first.
    pause
    exit /b 1
)
echo   OK

echo.
echo [3/4] PyInstaller packing (2-10 minutes, please wait)...
"%PY%" -m PyInstaller --noconfirm --clean ShadowTalk.spec
if errorlevel 1 (
    echo   [ABORT] Build failed. See messages above.
    pause
    exit /b 1
)
echo   OK

echo.
echo [4/4] Done.
echo   Output: %~dp0dist\ShadowTalk.exe
echo   Portable single file. On first run it creates data\ next to
echo   the exe (database, logs, avatars, tts cache).
pause
endlocal
