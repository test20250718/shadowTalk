@echo off
REM ============================================================
REM  ShadowTalk export script - pack source code into a zip
REM  for copying to another PC to continue development.
REM
REM  Usage: double-click, or run from terminal:  export_code.bat
REM  Output: ShadowTalk-src-YYYYMMDD.zip in repo root
REM
REM  Included : source, tests, resources, tools, packaging,
REM             build scripts, .git (history, ~1.5MB), todo.txt
REM  Excluded : venv (recreate with pip install), build/dist
REM             (rebuildable), runtime/user data (data\, logs\,
REM             mail_attachments\, shadowtalk.db - privacy)
REM
REM  After copying to the new PC: unzip anywhere, then see
REM  START-HERE.txt (venv + pip install + tests + run).
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

REM -- dated zip name (locale-independent via PowerShell) --
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set STAGE=ShadowTalk-src
set ZIP=%STAGE%-%TODAY%.zip

echo.
echo [1/3] Copying source to staging dir...
if exist "%STAGE%" rd /s /q "%STAGE%"
REM robocopy: bare names in /XD match at ANY depth (would wrongly drop
REM shadowtalk\data\ source files!), so runtime dirs are given as absolute
REM paths to exclude only the repo-root ones; __pycache__ stays a bare name
REM on purpose (must match at every level). %STAGE% and *.zip keep re-runs
REM from nesting the export into itself.
robocopy . "%STAGE%" /E ^
    /XD "%CD%\venv" "%CD%\build" "%CD%\dist" "%CD%\data" "%CD%\logs" ^
        "%CD%\mail_attachments" "%CD%\%STAGE%" __pycache__ .pytest_cache ^
    /XF shadowtalk.db *.pyc *.zip >nul
if errorlevel 8 (
    echo   [ABORT] robocopy failed with errorlevel %errorlevel%.
    rd /s /q "%STAGE%" 2>nul
    pause
    exit /b 1
)
echo   OK

echo.
echo [2/3] Compressing to %ZIP% ...
if exist "%ZIP%" del "%ZIP%"
REM Must use Windows bsdtar, NOT Compress-Archive and NOT Git's tar:
REM  - Compress-Archive silently skips hidden items - git marks .git
REM    hidden on Windows, so the repo history would vanish from the zip
REM  - Git's GNU tar (first in PATH) cannot write zip format at all
"%SystemRoot%\System32\tar.exe" -a -cf "%ZIP%" "%STAGE%"
if errorlevel 1 (
    echo   [ABORT] tar failed.
    rd /s /q "%STAGE%" 2>nul
    pause
    exit /b 1
)
echo   OK

echo.
echo [3/3] Cleaning staging dir...
rd /s /q "%STAGE%"
echo   OK

echo.
echo Done: %~dp0%ZIP%
echo.
echo Next steps on the other PC:
echo   1. Copy %ZIP% and unzip it anywhere.
echo   2. Follow START-HERE.txt inside: create venv, pip install
echo      -r requirements.txt  (last copy failed on missing bs4
echo      because venv was not rebuilt - do NOT copy venv\ over)
echo   3. Run tests, then continue development. Git history is
echo      included (.git), so commits/diffs keep working.
pause
endlocal
