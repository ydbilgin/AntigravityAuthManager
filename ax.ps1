#!/usr/bin/env pwsh
# ax.ps1 - Antigravity multi-account command (companion to `cx` for Codex).
#
# The real Antigravity CLI is `agy`; `ax` is OUR layer on top: switch between
# captured Google accounts, dispatch tasks, and view quota. One Google login is
# active at a time (shared by the agy CLI and the Antigravity IDE), so we SWITCH.
#
# Usage:
#   ax                      list captured accounts (numbered) + active
#   ax <N>                  switch to account #N   (e.g. ax 1, ax 2)
#   ax <name>               switch by name/prefix  (e.g. ax alice)
#   ax capture <name>       save the currently logged-in account as <name>
#   ax login                run `agy login` (browser) to add/refresh an account
#   ax dispatch <file> ...  run a task non-interactively (writes AGY_DONE_<acct>.md)
#   ax limits [--all]       show quota (local IDE; falls back to all accounts if IDE closed)
#   ax help

param(
  [Parameter(Position = 0)][string]$Command,
  [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$root    = $PSScriptRoot
$snapDir = Join-Path $root 'agy_snapshots'
$switch  = Join-Path $root 'ax_switch.ps1'

function Get-AccountNames {
  if (-not (Test-Path $snapDir)) { return @() }
  @(Get-ChildItem $snapDir -Filter 'cred_blob_*.bin' -ErrorAction SilentlyContinue |
    Sort-Object Name | ForEach-Object { $_.BaseName -replace '^cred_blob_', '' })
}

function Show-List {
  $names = Get-AccountNames
  Write-Host ""
  Write-Host "ax - Antigravity accounts" -ForegroundColor Cyan
  if (-not $names -or $names.Count -eq 0) {
    Write-Host "  (none captured)  ->  ax login   then   ax capture <name>"
    Write-Host ""
    return
  }
  for ($i = 0; $i -lt $names.Count; $i++) {
    Write-Host ("  {0}) {1}" -f ($i + 1), $names[$i])
  }
  $active = (& $switch -Active) 2>$null
  Write-Host ("active: {0}" -f $active) -ForegroundColor Green
  Write-Host "switch:  ax <number>   (e.g. ax 1)"
  Write-Host ""
}

function Show-Help {
  Get-Content $PSCommandPath | Where-Object { $_ -match '^#' } |
    ForEach-Object { $_ -replace '^#\s?', '' } | Select-Object -First 17
}

switch -Regex ($Command) {
  '^(|list|ls|accounts)$' { Show-List; break }
  '^(help|-h|--help)$'    { Show-Help; break }
  '^capture$' {
    if (-not $Rest -or -not $Rest[0]) { throw "usage: ax capture <name>" }
    & $switch -Capture $Rest[0]; break
  }
  '^login$'    { & agy login @Rest; break }
  '^dispatch$' { & (Join-Path $root 'ax_dispatch.cmd') @Rest; exit $LASTEXITCODE }
  '^limits$'   { & python (Join-Path $root 'ax_limits.py') @Rest; exit $LASTEXITCODE }
  default {
    $names = Get-AccountNames
    if ($Command -match '^\d+$') {
      $idx = [int]$Command
      if ($idx -lt 1 -or $idx -gt $names.Count) {
        throw "No account #$idx. Run 'ax' to list ($($names.Count) captured)."
      }
      & $switch $names[$idx - 1]
    } else {
      & $switch $Command
    }
  }
}
