@echo off
cd /d "%~dp0\.."
if exist "alarm-bot.exe" (
    alarm-bot.exe run
) else if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m alarm_bot.cli run
) else (
    python -m alarm_bot.cli run
)
