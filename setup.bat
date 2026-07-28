@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   ACARS Printer Bridge - first time setup
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python is not on your PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Setup complete.
echo.
choice /C YN /M "Start the app now"
if errorlevel 2 goto :end
start "" ".venv\Scripts\pythonw.exe" -m acars_bridge ui

:end
echo.
echo Next time just double click start.bat
echo.
pause
