@echo off
REM ============================================================
REM  ShadowTalk dev_export.bat
REM  Extract a portable source copy for developing on another PC.
REM  Output: ..\ShadowTalk-src   (next to this project folder)
REM  Whitelist only: source / tests / resources / packaging / build files
REM ============================================================
setlocal
cd /d "%~dp0"
set "OUT=%~dp0..\ShadowTalk-src"

echo.
echo [1/3] Cleaning old export ...
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

echo [2/3] Copying source (whitelist, no local data / caches / docs) ...
robocopy shadowtalk  "%OUT%\shadowtalk"  /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP
robocopy tests       "%OUT%\tests"       /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP
robocopy resources   "%OUT%\resources"   /E /NFL /NDL /NJH /NJS /NP
robocopy packaging   "%OUT%\packaging"   /E /NFL /NDL /NJH /NJS /NP
copy /y build_exe.bat  "%OUT%\" >nul
copy /y build_deb.sh   "%OUT%\" >nul
copy /y ShadowTalk.spec "%OUT%\" >nul
copy /y requirements.txt "%OUT%\" >nul
copy /y md2pdf.py      "%OUT%\" >nul

echo [3/3] Writing quick-start note ...
> "%OUT%\START-HERE.txt" echo ShadowTalk - how to start developing on this PC
>> "%OUT%\START-HERE.txt" echo.
>> "%OUT%\START-HERE.txt" echo   python -m venv venv
>> "%OUT%\START-HERE.txt" echo   venv\Scripts\pip install -r requirements.txt
>> "%OUT%\START-HERE.txt" echo   venv\Scripts\python -m pytest tests -q --ignore=tests/test_main_window.py
>> "%OUT%\START-HERE.txt" echo   venv\Scripts\python shadowtalk\main.py
>> "%OUT%\START-HERE.txt" echo.
>> "%OUT%\START-HERE.txt" echo Windows exe build:  build_exe.bat
>> "%OUT%\START-HERE.txt" echo Linux deb build :  build_deb.sh ^(on Linux^)

echo.
echo Done. Copy this folder to the other PC:
echo   %OUT%
echo.
pause
endlocal
