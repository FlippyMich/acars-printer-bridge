@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Environment not installed yet. Run setup.bat first.
    pause
    exit /b 1
)

if "%~1"=="" (
    ".venv\Scripts\python.exe" -m acars_bridge --help
    echo.
    echo Examples:
    echo   cli.bat scan
    echo   cli.bat test
    echo   cli.bat doctor
    echo   cli.bat run
    echo.
    pause
    exit /b 0
)

".venv\Scripts\python.exe" -m acars_bridge %*
if "%~1"=="run" exit /b 0
if "%~1"=="watch-sim" exit /b 0
echo.
pause
