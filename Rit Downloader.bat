@echo off
rem Starts Rit Downloader (runs in the background, opens an app window)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run - installing. This takes a few minutes...
  call "%~dp0Install.bat"
)
start "" ".venv\Scripts\pythonw.exe" "app\server.py"
