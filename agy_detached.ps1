<#
agy_detached.ps1 — FLASH-FREE agy dispatch (no-admin runtime trigger).

ConPTY's OpenConsole.exe child window flashes on the interactive desktop. Running
agy in a Task Scheduler job with an S4U (non-interactive) principal gives it NO
desktop -> no flash. Registering an S4U task needs admin, so that is done ONCE via
agy_detached_setup (see header of that command). Thereafter THIS script only:
  1. writes the per-run request to .agy_detached_request.json
  2. triggers the pre-registered task 'RIMA_agy_detached' (running your OWN task = no admin)
  3. waits for it to finish
  4. prints the AGY_DONE_<account>.md the dispatcher wrote

NON-UnityMCP dispatch only (web research / docs). UnityMCP needs the interactive
session -> use agy_dispatch.cmd for those (accept the minor flash).

USAGE (Claude PowerShell tool, run_in_background recommended):
  & ".\agy_detached.ps1" `
      -TaskFile "tasks/foo.md" [-Account <prefix>] [-PrintTimeout 600]
#>
param(
    [Parameter(Mandatory = $true)][string]$TaskFile,
    [string]$Account,
    [int]$PrintTimeout = 600
)

$ErrorActionPreference = 'Stop'
$root     = $PSScriptRoot
$taskName = 'agy_detached'

# Bail early with a clear message if the one-time admin setup hasn't been run.
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Error "Task '$taskName' not registered. Run the one-time admin setup first (see agy_detached_setup command)."
    exit 3
}

# 1. Write the per-run request the runner will read.
$req = @{ task_file = $TaskFile; print_timeout = $PrintTimeout }
if ($Account) { $req.account = $Account }
$req | ConvertTo-Json | Set-Content -Path (Join-Path $root '.agy_detached_request.json') -Encoding UTF8

# Snapshot newest AGY_DONE mtime so we can tell the run actually wrote something fresh.
function Newest-Done { Get-ChildItem (Join-Path $root 'AGY_DONE_*.md') -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 }
$before = Newest-Done
$beforeStamp = if ($before) { $before.LastWriteTime } else { [datetime]::MinValue }

# 2. Trigger the pre-registered task (no admin needed for your own task).
Start-ScheduledTask -TaskName $taskName

# 3. Wait for completion.
$deadline = (Get-Date).AddSeconds($PrintTimeout + 90)
do {
    Start-Sleep -Seconds 3
    $state = (Get-ScheduledTask -TaskName $taskName).State
} while ($state -eq 'Running' -and (Get-Date) -lt $deadline)

# 4. Read the fresh result.
$after = Newest-Done
if ($after -and $after.LastWriteTime -gt $beforeStamp) {
    Write-Output "[agy_detached] OK — $($after.Name) (modified $($after.LastWriteTime)):"
    Get-Content $after.FullName -Raw
} else {
    Write-Error "[agy_detached] no fresh AGY_DONE produced (state=$state). ConPTY may not init in the S4U session — fall back to hidden-desktop approach."
    exit 1
}
