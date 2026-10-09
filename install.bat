@echo off
chcp 65001 >nul
rem Двойной клик = установка. Админ-права не нужны.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
