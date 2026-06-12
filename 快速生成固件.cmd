@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-firmware-fast.ps1"
if errorlevel 1 (
    echo.
    echo Firmware build failed. Please keep this window open and review the error above.
    pause
    exit /b 1
)
echo.
echo A/B firmware build completed.
pause
