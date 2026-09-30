@echo off
powershell.exe -NoProfile -File "%~dp0install.ps1" -Owner david %*
pause
