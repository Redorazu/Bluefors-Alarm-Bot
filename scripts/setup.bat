@echo off
cd /d "%~dp0\.."
if exist "alarm-bot.exe" (
    alarm-bot.exe setup
) else if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m alarm_bot.cli setup
) else (
    python -m alarm_bot.cli setup
)
pause
