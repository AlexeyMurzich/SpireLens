@echo off
cd /d "%~dp0"
python desktop.py
if errorlevel 1 (
  echo Application failed. Python 3.10 or newer is required.
  pause
)
