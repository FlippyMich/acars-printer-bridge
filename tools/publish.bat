@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

rem ---------------------------------------------------------------------------
rem Publishes the repository and a release with both executables.
rem Run it from a normal console window: the GitHub login step is interactive.
rem Re-run it for later releases - it skips whatever is already done.
rem ---------------------------------------------------------------------------

set REPO=acars-printer-bridge
set OWNER=FlippyMich
set VERSION=v1.1.0
set DESCRIPTION=Print Fenix A32X ACARS/TELEX messages from MSFS on a Bluetooth thermal printer

set GH=gh
where gh >nul 2>nul || set GH="C:\Program Files\GitHub CLI\gh.exe"

echo ============================================================
echo   Publishing %OWNER%/%REPO% %VERSION%
echo ============================================================
echo.

if not exist "dist\APB.exe" (
    echo ERROR: dist\APB.exe is missing. Build it first:
    echo     .venv\Scripts\python.exe tools\build_exe.py
    pause
    exit /b 1
)
if not exist "dist\APBinstaller.exe" (
    echo ERROR: dist\APBinstaller.exe is missing. Build it first:
    echo     .venv\Scripts\python.exe tools\build_exe.py
    pause
    exit /b 1
)

echo [1/4] GitHub login
%GH% auth status >nul 2>nul
if errorlevel 1 (
    echo       Not logged in - a browser window will open.
    echo       Choose: GitHub.com  /  HTTPS  /  authenticate with a browser.
    %GH% auth login
    if errorlevel 1 (
        echo ERROR: login failed or was cancelled.
        pause
        exit /b 1
    )
) else (
    echo       already logged in.
)

echo.
echo [2/4] Repository
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo       Creating %OWNER%/%REPO% as a public repository and pushing...
    %GH% repo create %REPO% --public --source . --remote origin --push --description "%DESCRIPTION%"
    if errorlevel 1 (
        echo ERROR: could not create the repository.
        pause
        exit /b 1
    )
) else (
    echo       Remote already configured - pushing the current branch...
    git push -u origin HEAD
)

echo.
echo [3/4] Release %VERSION% with APB.exe and APBinstaller.exe
%GH% release view %VERSION% >nul 2>nul
if errorlevel 1 (
    %GH% release create %VERSION% "dist\APB.exe" "dist\APBinstaller.exe" ^
        --title "ACARS Printer Bridge %VERSION%" ^
        --notes "Download **APBinstaller.exe** and run it - it walks you through finding your Bluetooth thermal printer, installs the app, creates the Windows printer the Fenix EFB can see, and starts everything with Windows.\n\nAPB.exe is the app itself; the installer downloads it automatically, so you only need it if you prefer a manual install."
    if errorlevel 1 (
        echo ERROR: could not create the release.
        pause
        exit /b 1
    )
) else (
    echo       Release exists - uploading/overwriting the executables...
    %GH% release upload %VERSION% "dist\APB.exe" "dist\APBinstaller.exe" --clobber
)

echo.
echo [4/4] Done
echo.
echo   Repository : https://github.com/%OWNER%/%REPO%
echo   Installer  : https://github.com/%OWNER%/%REPO%/releases/latest/download/APBinstaller.exe
echo.
echo That download link is exactly what the installer uses to fetch APB.exe,
echo so from now on users only need APBinstaller.exe.
echo.
pause
