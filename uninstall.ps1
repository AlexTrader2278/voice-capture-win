# Удаление VoiceCapture. Модель в кэше HuggingFace (~400 МБ) оставляем, если не указан -WithModel.
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "VoiceCapture"),
    [switch]$WithModel
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$InstallDir*" -or $_.CommandLine -like "*$InstallDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "VoiceCapture.lnk"
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Автозапуск убран." }
if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Host "Папка удалена: $InstallDir" }
if ($WithModel) {
    $m = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
    Get-ChildItem $m -Directory -Filter "models--*gigaam*" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    Write-Host "Модель из кэша удалена."
}
Write-Host "Готово."
