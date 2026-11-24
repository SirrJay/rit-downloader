@echo off
rem Installs / repairs Rit Downloader. Safe to run again at any time.
cd /d "%~dp0"
title Rit Downloader - Setup
where python >nul 2>nul || (
  echo Python is not installed. Installing it with winget...
  winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
  echo Please close this window and run Install.bat again.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating environment...
  python -m venv .venv || (echo Failed to create environment & pause & exit /b 1)
)
echo Installing / updating components...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]" yt-dlp-ejs flask waitress || (echo Install failed & pause & exit /b 1)
".venv\Scripts\python.exe" "app\setup_ffmpeg.py"
where node >nul 2>nul || (
  echo Installing Node.js, which YouTube needs for some videos...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
)
echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\make_shortcut.ps1"
echo.
echo Done! Start "Rit Downloader" from your desktop.
timeout /t 5 >nul
