#!/usr/bin/env pwsh
# install_global.ps1 - make `ax` a global command (mirrors how CodexAuthManager installs `cx`).
#
# Writes an ax.cmd shim into %APPDATA%\npm (already on PATH for npm users; the same
# folder CodexAuthManager uses for `cx`) that forwards to ax.ps1 in this folder.
#
# Run once:  .\install_global.ps1     then open a new terminal and run:  ax

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

$shimDir = Join-Path $env:APPDATA 'npm'
if (-not (Test-Path $shimDir)) { New-Item -ItemType Directory -Force -Path $shimDir | Out-Null }

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshExe) { $pwshExe = (Get-Command powershell).Source }

$shim = Join-Path $shimDir 'ax.cmd'
$content = "@echo off`r`n`"$pwshExe`" -NoProfile -ExecutionPolicy Bypass -File `"$here\ax.ps1`" %*`r`n"
Set-Content -Path $shim -Value $content -NoNewline -Encoding ascii
Write-Host "[OK] Installed global command -> $shim" -ForegroundColor Green
Write-Host "     (forwards to $here\ax.ps1)" -ForegroundColor DarkGray

# Ensure the shim folder is on the user PATH.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$shimDir*") {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$shimDir", 'User')
  Write-Host "[OK] Added $shimDir to user PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "Open a NEW terminal, then try:" -ForegroundColor Cyan
Write-Host "  ax              # list accounts"
Write-Host "  ax 1            # switch to account 1"
Write-Host "  ax limits       # show quota"
Write-Host "  ax dispatch task.md"
