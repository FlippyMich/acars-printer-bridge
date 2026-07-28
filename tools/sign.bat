@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

rem ---------------------------------------------------------------------------
rem Code-signs dist\APB.exe and dist\APBinstaller.exe.
rem
rem Needs signtool.exe from the Windows SDK ("Windows 10/11 SDK" -> Signing
rem Tools). Then pick one of the two methods below.
rem
rem   1) Certificate in the Windows certificate store (smartcard, USB token or
rem      an imported .pfx). This is the normal case since 2023, because CA rules
rem      require the private key to live on hardware or in a cloud HSM:
rem
rem          tools\sign.bat store "Thumbprint or subject name"
rem
rem   2) Azure Trusted Signing, which signs in the cloud - no hardware:
rem
rem          tools\sign.bat azure path\to\metadata.json
rem
rem      (install the dlib first:  dotnet tool install --global azuresigntool
rem       or use the Trusted Signing dlib documented by Microsoft)
rem
rem A self-signed certificate is NOT worth it: users have no way to trust it, so
rem SmartScreen warns exactly the same.
rem ---------------------------------------------------------------------------

set TS=http://timestamp.digicert.com
set METHOD=%~1
set CRED=%~2

if "%METHOD%"=="" (
    echo Usage:
    echo     tools\sign.bat store "certificate thumbprint or subject"
    echo     tools\sign.bat azure  path\to\trusted-signing-metadata.json
    echo.
    echo Read the comments at the top of this file for the details.
    pause
    exit /b 1
)
if "%CRED%"=="" (
    echo ERROR: second argument missing ^(certificate or metadata file^).
    pause
    exit /b 1
)

rem --- locate signtool -------------------------------------------------------
set SIGNTOOL=
where signtool >nul 2>nul && set SIGNTOOL=signtool
if "%SIGNTOOL%"=="" (
    for /f "delims=" %%i in ('dir /b /o-n "C:\Program Files (x86)\Windows Kits\10\bin\10.*" 2^>nul') do (
        if exist "C:\Program Files (x86)\Windows Kits\10\bin\%%i\x64\signtool.exe" (
            set SIGNTOOL="C:\Program Files (x86)\Windows Kits\10\bin\%%i\x64\signtool.exe"
            goto :found
        )
    )
)
:found
if "%SIGNTOOL%"=="" (
    echo ERROR: signtool.exe not found. Install the Windows SDK ^(Signing Tools^).
    pause
    exit /b 1
)
echo Using %SIGNTOOL%
echo.

for %%F in ("dist\APB.exe" "dist\APBinstaller.exe") do (
    if not exist %%F (
        echo ERROR: %%F is missing - build it first with tools\build_exe.py
        pause
        exit /b 1
    )
)

rem --- sign ------------------------------------------------------------------
if /i "%METHOD%"=="store" (
    for %%F in ("dist\APB.exe" "dist\APBinstaller.exe") do (
        echo Signing %%F ...
        %SIGNTOOL% sign /sha1 "%CRED%" /fd SHA256 /tr "%TS%" /td SHA256 /d "ACARS Printer Bridge" %%F
        if errorlevel 1 (
            echo   thumbprint lookup failed, retrying by subject name...
            %SIGNTOOL% sign /n "%CRED%" /fd SHA256 /tr "%TS%" /td SHA256 /d "ACARS Printer Bridge" %%F
            if errorlevel 1 (
                echo ERROR: signing failed for %%F
                pause
                exit /b 1
            )
        )
    )
) else if /i "%METHOD%"=="azure" (
    for %%F in ("dist\APB.exe" "dist\APBinstaller.exe") do (
        echo Signing %%F with Trusted Signing ...
        %SIGNTOOL% sign /v /debug /fd SHA256 /tr "%TS%" /td SHA256 ^
            /dlib "%CRED%" /dmdf "%CRED%" %%F
        if errorlevel 1 (
            echo ERROR: signing failed for %%F
            pause
            exit /b 1
        )
    )
) else (
    echo ERROR: unknown method "%METHOD%" ^(use store or azure^).
    pause
    exit /b 1
)

rem --- verify ----------------------------------------------------------------
echo.
echo Verifying signatures...
for %%F in ("dist\APB.exe" "dist\APBinstaller.exe") do (
    %SIGNTOOL% verify /pa /v %%F | findstr /i "Successfully verified Signing Certificate Chain Timestamp"
)

echo.
echo Signed. Now re-upload both files to the release:
echo     tools\publish.bat
echo.
pause
