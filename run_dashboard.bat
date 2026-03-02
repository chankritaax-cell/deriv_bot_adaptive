@echo off
chcp 65001 >nul
echo 🛑 Closing previous instances...
taskkill /FI "WINDOWTITLE eq Deriv Dashboard*" /F /T >nul 2>&1
timeout /t 1 /nobreak >nul

echo 🔥 Starting  Dashboard...

:: Start Dashboard in a new window
:: Start Dashboard in a new window
echo 🚀 Launching Dashboard Server...
start "Deriv Dashboard" cmd /k ".venv\Scripts\python.exe dashboard_server.py && pause"

timeout /t 3 /nobreak >nul
start http://localhost:5001
