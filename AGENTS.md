# AGENTS.md — using this repo as an AI agent

**AntigravityAuthManager** manages multiple Google accounts for **Antigravity**
(which has both a CLI, `agy`, and an IDE — they share one Google login) and lets
you — an AI — run an `agy` task on a chosen/auto‑selected account and read quota.

## You can USE this tool to delegate work to Antigravity
Prerequisites the human sets up once (you can't — they need browser login):
`agy` installed + Python 3.10+ + `pip install pywinpty` + `agy login`. For multiple
accounts they also capture credential blobs into `agy_snapshots/` (see its README).

1. Write the task to a file, e.g. `task.md` — self‑contained; tell the worker to
   **run** the steps, not describe them.
2. Dispatch in the background (the `.cmd` wrapper avoids a console flash):
   `cmd //c "agy_dispatch.cmd" --task-file task.md --print-timeout 600`
   - `--account <prefix>` pins a captured account; `--no-swap` uses the active one
     (single‑account mode).
3. Read the result from `AGY_DONE_<account>.md`. **Success = non‑empty output, exit 0.**
   On swap‑fail/empty/timeout it auto‑falls through to the next account.
4. Check quota first if useful: `python agy_limits.py` (or `--all`).

Parallel dispatches are safe (per‑account lock files). Set preferred order via
`ACCOUNT_PRIORITY = []` near the top of `agy_dispatch.py`.

Full docs: [`README.md`](README.md) and [`agy_snapshots/README.md`](agy_snapshots/README.md).

## Don't
- Don't commit `*.bin` (live OAuth blobs) or `AGY_DONE_*.md` (task output) — already in `.gitignore`.
- Don't hardcode account names — captured accounts are discovered at runtime.
- Switching an account changes the **shared** Antigravity credential, affecting both the CLI and the IDE login.
