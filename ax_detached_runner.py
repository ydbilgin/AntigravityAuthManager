"""ax_detached_runner.py — entry point for the flash-free scheduled task.

The reusable task 'ax_detached' (registered ONCE with admin, S4U principal)
runs THIS script. It reads the per-run request from .ax_detached_request.json,
rebuilds argv, and calls ax_dispatch.main() inside the task's non-interactive
session — so agy.exe's ConPTY child window has no desktop to flash on.

Per-run flow (driven by ax_detached.ps1, no admin needed):
  1. ps1 writes .ax_detached_request.json  {task_file, account?, print_timeout}
  2. ps1 triggers the task (schtasks /run) — running your OWN task needs no elevation
  3. this runner dispatches; ax_dispatch writes AGY_DONE_<account>.md as usual
  4. ps1 reads AGY_DONE_<account>.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
REQ = ROOT / ".ax_detached_request.json"


def main() -> int:
    try:
        req = json.loads(REQ.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — any failure means no valid request
        sys.stderr.write(f"[runner] no/invalid request file: {e}\n")
        return 2

    task_file = req.get("task_file")
    if not task_file:
        sys.stderr.write("[runner] request missing 'task_file'\n")
        return 2

    argv = ["ax_dispatch.py", "--task-file", task_file,
            "--print-timeout", str(req.get("print_timeout", 600))]
    if req.get("account"):
        argv += ["--account", req["account"]]

    # ax_dispatch.py guards main() under __main__, so importing only runs its
    # top-level console-hide block (harmless under pythonw). We drive main() directly.
    sys.argv = argv
    import ax_dispatch  # noqa: E402 — deferred so argv is set first
    return ax_dispatch.main()


if __name__ == "__main__":
    sys.exit(main())
