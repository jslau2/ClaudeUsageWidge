@echo off
REM Creates a Startup-folder launcher so the Claude Quota widget runs at login.
REM Double-click this file (or run it) to install. Delete the created file to undo.
REM
REM The Claude CLI working directory is resolved without hardcoding, in order:
REM   1. First argument passed to this script   (install_autostart.bat "D:\path\to\workspace")
REM   2. The CLAUDE_WORKSPACE environment variable
REM   3. This script's own folder (%~dp0) as a fallback
setlocal
set "WIDGET=%~dp0claude_usage_widget.pyw"

REM Resolve the Claude CLI working directory.
set "CLAUDE_DIR=%~1"
if not defined CLAUDE_DIR set "CLAUDE_DIR=%CLAUDE_WORKSPACE%"
if not defined CLAUDE_DIR set "CLAUDE_DIR=%~dp0"
REM Strip any trailing backslash for clean display.
if "%CLAUDE_DIR:~-1%"=="\" set "CLAUDE_DIR=%CLAUDE_DIR:~0,-1%"

if not exist "%WIDGET%" (
    echo ERROR: widget not found:
    echo   %WIDGET%
    pause
    exit /b 1
)
if not exist "%CLAUDE_DIR%\" (
    echo ERROR: Claude working directory not found:
    echo   %CLAUDE_DIR%
    echo Pass it explicitly, e.g.:  install_autostart.bat "D:\path\to\workspace"
    echo or set CLAUDE_WORKSPACE first.
    pause
    exit /b 1
)

set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClaudeUsageWidget.bat"

> "%TARGET%" echo @echo off
>> "%TARGET%" echo start "Claude" cmd /k "cd /d %CLAUDE_DIR% && claude"
>> "%TARGET%" echo timeout /t 5 /nobreak ^>nul
>> "%TARGET%" echo start "" pythonw "%WIDGET%"

echo Auto-start installed:
echo   %TARGET%
echo   -^> claude in "%CLAUDE_DIR%"
echo   -^> wait 3s (let Claude refresh the token)
echo   -^> pythonw "%WIDGET%"
echo.
echo To disable later, delete:
echo   %TARGET%
echo.
pause
