@echo off
chcp 65001 >nul
echo 🛑 Closing previous instances...
taskkill /FI "WINDOWTITLE eq Deriv Dashboard*" /F /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq Deriv Bot*" /F /T >nul 2>&1
timeout /t 1 /nobreak >nul

echo 🔥 Starting Deriv Bot ^& Dashboard...




start "Deriv Bot" bot_launcher.bat
start "Telegram Bridge" telegram_launcher.bat

echo ✅ Processes started. Close the windows to stop.
echo 📊 Dashboard available at http://localhost:5001
pause
