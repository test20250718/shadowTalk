@echo off
REM ============================================================
REM  ShadowTalk build script - pack into single-file exe
REM  Usage: double-click, or run from terminal:  build_exe.bat
REM  Output: dist\ShadowTalk.exe (portable, no Python needed)
REM  Note: takes about 2-10 minutes. Bundles Python 3.11 runtime.
REM ============================================================
setlocal

cd /d "%~dp0"

echo.
echo [1/4] Checking dependencies...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo   ^> PyInstaller not found, installing...
    pip install pyinstaller
)
python -c "import PySide6, openai, edge_tts" >nul 2>&1
if errorlevel 1 (
    echo   ^> Missing dependencies, installing requirements.txt...
    pip install -r requirements.txt
)
echo   OK
python -c "import shadowtalk;print('   Version: v'+shadowtalk.__version__)"

echo.
echo [2/4] Running tests (abort build on failure)...
python -m pytest tests/ -q --ignore=tests/test_main_window.py
if errorlevel 1 (
    echo   [ABORT] Tests failed. Fix issues first.
    pause
    exit /b 1
)
echo   OK

echo.
echo [3/4] PyInstaller packing (2-10 minutes, please wait)...
python -m PyInstaller --noconfirm --clean ShadowTalk.spec
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
