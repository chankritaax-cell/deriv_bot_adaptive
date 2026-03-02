@echo off
chcp 65001 >nul
:loop
echo 🔄 Starting Telegram Bridge...
python -m modules.telegram_bridge
if %ERRORLEVEL% EQU 100 (
    echo ℹ️ Telegram token not found. Bridge disabled.
    timeout /t 3
    exit
)
echo ⚠️ Bridge exited. Restarting in 5s...
timeout /t 5
goto loop
