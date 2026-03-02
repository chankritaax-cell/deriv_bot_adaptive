@echo off
chcp 65001 >nul
:loop
echo 🔄 Starting Bot...
python bot.py

if %errorlevel% equ 42 (
    echo.
    echo 🛑 BOT HALTED PERMANENTLY: Stop-Loss Reached!
    echo 🛑 Close this window when ready.
    pause
    exit /b 42
)

echo ⚠️ Bot exited. Restarting in 5s...
timeout /t 5
goto loop
