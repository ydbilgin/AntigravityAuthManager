# agy_snapshots — your captured Antigravity account credential blobs

This folder holds one `cred_blob_<name>.bin` per Antigravity (Google) account you
want `agy_dispatch.py` to swap between. **It ships empty** — you capture your own.

- **Single account?** You don't need this folder at all. Just run
  `agy_dispatch.py --no-swap` (it uses whatever account is active in `agy`).
- **Multiple accounts?** Capture one blob per account (below). The dispatcher then
  swaps between them automatically via `agychange.ps1`.

> ⚠️ **These `.bin` files are live OAuth tokens.** Never share, commit, or upload
> them. Each person captures their own.

## How to capture an account's blob

1. Log in the account you want to capture:
   ```powershell
   agy login        # complete Google sign-in for THIS account
   ```
2. Save its current Credential Manager blob into this folder (run from here).
   Replace `<name>` with a short label, e.g. the email local part:
   ```powershell
   $target = "LegacyGeneric:target=gemini:antigravity"
   $name   = "<name>"
   Add-Type -TypeDefinition @"
   using System; using System.Runtime.InteropServices;
   public class Cap {
     [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct CRED {
       public uint Flags; public uint Type; public IntPtr TargetName; public IntPtr Comment;
       public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
       public uint BlobSize; public IntPtr Blob; public uint Persist; public uint AttrCount;
       public IntPtr Attrs; public IntPtr TargetAlias; public IntPtr UserName; }
     [DllImport("advapi32", CharSet=CharSet.Unicode, SetLastError=true)]
     public static extern bool CredRead(string t, int ty, int f, out IntPtr c);
     [DllImport("advapi32")] public static extern bool CredFree(IntPtr c);
   }
   "@
   $p = [IntPtr]::Zero
   if (-not [Cap]::CredRead($target, 1, 0, [ref]$p)) { throw "No agy credential found - run 'agy login' first." }
   try {
     $size  = [Runtime.InteropServices.Marshal]::ReadInt32($p, 32)
     $blob  = [Runtime.InteropServices.Marshal]::ReadIntPtr($p, 40)
     $bytes = New-Object byte[] $size
     [Runtime.InteropServices.Marshal]::Copy($blob, $bytes, 0, $size)
     [IO.File]::WriteAllBytes("$PSScriptRoot\cred_blob_$name.bin", $bytes)
     Write-Host "Saved cred_blob_$name.bin ($size bytes)"
   } finally { [void][Cap]::CredFree($p) }
   ```
3. Repeat steps 1-2 for each additional account.

## Verify / switch manually
```powershell
..\agychange.ps1            # list captured accounts + which is active
..\agychange.ps1 <name>     # switch the active agy account to that blob
```
`agy_dispatch.py` calls `agychange.ps1` for you on each dispatch (unless `--no-swap`).
