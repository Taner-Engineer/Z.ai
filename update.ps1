# Обновляет локальную копию из GitHub и переустанавливает скиллы и память.
# Запуск из корня репозитория: .\update.ps1
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoDir

Write-Host "[*] git pull..."
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "git pull завершился с ошибкой" }

& (Join-Path $RepoDir "install.ps1")
