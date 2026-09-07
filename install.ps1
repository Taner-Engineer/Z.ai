# Разворачивает скиллы и глобальную память ZCode на этой машине (PowerShell).
# Запуск из корня репозитория: .\install.ps1
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ZcodeSkills = Join-Path $env:USERPROFILE ".zcode\skills"
$AgentsSkills = Join-Path $env:USERPROFILE ".agents\skills"
$AgentsMd = Join-Path $env:USERPROFILE ".zcode\AGENTS.md"

New-Item -ItemType Directory -Force -Path $ZcodeSkills, $AgentsSkills | Out-Null

# --- Скиллы ---
$installed = 0
Get-ChildItem -Directory (Join-Path $RepoDir "skills") | ForEach-Object {
    $dest1 = Join-Path $ZcodeSkills $_.Name
    $dest2 = Join-Path $AgentsSkills $_.Name
    if (Test-Path $dest1) { Remove-Item -Recurse -Force $dest1 }
    if (Test-Path $dest2) { Remove-Item -Recurse -Force $dest2 }
    Copy-Item -Recurse $_.FullName $dest1
    Copy-Item -Recurse $_.FullName $dest2
    Write-Host "[+] скилл: $($_.Name)"
    $installed++
}

# --- Глобальная память AGENTS.md ---
if ((Test-Path $AgentsMd) -and
    ((Get-FileHash (Join-Path $RepoDir "AGENTS.md")).Hash -ne (Get-FileHash $AgentsMd).Hash)) {
    $backup = "$AgentsMd.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $AgentsMd $backup
    Write-Host "[!] Существующий AGENTS.md отличался — сохранена копия: $backup"
}
Copy-Item (Join-Path $RepoDir "AGENTS.md") $AgentsMd -Force
Write-Host "[+] глобальная память: $AgentsMd"

Write-Host ""
Write-Host "Готово: $installed скилл(ов) + AGENTS.md установлены."
Write-Host "Если ZCode запущен — перезапустите его, чтобы новые скиллы подхватились."
