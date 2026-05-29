#!/usr/bin/env pwsh
# ax_switch.ps1 — switch agy CLI active Google account by restoring its cached OAuth blob
#   into Windows Credential Manager (LegacyGeneric:target=gemini:antigravity).
#
# Usage:
#   .\ax_switch.ps1                       # list captured accounts + active
#   .\ax_switch.ps1 <email-prefix>        # switch (e.g. 'alice' or full email)
#   .\ax_switch.ps1 -List                 # explicit list
#   .\ax_switch.ps1 -Active               # print current active email only
#
# Blobs live in: agy_snapshots\cred_blob_<localpart>.bin

[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Account,
  [switch]$List,
  [switch]$Active,
  [string]$Capture
)

$ErrorActionPreference = 'Stop'
$snapDir = Join-Path $PSScriptRoot "agy_snapshots"
$target  = "LegacyGeneric:target=gemini:antigravity"

# --- Win32 CredRead / CredWrite / CredFree (single-class wrapper) ---
if (-not ('WinApi.AgyCredApi' -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace WinApi {
  public class AgyCredApi {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    public struct CREDENTIAL {
      public uint   Flags;
      public uint   Type;
      public IntPtr TargetName;
      public IntPtr Comment;
      public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
      public uint   CredentialBlobSize;
      public IntPtr CredentialBlob;
      public uint   Persist;
      public uint   AttributeCount;
      public IntPtr Attributes;
      public IntPtr TargetAlias;
      public IntPtr UserName;
    }
    [DllImport("advapi32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr CredentialPtr);
    [DllImport("advapi32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool CredWrite([In] ref CREDENTIAL Credential, [In] uint Flags);
    [DllImport("advapi32", SetLastError=true)]
    public static extern bool CredFree(IntPtr cred);
  }
}
"@
}
$api = [WinApi.AgyCredApi]

function Get-ActiveEmail {
  $logDir = "$env:USERPROFILE\.gemini\antigravity-cli\log"
  if (-not (Test-Path $logDir)) { return $null }
  $latest = Get-ChildItem $logDir -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { return $null }
  $m = Select-String -Path $latest.FullName -Pattern 'applyAuthResult: email=([^,]+),' -ErrorAction SilentlyContinue | Select-Object -Last 1
  if ($m) { return $m.Matches[0].Groups[1].Value }
  return $null
}

function Get-CapturedAccounts {
  if (-not (Test-Path $snapDir)) { return @() }
  Get-ChildItem $snapDir -Filter "cred_blob_*.bin" | ForEach-Object {
    $local = $_.BaseName -replace '^cred_blob_', ''
    [PSCustomObject]@{ Local = $local; Email = "$local@gmail.com"; Path = $_.FullName; Size = $_.Length }
  }
}

function Get-CurrentBlobSha {
  $credPtr = [IntPtr]::Zero
  $ok = $api::CredRead($target, 1, 0, [ref]$credPtr)
  if (-not $ok) { return $null }
  try {
    $blobSize = [System.Runtime.InteropServices.Marshal]::ReadInt32($credPtr, 32)
    $blobPtr  = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($credPtr, 40)
    if ($blobSize -le 0 -or $blobSize -gt 200000) { return $null }
    $bytes = New-Object byte[] $blobSize
    [System.Runtime.InteropServices.Marshal]::Copy($blobPtr, $bytes, 0, $blobSize)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').Substring(0, 16))
  } finally {
    [void]$api::CredFree($credPtr)
  }
}

function Show-List {
  $active = Get-ActiveEmail
  $currentSha = Get-CurrentBlobSha
  Write-Host ""
  Write-Host "agy account switcher  (target: $target)" -ForegroundColor Cyan
  Write-Host "Active (last login from log): " -NoNewline
  Write-Host "$active" -ForegroundColor Green
  Write-Host "Current Cred Manager blob SHA: $currentSha"
  Write-Host ""
  Write-Host "Captured accounts:" -ForegroundColor Cyan
  $sha = [System.Security.Cryptography.SHA256]::Create()
  Get-CapturedAccounts | ForEach-Object {
    $blobBytes = [System.IO.File]::ReadAllBytes($_.Path)
    $hsh = [BitConverter]::ToString($sha.ComputeHash($blobBytes)).Replace('-','').Substring(0, 16)
    $marker = if ($hsh -eq $currentSha) { "[*]" } else { "   " }
    Write-Host ("  {0} {1,-22} {2} bytes  blob={3}" -f $marker, $_.Email, $_.Size, $hsh)
  }
  Write-Host ""
}

function Invoke-Switch([string]$acct) {
  $accounts = Get-CapturedAccounts
  $match = $accounts | Where-Object { $_.Local -like "*$acct*" -or $_.Email -like "*$acct*" } | Select-Object -First 1
  if (-not $match) {
    Write-Host "No captured blob matching '$acct'. Available:" -ForegroundColor Red
    $accounts | ForEach-Object { Write-Host "  $($_.Local)" }
    exit 1
  }

  $bytes = [System.IO.File]::ReadAllBytes($match.Path)
  $blobSize = $bytes.Length

  # Marshal blob into unmanaged memory
  $blobPtr = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($blobSize)
  [System.Runtime.InteropServices.Marshal]::Copy($bytes, 0, $blobPtr, $blobSize)

  $targetPtr   = [System.Runtime.InteropServices.Marshal]::StringToHGlobalUni($target)
  $userNamePtr = [System.Runtime.InteropServices.Marshal]::StringToHGlobalUni("antigravity")

  $cred = New-Object WinApi.AgyCredApi+CREDENTIAL
  $cred.Flags              = 0
  $cred.Type               = 1     # CRED_TYPE_GENERIC
  $cred.TargetName         = $targetPtr
  $cred.Comment            = [IntPtr]::Zero
  $cred.CredentialBlobSize = [uint32]$blobSize
  $cred.CredentialBlob     = $blobPtr
  $cred.Persist            = 2     # CRED_PERSIST_LOCAL_MACHINE
  $cred.AttributeCount     = 0
  $cred.Attributes         = [IntPtr]::Zero
  $cred.TargetAlias        = [IntPtr]::Zero
  $cred.UserName           = $userNamePtr

  $ok = $api::CredWrite([ref]$cred, 0)
  $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()

  [System.Runtime.InteropServices.Marshal]::FreeHGlobal($blobPtr)
  [System.Runtime.InteropServices.Marshal]::FreeHGlobal($targetPtr)
  [System.Runtime.InteropServices.Marshal]::FreeHGlobal($userNamePtr)

  if ($ok) {
    Write-Host "[OK] Swapped Cred Manager blob -> $($match.Email) ($blobSize bytes)" -ForegroundColor Green
    Write-Host "     (next agy CLI invocation will use this account)" -ForegroundColor DarkGray
  } else {
    Write-Host "[FAIL] CredWrite returned false. Win32 error: $err" -ForegroundColor Red
    exit 2
  }
}

function Save-CurrentBlob([string]$name) {
  if (-not (Test-Path $snapDir)) { New-Item -ItemType Directory -Force -Path $snapDir | Out-Null }
  $credPtr = [IntPtr]::Zero
  if (-not $api::CredRead($target, 1, 0, [ref]$credPtr)) {
    Write-Host "[FAIL] No Antigravity credential found. Run 'agy login' first." -ForegroundColor Red
    exit 1
  }
  try {
    $blobSize = [System.Runtime.InteropServices.Marshal]::ReadInt32($credPtr, 32)
    $blobPtr  = [System.Runtime.InteropServices.Marshal]::ReadIntPtr($credPtr, 40)
    if ($blobSize -le 0 -or $blobSize -gt 200000) { Write-Host "[FAIL] Unexpected blob size: $blobSize" -ForegroundColor Red; exit 2 }
    $bytes = New-Object byte[] $blobSize
    [System.Runtime.InteropServices.Marshal]::Copy($blobPtr, $bytes, 0, $blobSize)
    $out = Join-Path $snapDir ("cred_blob_{0}.bin" -f $name)
    [System.IO.File]::WriteAllBytes($out, $bytes)
    Write-Host "[OK] Captured current account -> $out ($blobSize bytes)" -ForegroundColor Green
  } finally {
    [void]$api::CredFree($credPtr)
  }
}

# --- main ---
if ($Capture) {
  Save-CurrentBlob -name $Capture
  exit 0
}
if ($Active) {
  $e = Get-ActiveEmail
  if ($e) { Write-Output $e } else { Write-Output "(unknown)" }
  exit 0
}
if ($List -or [string]::IsNullOrWhiteSpace($Account)) {
  Show-List
  exit 0
}
Invoke-Switch -acct $Account
