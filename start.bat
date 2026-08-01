@echo off
cd /d "%~dp0"
echo Starting SAOM Dashboard...
echo Dashboard: http://localhost:5000
echo Press Ctrl+C to stop
echo.
python web_server.py