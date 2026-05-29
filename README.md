# AntigravityAuthManager

Multi-account **account switcher + task dispatcher + quota viewer** for Google's
**Antigravity** on Windows.

**Antigravity is a product with two surfaces:** a command-line tool (`agy`) and an
IDE (the Antigravity editor / `language_server`). Both log in with the **same
Google account**, stored once in Windows Credential Manager. AntigravityAuthManager
is **not** that CLI or IDE — it is a thin layer on top that lets you keep several
Google accounts ready, switch the active one instantly, run `agy` tasks
non‑interactively across accounts, and read live quota.

> Companion project for the Codex side: **[CodexAuthManager](https://github.com/ydbilgin/CodexAuthManager)**.

---

## Why this exists

The `agy` CLI logs in one Google account at a time, and that login is shared with
the Antigravity IDE. If you have multiple accounts (to spread rate limits), there's
no built-in way to (a) keep them all captured, (b) switch between them from a
script, (c) run a task on whichever account still has quota, or (d) see how much
quota each one has left. This tool adds all four — designed to be driven by a
human **or** an orchestrating AI.

## Features

- **Account switching** (`agychange.ps1`) — instantly point Antigravity at a
  different captured account by restoring its OAuth blob into Windows Credential
  Manager (`LegacyGeneric:target=gemini:antigravity`). Because that credential is
  shared, the switch affects **both the `agy` CLI and the Antigravity IDE**.
- **Account capture** (`agy_snapshots/`) — save each account's credential blob once
  so it can be restored later. You capture your own; nothing is bundled.
- **Task dispatch** (`agy_dispatch.py`) — run a prompt/task through the `agy` CLI
  non‑interactively and capture the full output to a file. Includes:
  - **Automatic account selection** with a priority chain and **fall‑through**: on
    a swap failure / empty response / timeout it moves to the next account in one
    run.
  - **Pseudo‑TTY (ConPTY) capture** — `agy --print` only streams its typewriter
    output to a real terminal, so the dispatcher runs it under a pseudo‑TTY
    (pywinpty) and drains everything, then strips ANSI for a clean `.md` result.
  - **Parallel‑safe** — per‑account lock files prevent two runs grabbing the same
    account.
- **Quota / limits viewer** (`agy_limits.py`) — read remaining model quota:
  - default: the **currently running IDE** account (no quota spent), or
  - `--all`: every account via the community `antigravity-usage` CLI, rendered as a
    table that separates the ~5h window from longer reset windows.
- **Flash‑free detached mode** (`agy_detached.ps1`, advanced/optional) — ConPTY
  briefly flashes a console window on the desktop; running `agy` inside a Task
  Scheduler **S4U** (non‑interactive) job gives it no desktop, so there is no flash.
  For non‑IDE (web/research) tasks only.

## Requirements (Windows)

1. **Python 3.10+** on PATH.
2. **`agy` CLI** installed (Antigravity command line). Verify: `agy --version`.
3. **pywinpty**: `pip install pywinpty`
4. *(optional, for `agy_limits.py --all`)* `npm install -g antigravity-usage`

> The scripts auto‑find `agy` on PATH. If it lives elsewhere, set
> `AGY_EXE=C:\path\to\agy.exe` before running.

## Setup

```powershell
agy login          # complete the Google sign-in for your first account
```

- **One account?** You're done — dispatch with `--no-swap`.
- **Multiple accounts?** Capture one credential blob per account into
  `agy_snapshots/` (step‑by‑step guide in [`agy_snapshots/README.md`](agy_snapshots/README.md)).
  After that, the dispatcher swaps between them automatically.

## Usage

### Switch the active account
```powershell
.\agychange.ps1                 # list captured accounts + show the active one
.\agychange.ps1 <name>          # switch (e.g. a localpart or full email)
.\agychange.ps1 -Active         # print the current active email only
```

### Dispatch a task
```bash
# From bash (no console flash — preferred wrapper):
cmd //c "agy_dispatch.cmd" --task-file mytask.md --print-timeout 600

# Or directly:
python agy_dispatch.py --task-file mytask.md --print-timeout 600 [--account <prefix>] [--no-swap]

# Connectivity self-test (also checks MCP/UnityMCP reachability):
python agy_dispatch.py --test
```
- Result is written to `AGY_DONE_<account>.md` (and appended to `AGY_DONE.md`).
- `--account <prefix>` forces a captured account (substring match, no fallback).
- `--no-swap` uses whatever account is currently active (single‑account mode).
- Set a preferred order by editing `ACCOUNT_PRIORITY = []` near the top of
  `agy_dispatch.py` (empty = captured accounts tried alphabetically).

### View quota
```bash
python agy_limits.py            # active IDE account (Antigravity must be running)
python agy_limits.py --all      # all accounts (needs antigravity-usage installed)
```

### Flash‑free dispatch (advanced)
See the header of `agy_detached.ps1`. Needs a one‑time admin registration of a
Task Scheduler job; afterwards it runs with no window flash. Non‑IDE tasks only.

## For an AI agent / orchestrator

1. Write the task prompt to a `.md` file (self‑contained; tell the worker to **run**
   steps, not describe them).
2. Run in the background: `cmd //c "agy_dispatch.cmd" --task-file <file> --print-timeout 600`.
3. Read the result from `AGY_DONE_<account>.md`. Success = non‑empty output, exit 0.
4. Parallel runs are safe (per‑account locks in `.agy_dispatch_locks/`).
5. Check quota before a big batch: `python agy_limits.py`.

## How it works

- **Credential swap:** Antigravity stores its Google login as a single Windows
  Credential Manager entry (`gemini:antigravity`). `agychange.ps1` reads a saved
  `.bin` blob and `CredWrite`s it into that slot, so the next `agy` (or IDE) launch
  uses that account. Capturing is the reverse (`CredRead` → save bytes).
- **Output capture:** `agy --print` renders a typewriter stream meant for a TTY.
  `agy_dispatch.py` spawns `agy` under a pywinpty pseudo‑console, drains the stream,
  strips ANSI escapes, and writes a clean transcript.
- **No window flash:** the dispatcher re‑execs under `pythonw.exe`, hides its own
  console, and installs a `SetWinEventHook` that hides the ConPTY child window on
  creation. The only fully‑flash‑free path is the S4U detached mode.

## Files

```text
agy_dispatch.py          Dispatch a task on an account (ConPTY capture + fallback)
agy_dispatch.cmd         Bash/CMD wrapper that avoids the console flash (use this)
agy_limits.py            Quota viewer (local IDE account, or --all accounts)
agychange.ps1            Switch the active account via its captured credential blob
agy_detached.ps1         Advanced fully‑flash‑free dispatch (S4U scheduled task)
agy_detached_runner.py   Entry point the scheduled task runs
agy_snapshots/           Your captured per‑account blobs (empty; see its README)
.gitignore               Excludes secrets (*.bin), task output, and runtime files
```

## Security

- **No accounts or tokens are bundled.** You log in your own accounts via `agy`.
- `agy_snapshots/*.bin` are **live OAuth credential blobs** — treat them like
  passwords. Never share or commit them (the `.gitignore` already excludes them).
- `AGY_DONE_*.md` may contain task content — also excluded from git.
