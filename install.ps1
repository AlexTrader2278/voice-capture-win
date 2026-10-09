# VoiceCapture для Windows — установщик. Админ-права НЕ нужны.
# Что делает: скачивает менеджер Python (uv) -> ставит Python 3.12 и пакеты в свою папку ->
# скачивает модель GigaAM (~400 МБ, один раз) -> проверяет её -> ставит автозапуск -> запускает.
# Параметры: -InstallDir <путь>  -NoAutostart  -NoLaunch  -SkipModel
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "VoiceCapture"),
    [switch]$NoAutostart,
    [switch]$NoLaunch,
    [switch]$SkipModel
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProgressPreference = "SilentlyContinue"   # без прогресс-бара: в 10 раз быстрее скачивание
$src = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($n, $t) { Write-Host "`n[$n/6] $t" -ForegroundColor Cyan }
function Fail($t) { Write-Host "`nОШИБКА: $t" -ForegroundColor Red; exit 1 }

Write-Host "=== VoiceCapture для Windows: установка ===" -ForegroundColor Green
Write-Host "Папка установки: $InstallDir"

# 0. проверки окружения
if (-not [Environment]::Is64BitOperatingSystem) { Fail "Нужна 64-битная Windows." }
if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { Fail "ARM-ноутбуки (Snapdragon) не поддерживаются: нет сборок пакетов. Нужен обычный Intel/AMD." }
if ([Environment]::OSVersion.Version.Major -lt 10) { Fail "Нужна Windows 10 или новее." }

# 1. останавливаем прежнюю копию (переустановка поверх)
Step 1 "Подготовка папки"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$InstallDir*" -or $_.CommandLine -like "*$InstallDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
foreach ($f in "voice_input.py","cleaner.py","requirements.txt","run-hidden.vbs","voice-input.bat","uninstall.ps1","uninstall.bat","README.md") {
    $p = Join-Path $src $f
    if (Test-Path $p) { Copy-Item $p (Join-Path $InstallDir $f) -Force }
}
# config.json пользователя не затираем при переустановке
$cfg = Join-Path $InstallDir "config.json"
if (-not (Test-Path $cfg)) { Copy-Item (Join-Path $src "config.json") $cfg }

# 2. uv (менеджер Python) — один exe, кладём в свою папку, PATH не трогаем
Step 2 "Скачиваю менеджер Python (uv)"
$uvDir = Join-Path $InstallDir "tools"
$uv = Join-Path $uvDir "uv.exe"
if (-not (Test-Path $uv)) {
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    $zip = Join-Path $env:TEMP "uv-win.zip"
    $url = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing } catch { Fail "Не скачался uv ($url). Проверь интернет/VPN/антивирус. $_" }
    Expand-Archive -Path $zip -DestinationPath $uvDir -Force
    Remove-Item $zip -Force
    # в архиве exe может лежать во вложенной папке
    if (-not (Test-Path $uv)) {
        $found = Get-ChildItem $uvDir -Recurse -Filter uv.exe | Select-Object -First 1
        if ($found) { Move-Item $found.FullName $uv -Force }
    }
    if (-not (Test-Path $uv)) { Fail "uv.exe не найден после распаковки." }
}

# 3. Python 3.12 + виртуальное окружение
Step 3 "Ставлю Python 3.12 и окружение (1-3 минуты)"
$env:UV_CACHE_DIR = Join-Path $InstallDir "tools\cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallDir "tools\python"
Push-Location $InstallDir
try {
    & $uv venv --python 3.12 --clear .venv
    if ($LASTEXITCODE -ne 0) { Fail "Не удалось создать окружение Python." }
    $py = Join-Path $InstallDir ".venv\Scripts\python.exe"

    # 4. пакеты
    Step 4 "Ставлю пакеты распознавания"
    & $uv pip install --python $py -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "Не удалось поставить пакеты." }
} finally { Pop-Location }

# 5. модель + самопроверка (скачивает ~400 МБ с HuggingFace в кэш пользователя)
Step 5 "Скачиваю и проверяю модель GigaAM v3 (~400 МБ, только в первый раз)"
if ($SkipModel) { Write-Host "пропущено (-SkipModel)" -ForegroundColor Yellow }
else {
    & $py (Join-Path $InstallDir "voice_input.py") --selftest
    if ($LASTEXITCODE -ne 0) { Fail "Модель не загрузилась/не прошла проверку. Проверь интернет (нужен huggingface.co) и свободное место (~2 ГБ)." }
}

# 6. автозапуск + старт
Step 6 "Автозапуск и старт"
$vbs = Join-Path $InstallDir "run-hidden.vbs"
if (-not $NoAutostart) {
    $lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "VoiceCapture.lnk"
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($lnk)
    $s.TargetPath = "wscript.exe"
    $s.Arguments = "`"$vbs`""
    $s.WorkingDirectory = $InstallDir
    $s.Save()
    Write-Host "Автозапуск включён: $lnk"
}
if (-not $NoLaunch) {
    Start-Process wscript.exe -ArgumentList "`"$vbs`"" -WorkingDirectory $InstallDir
    Write-Host "Запущено. Через 5-10 секунд прозвучит два коротких сигнала — программа готова."
}

Write-Host "`n=== ГОТОВО ===" -ForegroundColor Green
Write-Host @"
Как пользоваться:
  1. Поставь курсор в любое поле ввода (браузер, Word, мессенджер).
  2. ЗАЖМИ правый Ctrl, говори, ОТПУСТИ — текст появится там, где курсор.
  3. Выход из программы: Ctrl+Alt+Shift+G.
Если не пишет звук: Параметры Windows -> Конфиденциальность -> Микрофон -> разреши доступ классическим приложениям.
Папка программы: $InstallDir
"@
