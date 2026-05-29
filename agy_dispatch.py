"""agy_dispatch.py — Antigravity (agy CLI) dispatcher with ConPTY wrapper.

Sibling of cx_dispatch.py for Codex. Solves the Windows agy --print stdio
capture bug by allocating a pseudo-TTY via pywinpty: agy's text_drip
typewriter renderer happily writes to the PTY (thinks it's a real terminal),
and we drain everything on the read side. Output is ANSI-stripped and
written to AGY_DONE_<account>.md plus appended to shared AGY_DONE.md.

Required: pip install pywinpty
Verified prerequisite: $env:TERM='xterm-256color' (set internally)

Usage:
  python agy_dispatch.py --task-file tasks/foo.md [--account <prefix>]
                         [--print-timeout 120] [--no-swap]

  # canary self-test (verifies UnityMCP connectivity)
  python agy_dispatch.py --test

Account selection:
  --account <prefix>   Force a specific captured account (substring match)
  default              Round-robin via STAGING/agy_snapshots/cred_blob_*.bin
                       state in .agy_dispatch_state.json, locked accounts skipped

Exit codes:
  0  Got a non-empty response, agy exited cleanly
  1  Empty response / agy non-zero exit / timeout / swap failed
  2  Environment problem (pywinpty missing, agy not found, etc.)
"""

import sys
import os
import re
import time
import json
import argparse

# --- Windows window suppression (must run BEFORE pywinpty / subprocess imports) ---
#
# Problem: `python agy_dispatch.py` from Bash tool runs under python.exe which is
# a CONSOLE-subsystem binary. Windows briefly attaches a conhost.exe window when
# the process starts, and pywinpty/ConPTY's CreatePseudoConsole can also trigger
# a brief flash on the active monitor — stealing focus mid-game.
#
# Strategy (two-step):
#   1) If we ARE python.exe and a pythonw.exe is available, re-exec ourselves
#      under pythonw.exe (a GUI-subsystem binary — Windows allocates NO console
#      for it). The child inherits stdout/stderr handles, so background-task
#      output capture still works. Parent waits and propagates exit code.
#   2) Fallback: if pythonw isn't available, or we're already pythonw, hide the
#      console window aggressively (AllocConsole + move offscreen + SW_HIDE).
#
# Sentinel env var `AGY_DISPATCH_RELAUNCHED=1` prevents fork-bomb.
if sys.platform == "win32":
    # Debug log so we can verify whether pythonw self-relaunch is actually happening
    try:
        _dbg = Path(__file__).parent / ".agy_dispatch_relaunch.log" if False else None
    except Exception:
        _dbg = None
    try:
        import time as _t
        _log_path = os.path.join(os.path.dirname(__file__), ".agy_dispatch_relaunch.log")
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(f"[{_t.strftime('%H:%M:%S')}] exec={sys.executable} relaunched={os.environ.get('AGY_DISPATCH_RELAUNCHED', '0')} argv={sys.argv[:3]}\n")
    except Exception:
        pass
    try:
        import ctypes
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        SW_HIDE = 0

        _exe_lower = sys.executable.lower()
        _is_pythonw = "pythonw" in _exe_lower

        if not _is_pythonw and os.environ.get("AGY_DISPATCH_RELAUNCHED") != "1":
            # Try to re-exec under pythonw.exe (sibling binary in same install).
            _pythonw_candidates = []
            if _exe_lower.endswith("python.exe"):
                _pythonw_candidates.append(sys.executable[:-len("python.exe")] + "pythonw.exe")
            # Also try a few common install locations as fallback.
            _pythonw_candidates.extend([
                r"C:\Program Files\Python312\pythonw.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"),
            ])
            _pythonw_path = next((p for p in _pythonw_candidates if os.path.exists(p)), None)

            if _pythonw_path:
                import subprocess as _sub
                _CREATE_NO_WINDOW = 0x08000000
                _env = os.environ.copy()
                _env["AGY_DISPATCH_RELAUNCHED"] = "1"

                # STARTUPINFO with SW_HIDE: tells Windows to spawn child with hidden
                # window state at CreateProcess level. More aggressive than CREATE_NO_WINDOW
                # alone — also propagates to grandchildren when they inherit STARTUPINFO.
                # Best effort against ConPTY OpenConsole.exe brief flash.
                _si = _sub.STARTUPINFO()
                _si.dwFlags |= _sub.STARTF_USESHOWWINDOW
                _si.wShowWindow = 0  # SW_HIDE

                try:
                    _proc = _sub.Popen(
                        [_pythonw_path, __file__] + sys.argv[1:],
                        env=_env,
                        creationflags=_CREATE_NO_WINDOW,
                        startupinfo=_si,
                        stdout=sys.stdout if hasattr(sys.stdout, "fileno") else None,
                        stderr=sys.stderr if hasattr(sys.stderr, "fileno") else None,
                        close_fds=False,
                    )
                    sys.exit(_proc.wait())
                except Exception:
                    # Fall through to in-process hide path
                    pass

        # Fallback: hide the existing/allocated console as best we can.
        _hwnd = _kernel32.GetConsoleWindow()
        if not _hwnd:
            try:
                _kernel32.AllocConsole()
                _hwnd = _kernel32.GetConsoleWindow()
            except Exception:
                _hwnd = 0
        if _hwnd:
            try:
                # SWP_NOSIZE(1) | SWP_NOACTIVATE(0x10) | SWP_NOZORDER(4) = 0x15
                _user32.SetWindowPos(_hwnd, 1, -32000, -32000, 0, 0, 0x15)
            except Exception:
                pass
            _user32.ShowWindow(_hwnd, SW_HIDE)
    except Exception:
        pass
import subprocess
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so em-dashes/Turkish chars don't crash print()
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Force ConPTY backend on Windows 10+ — eliminates winpty-agent.exe window flicker.
# Must be set BEFORE `import winpty`. 2 = ConPTY (native, hostless), 1 = legacy winpty.
if sys.platform == "win32":
    os.environ.setdefault("PYWINPTY_BACKEND", "2")

try:
    import winpty
except ImportError:
    print("ERROR: pywinpty not installed. Run: pip install pywinpty", file=sys.stderr)
    sys.exit(2)

# --- S110 ConPTY child window flash hook ---
#
# When pywinpty.PtyProcess.spawn() allocates a ConPTY, Windows creates an
# OpenConsole.exe / PseudoConsoleWindow child window. Even with parent console
# hidden, this child briefly flashes on the active monitor — stealing focus.
#
# Strategy: install a SetWinEventHook for EVENT_OBJECT_CREATE around the spawn
# call. The callback runs out-of-context (system worker thread, GIL safe via
# ctypes WINFUNCTYPE) and immediately SW_HIDE + offscreen-move any window
# whose class matches a known console wrapper.
#
# Tahmin class list — Windows ref docs don't enumerate ConPTY internals; misses
# are non-fatal because SW_HIDE only fires for matched classes (no collateral).
if sys.platform == "win32":
    _EVENT_OBJECT_CREATE = 0x8000
    _WINEVENT_OUTOFCONTEXT = 0x0000
    _WINEVENT_SKIPOWNPROCESS = 0x0002
    _SW_HIDE = 0
    _SWP_FLAGS = 0x15  # NOSIZE | NOZORDER | NOACTIVATE

    _WinEventProcType = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p,   # hWinEventHook
        ctypes.c_ulong,    # event
        ctypes.c_void_p,   # hwnd
        ctypes.c_long,     # idObject
        ctypes.c_long,     # idChild
        ctypes.c_ulong,    # idEventThread
        ctypes.c_ulong,    # dwmsEventTime
    )

    _HIDE_CLASS_NAMES = {
        "ConsoleWindowClass",
        "PseudoConsoleWindow",
        "OpenConsoleWindow",
        "OpenConsole",
        "Windows.UI.Core.CoreWindow",
    }

    def _make_console_hider_callback():
        """Build a SetWinEventHook callback that hides ConPTY child windows.

        Caller MUST retain the returned object as a strong reference for the
        full hook lifetime — if Python GCs the WINFUNCTYPE wrapper while the
        OS still holds the function pointer, the next event triggers a crash.
        """
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        def _cb(hWinEventHook, event, hwnd, idObject, idChild, idEventThread, dwmsEventTime):
            if not hwnd:
                return
            try:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                cls = buf.value
                if cls in _HIDE_CLASS_NAMES:
                    user32.SetWindowPos(hwnd, 1, -32000, -32000, 0, 0, _SWP_FLAGS)
                    user32.ShowWindow(hwnd, _SW_HIDE)
            except Exception:
                pass

        return _WinEventProcType(_cb)


ROOT = Path(__file__).parent.resolve()
AGY_EXE = (os.environ.get("AGY_EXE") or __import__("shutil").which("agy") or __import__("shutil").which("agy.exe") or os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe"))
SNAP_DIR = ROOT / "agy_snapshots"
SWITCHER = ROOT / "agychange.ps1"
LOCK_DIR = ROOT / ".agy_dispatch_locks"
STATE_FILE = ROOT / ".agy_dispatch_state.json"
LOCK_STALE_SECS = 7200  # 2h — auto-release ghost locks

# Fixed account priority (user-set 2026-05-28). Dispatch tries these in order; on a
# swap failure / empty response / timeout it FALLS THROUGH to the next account in the
# list automatically (within one dispatch). Accounts not listed are tried last, in
# glob order. Round-robin is no longer used unless --account overrides.
ACCOUNT_PRIORITY = []  # no preferred order by default; captured accounts tried alphabetically. Edit to set priority.

# ANSI escape sequences: CSI (most common), OSC, charset selects, single-char escapes.
ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]"     # CSI ... letter
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL or ST
    r"|\x1b[()][AB012]"            # charset designation
    r"|\x1b[><=ZcDEHM78]"          # single-char ESC sequences
)


def strip_ansi(s: str) -> str:
    # First strip ANSI escape sequences, then collapse stray carriage returns,
    # then squash >2 consecutive blank lines (typewriter often leaves them).
    s = ANSI_RE.sub("", s)
    s = s.replace("\r\n", "\n").replace("\r", "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


def list_accounts() -> list[str]:
    if not SNAP_DIR.exists():
        return []
    return sorted(p.stem.replace("cred_blob_", "") for p in SNAP_DIR.glob("cred_blob_*.bin"))


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_account": None, "last_used": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def pick_next_account(accounts: list[str], state: dict) -> str | None:
    if not accounts:
        return None
    last = state.get("last_account")
    if last in accounts:
        idx = (accounts.index(last) + 1) % len(accounts)
    else:
        idx = 0
    return accounts[idx]


def order_by_priority(accounts: list[str]) -> list[str]:
    """Order accounts by ACCOUNT_PRIORITY (listed first, in order); unlisted appended
    alphabetically. Used to build the fallback chain for a single dispatch."""
    rank = {name: i for i, name in enumerate(ACCOUNT_PRIORITY)}
    return sorted(accounts, key=lambda a: (rank.get(a, len(ACCOUNT_PRIORITY)), a))


def is_locked(account: str) -> bool:
    p = LOCK_DIR / f"{account}.lock"
    if not p.exists():
        return False
    try:
        if time.time() - p.stat().st_mtime > LOCK_STALE_SECS:
            p.unlink(missing_ok=True)
            return False
        return True
    except OSError:
        return False


def acquire_lock(account: str) -> Path:
    LOCK_DIR.mkdir(exist_ok=True)
    p = LOCK_DIR / f"{account}.lock"
    p.write_text(str(os.getpid()), encoding="utf-8")
    return p


def release_lock(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


_NO_WINDOW_FLAG = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _hidden_startupinfo():
    """STARTUPINFO with wShowWindow=SW_HIDE. Belt-and-suspenders with CREATE_NO_WINDOW.

    On Windows 11 with Windows Terminal as default, CREATE_NO_WINDOW alone can still
    cause a Z-order flash when the parent is attached to a console. STARTUPINFO with
    STARTF_USESHOWWINDOW + SW_HIDE tells CreateProcess at the kernel level to spawn
    the child with hidden window state, propagated even when the child re-spawns.
    """
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


def swap_account(account: str) -> bool:
    """Restore the account's OAuth blob via agychange.ps1. Returns True on success."""
    if not SWITCHER.exists():
        print(f"ERROR: switcher script not found: {SWITCHER}", file=sys.stderr)
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden",  # PowerShell-level hide hint
             "-File", str(SWITCHER), account],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW_FLAG,  # CreateProcess CREATE_NO_WINDOW
            startupinfo=_hidden_startupinfo(),  # STARTUPINFO SW_HIDE belt-and-suspenders
        )
    except subprocess.TimeoutExpired:
        print("ERROR: agychange.ps1 timeout after 15s", file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"WARN: agychange.ps1 exit {r.returncode}: {r.stderr.strip()}", file=sys.stderr)
        return False
    # The "[OK] Swapped" line is the signal of success
    return "[OK] Swapped" in (r.stdout or "")


def run_agy_via_pty(prompt: str, print_timeout: int) -> tuple[str, int | None]:
    """Spawn agy under a pseudo-TTY and capture all output. Returns (clean_text, exit_code).

    S110 ConPTY child window flash fix (3-layer strategy):
      1. SetWinEventHook EVENT_OBJECT_CREATE catches OpenConsole/ConsoleWindowClass
         spawn around winpty.PtyProcess.spawn() and forces SW_HIDE + offscreen move.
      2. Pre-spawn re-hide of own console (race-safety — domain reload or external
         activation may have made our parent console visible again).
      3. TODO: --detached flag for non-UnityMCP dispatch via Scheduled Task
         (Session 0). Out of scope for this edit.
    """
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"

    argv = [
        AGY_EXE,
        "--print", prompt,
        "--dangerously-skip-permissions",
        "--print-timeout", f"{print_timeout}s",
    ]

    # Layer 1+2: install ConPTY child window hide hook + re-hide own console
    _hook = None
    _hook_user32 = None
    _hook_callback_ref = None  # strong ref — keep alive until UnhookWinEvent
    if sys.platform == "win32":
        try:
            _hook_user32 = ctypes.WinDLL("user32", use_last_error=True)
            _hook_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # Layer 2: race-safe re-hide of own console (may have re-appeared)
            try:
                _own_hwnd = _hook_kernel32.GetConsoleWindow()
                if _own_hwnd:
                    _hook_user32.SetWindowPos(_own_hwnd, 1, -32000, -32000, 0, 0, _SWP_FLAGS)
                    _hook_user32.ShowWindow(_own_hwnd, _SW_HIDE)
            except Exception:
                pass
            # Layer 1: install event hook for ConPTY child windows
            _hook_callback_ref = _make_console_hider_callback()
            _hook = _hook_user32.SetWinEventHook(
                _EVENT_OBJECT_CREATE, _EVENT_OBJECT_CREATE,
                None,
                _hook_callback_ref,
                0, 0,
                _WINEVENT_OUTOFCONTEXT | _WINEVENT_SKIPOWNPROCESS,
            )
        except Exception:
            _hook = None

    try:
        proc = winpty.PtyProcess.spawn(
            argv,
            env=env,
            cwd=str(ROOT),
            dimensions=(40, 200),  # rows, cols — wide enough that text_drip doesn't wrap
        )
    finally:
        if _hook and sys.platform == "win32":
            try:
                _hook_user32.UnhookWinEvent(_hook)
            except Exception:
                pass
        _hook_callback_ref = None  # safe to release after spawn / unhook

    chunks: list[str] = []
    hard_deadline = time.time() + print_timeout + 30  # generous safety margin

    while time.time() < hard_deadline:
        try:
            data = proc.read(8192)
        except EOFError:
            break
        except OSError:
            # PTY closed unexpectedly
            break
        if data:
            chunks.append(data)
            continue
        # No data and process dead = real EOF
        if not proc.isalive():
            # Final drain
            for _ in range(5):
                try:
                    tail = proc.read(8192)
                except EOFError:
                    break
                if not tail:
                    break
                chunks.append(tail)
            break
        # No data but still alive — short pause and retry
        time.sleep(0.05)

    timed_out = time.time() >= hard_deadline
    if proc.isalive():
        try:
            proc.terminate()
            time.sleep(0.3)
            if proc.isalive():
                proc.kill()
        except Exception:
            pass

    exit_code: int | None
    try:
        exit_code = proc.exitstatus
    except Exception:
        exit_code = None

    raw = "".join(chunks)
    clean = strip_ansi(raw)
    if timed_out:
        clean += f"\n[agy_dispatch] HARD_TIMEOUT after {print_timeout + 30}s\n"
    return clean, exit_code


CANARY_PROMPT = (
    "Reply with EXACTLY three short lines and nothing else. "
    "Line1: AGY_ONLINE. "
    "Line2: MCP_SERVERS=<comma-separated names of MCP servers you can call, or NONE>. "
    "Line3: UNITY_CHECK=<if UnityMCP listed, call its read_console tool with last 1 entry; "
    "reply CONNECTED if call returned data, NOT_CONNECTED if errored, ABSENT if not in list>."
)


def main() -> int:
    p = argparse.ArgumentParser(description="Antigravity dispatcher (ConPTY wrapper)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--task-file", help="Path to .md file containing the prompt")
    g.add_argument("--test", action="store_true",
                   help="Run canary prompt (UnityMCP connectivity check)")
    p.add_argument("--account", default=None,
                   help="Account prefix (else round-robin)")
    p.add_argument("--print-timeout", type=int, default=120,
                   help="agy --print-timeout in seconds (default 120)")
    p.add_argument("--no-swap", action="store_true",
                   help="Skip agychange.ps1 swap (use whatever's currently active)")
    p.add_argument("--list-accounts", action="store_true",
                   help="Print available accounts and exit")
    args = p.parse_args()

    if not (args.task_file or args.test or args.list_accounts):
        p.error("one of --task-file, --test, or --list-accounts is required")

    if not Path(AGY_EXE).exists():
        print(f"ERROR: agy.exe not found at {AGY_EXE}", file=sys.stderr)
        return 2

    accounts = list_accounts()

    if args.list_accounts:
        print(json.dumps({"accounts": accounts, "state": load_state()}, indent=2))
        return 0

    # Load prompt
    if args.test:
        prompt = CANARY_PROMPT
    else:
        tf = Path(args.task_file)
        if not tf.exists():
            print(f"ERROR: task file not found: {tf}", file=sys.stderr)
            return 1
        prompt = tf.read_text(encoding="utf-8").strip()
        if not prompt:
            print("ERROR: task file is empty", file=sys.stderr)
            return 1

    # Account selection — build a priority-ordered candidate chain.
    state = load_state()
    if args.account:
        matches = [a for a in accounts if args.account in a]
        if not matches:
            print(f"ERROR: no account matching '{args.account}'. Available: {accounts}",
                  file=sys.stderr)
            return 1
        candidates = [matches[0]]  # explicit override: single account, no fallback
    else:
        candidates = [a for a in order_by_priority(accounts) if not is_locked(a)]
        if not candidates:
            print(f"ERROR: all accounts locked/unavailable: {accounts}", file=sys.stderr)
            return 1
        print(f"PRIORITY CHAIN: {candidates}", file=sys.stderr)

    # Try each candidate in order; fall through to the next on swap-fail/empty/timeout.
    last_err = "no candidates"
    for account in candidates:
        print(f"ACCOUNT_SELECTED: {account}", file=sys.stderr)

        if not args.no_swap:
            print(f"Swapping cred blob -> {account}...", file=sys.stderr)
            if not swap_account(account):
                print(f"WARN: swap to {account} failed -> next account", file=sys.stderr)
                last_err = f"swap failed ({account})"
                continue

        lock = acquire_lock(account)
        t0 = time.time()
        try:
            clean, exit_code = run_agy_via_pty(prompt, print_timeout=args.print_timeout)
        finally:
            release_lock(lock)
        dur = int(time.time() - t0)

        # Persist result (every attempt, so failures are inspectable on disk).
        safe_acct = re.sub(r"[^a-zA-Z0-9_-]", "_", account)
        done_file = ROOT / f"AGY_DONE_{safe_acct}.md"
        done_file.write_text(clean, encoding="utf-8")

        shared = ROOT / "AGY_DONE.md"
        with open(shared, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n## {account} @ {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(dur={dur}s, exit={exit_code})\n\n{clean}\n")

        state["last_account"] = account
        state.setdefault("last_used", {})[account] = time.time()
        save_state(state)

        body = clean.strip()
        if "HARD_TIMEOUT" in body:
            print(f"WARN: {account} timed out ({args.print_timeout + 30}s) -> next account", file=sys.stderr)
            last_err = f"timeout ({account})"
            continue
        if not body:
            print(f"WARN: {account} returned empty (exit={exit_code}, dur={dur}s) -> next account", file=sys.stderr)
            last_err = f"empty ({account})"
            continue

        # Success.
        print(clean)
        print(f"SUCCESS via {account} (dur={dur}s)", file=sys.stderr)
        return 0

    print(f"FAILED: all priority accounts exhausted — last: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
