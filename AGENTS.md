# AGENTS.md — using this repo as an AI agent

**AntigravityAuthManager** gives you a single command, **`ax`**, to run Google's
**Antigravity** (the `agy` CLI) across multiple Google accounts and read quota.
Antigravity keeps one login active at a time (shared by the CLI and the IDE), so
multiple accounts are used by **switching**.

## You can USE this tool to delegate work to Antigravity
Prerequisites the human sets up once (you can't — they need browser login):
`agy` installed + Python 3.10+ + `pip install pywinpty` + `.\install_global.ps1`,
then `agy login` (+ `ax capture <name>` per extra account).

1. Write the task to a file, e.g. `task.md` — self‑contained; tell the worker to
   **run** the steps, not describe them.
2. Dispatch in the background:
   `ax dispatch task.md --print-timeout 600`
   - `--account <prefix>` pins a captured account; `--no-swap` uses the active one.
   - `ax` auto‑selects an account and falls through to the next on failure.
3. Read the result from `AGY_DONE_<account>.md`. **Success = non‑empty output, exit 0.**
4. Check quota first if useful: `ax limits` (or `ax limits --all`).
5. Switch accounts directly with `ax <number>` (e.g. `ax 1`) or `ax <name>`; list with `ax`.

Parallel dispatches are safe (per‑account lock files in `.agy_dispatch_locks/`).

## Don't
- Don't commit `*.bin` (live OAuth blobs) or `AGY_DONE_*.md` (task output) — already `.gitignore`d.
- Don't hardcode account names — captured accounts are discovered at runtime (`ax` lists them).
- Switching an account changes the **shared** Antigravity credential, affecting both the `agy` CLI and the IDE.

Full docs: [`README.md`](README.md).
