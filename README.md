# AntigravityAuthManager

A single global command — **`ax`** — for running Google's **Antigravity** across
multiple Google accounts on Windows: switch the active account instantly, dispatch
tasks non‑interactively, and view quota.

**Antigravity has two surfaces** — a CLI (`agy`) and an IDE — and **both share one
Google login** (stored once in Windows Credential Manager). `ax` is **not** that
CLI; it is a thin layer on top (the same way **`cx`** sits on top of `codex` in the
companion project **[CodexAuthManager](https://github.com/ydbilgin/CodexAuthManager)**).

| | Real CLI you connect with | This project's command |
|---|---|---|
| Codex | `codex` | `cx`  (CodexAuthManager) |
| Antigravity | `agy` | **`ax`**  (this repo) |

Because Antigravity keeps only one login active at a time, multiple accounts are
used by **switching** between captured logins — that's what `ax` makes effortless.

## Install

```powershell
.\install_global.ps1      # writes an `ax` command shim to %APPDATA%\npm (on PATH)
```
Open a new terminal, then `ax` is available everywhere. Requirements: Windows,
PowerShell, **Python 3.10+**, the **`agy`** CLI on PATH, and `pip install pywinpty`
(used by `ax dispatch`).

## Set up accounts

```powershell
agy login          # browser sign-in for an account
ax capture work    # save the now-active login as "work"
agy login          # sign in the next account
ax capture personal
```
Captured logins are stored as credential blobs in `agy_snapshots/` (yours only —
nothing is bundled; never share them).

## Use

```powershell
ax                      # list captured accounts (numbered) + the active one
ax 1                    # switch to account #1   (ax 2, ax 3, ...)
ax work                 # switch by name/prefix
ax capture <name>       # save the currently logged-in account
ax login                # agy login (add/refresh an account)
ax limits [--all]       # show remaining quota
ax dispatch task.md --print-timeout 600 [--account <prefix>] [--no-swap]
```

- `ax dispatch` runs a prompt/task through `agy` non‑interactively and writes the
  full response to `AGY_DONE_<account>.md`. It auto‑selects an account (priority +
  fall‑through on failure) unless you pass `--account` / `--no-swap`.
- `ax limits` reads the running IDE account's quota by default, or every account
  with `--all` (needs `npm i -g antigravity-usage`).

## How accounts work

Antigravity stores its Google login as one Windows Credential Manager entry
(`gemini:antigravity`). `ax <n>` restores the chosen account's saved blob into that
slot, so the next `agy` **and** the IDE use that account. `ax capture` does the
reverse (reads the current blob and saves it).

## Under the hood

`ax` is a PowerShell front‑end that calls:

```text
ax.ps1                   the `ax` command (switch / list / route subcommands)
ax_switch.ps1            credential-blob switch + capture (Win32 CredRead/CredWrite)
ax_dispatch.py           task dispatch ENGINE — runs `agy --print` under a
                         pseudo-TTY (pywinpty/ConPTY) and captures the output.
                         agy's typewriter renderer only streams to a real terminal,
                         so a ConPTY is required; plain pipe capture hangs.
ax_dispatch.cmd          flash-reduced wrapper (`ax dispatch` calls this)
ax_limits.py             quota viewer (local IDE account, or --all accounts)
ax_detached.ps1 +        advanced fully-flash-free dispatch via an S4U scheduled
ax_detached_runner.py    task (no desktop = no ConPTY window flash); non-IDE tasks
install_global.ps1       installs the global `ax` command
agy_snapshots/           your captured credential blobs (empty; see its README)
```

> **Why Python for dispatch?** `agy --print` only emits its output to a real TTY.
> Capturing it requires a pseudo‑console (ConPTY); pywinpty does this cleanly. A
> pure‑PowerShell capture isn't possible (it hangs), so the proven Python engine
> stays under the hood — you still just type `ax dispatch …`.

## For an AI agent

`AGENTS.md` has the quickstart. In short: write the task to a `.md`, run
`ax dispatch <file>` in the background, read `AGY_DONE_<account>.md` (success =
non‑empty, exit 0). Check quota with `ax limits`.

## Security

- No accounts or tokens are bundled — you log in your own.
- `agy_snapshots/*.bin` are live OAuth blobs — treat like passwords; never commit
  (the `.gitignore` excludes them, plus `AGY_DONE_*.md`).
