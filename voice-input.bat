@echo off
rem Запуск с окном и логом (для отладки). Аргументы: --diag, --list-devices, --selftest
cd /d "%~dp0"
".venv\Scripts\python.exe" "voice_input.py" %*
echo.
echo --- программа завершилась, окно можно закрыть ---
pause
