# Установка одной строкой: скачивает архив репозитория, распаковывает во временную папку и запускает install.ps1
# irm https://raw.githubusercontent.com/AlexTrader2278/voice-capture-win/main/bootstrap.ps1 | iex
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = "AlexTrader2278/voice-capture-win"
$tmp = Join-Path $env:TEMP "vc-win-setup"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
Expand-Archive $zip -DestinationPath $tmp -Force
$dir = Get-ChildItem $tmp -Directory | Select-Object -First 1
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir.FullName "install.ps1")
