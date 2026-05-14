@echo off
setlocal

echo.
echo =====================================
echo Pill Box PWA Notification Test
echo =====================================
echo.
echo This starts Flask with Python 3.11 and opens an ngrok HTTPS tunnel.
echo Use the HTTPS ngrok URL on your phone.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_with_ngrok.ps1"

echo.
pause
