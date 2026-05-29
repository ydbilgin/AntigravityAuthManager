"""ax_limits.py - Antigravity quota display for RIMA.

Usage:
  python STAGING/ax_limits.py
  python STAGING/ax_limits.py --all [--refresh]

Default mode reads the running Antigravity IDE language_server on localhost and
prints the active IDE account's model quota. This uses the same local data the
Antigravity UI sees and does not spend model quota.

Multi-account mode uses the community `antigravity-usage` CLI as the
authenticated transport, then renders a RIMA-specific table that tracks the
normal ~5h window separately from any long/weekly reset window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SNAP_DIR = ROOT / "agy_snapshots"
STATE_FILE = ROOT / ".ax_dispatch_state.json"
STATUS_ENDPOINT = "/exa.language_server_pb.LanguageServerService/GetUserStatus"
SHORT_WINDOW_MAX_MS = 6 * 60 * 60 * 1000


@dataclass
class LocalServer:
    pid: int
    csrf_token: str
    ports: list[int]


def run_powershell_json(command: str) -> Any:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    text = result.stdout.strip()
    if not text:
        return []
    return json.loads(text)


def discover_servers() -> list[LocalServer]:
    ps = r"""
$procs = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq 'language_server.exe' -and
    $_.CommandLine -match 'antigravity' -and
    $_.CommandLine -match '--csrf_token'
  }

$items = foreach ($p in $procs) {
  $token = $null
  if ($p.CommandLine -match '--csrf_token\s+([A-Za-z0-9-]+)') {
    $token = $Matches[1]
  }
  $ports = @(Get-NetTCPConnection -OwningProcess $p.ProcessId -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
    Select-Object -ExpandProperty LocalPort)
  [pscustomobject]@{
    pid = $p.ProcessId
    csrf_token = $token
    ports = $ports
  }
}

$items | ConvertTo-Json -Depth 5
"""
    raw = run_powershell_json(ps)
    if isinstance(raw, dict):
        raw = [raw]
    servers: list[LocalServer] = []
    for item in raw or []:
        token = item.get("csrf_token")
        ports = item.get("ports") or []
        if isinstance(ports, int):
            ports = [ports]
        if token and ports:
            servers.append(LocalServer(int(item["pid"]), token, [int(p) for p in ports]))
    return servers


def fetch_status(server: LocalServer) -> dict[str, Any]:
    ctx = ssl._create_unverified_context()
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "x-codeium-csrf-token": server.csrf_token,
    }
    body = b"{}"
    errors: list[str] = []
    for port in server.ports:
        url = f"https://127.0.0.1:{port}{STATUS_ENDPOINT}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            errors.append(f"{port}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def fetch_local_status() -> dict[str, Any]:
    servers = discover_servers()
    if not servers:
        raise RuntimeError("No running Antigravity language_server.exe found")
    errors: list[str] = []
    for server in servers:
        try:
            return fetch_status(server)
        except Exception as exc:
            errors.append(f"pid {server.pid}: {exc}")
    raise RuntimeError("; ".join(errors))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def reset_in(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    seconds = int((dt - datetime.now(dt.tzinfo)).total_seconds())
    if seconds <= 0:
        return "now"
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def reset_at(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    return dt.strftime("%Y-%m-%d %H:%M")


def reset_window_from_ms(ms: int | float | None) -> str:
    if ms is None:
        return "unknown"
    return "5h" if ms <= SHORT_WINDOW_MAX_MS else "long"


def pct(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{int(round(float(value) * 100))}%"


def reset_in_from_ms(ms: int | float | None) -> str:
    if ms is None:
        return "-"
    seconds = max(0, int(ms / 1000))
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"


def rows_from_status(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    user = data.get("userStatus", {})
    plan_status = user.get("planStatus", {}) or {}
    plan_info = plan_status.get("planInfo", {}) or {}
    models = (
        (user.get("cascadeModelConfigData", {}) or {})
        .get("clientModelConfigs", [])
    )
    account = {
        "email": user.get("email", "?"),
        "name": user.get("name", "?"),
        "plan": plan_info.get("planName") or user.get("userTier", {}).get("name") or "?",
        "prompt": plan_status.get("availablePromptCredits", "?"),
        "flow": plan_status.get("availableFlowCredits", "?"),
    }

    rows: list[dict[str, str]] = []
    for model in models:
        quota = model.get("quotaInfo") or {}
        remaining = quota.get("remainingFraction")
        if remaining is None:
            continue
        left = int(round(float(remaining) * 100))
        left = max(0, min(100, left))
        reset_dt = parse_time(quota.get("resetTime"))
        reset_ms = None
        if reset_dt is not None:
            reset_ms = max(0, int((reset_dt - datetime.now(reset_dt.tzinfo)).total_seconds() * 1000))
        rows.append({
            "model": str(model.get("label", "?")),
            "window": reset_window_from_ms(reset_ms),
            "left": f"{left}",
            "used": f"{100 - left}",
            "reset_in": reset_in(reset_dt),
            "reset_at": reset_at(reset_dt),
            "status": "OK" if left > 0 else "BLOCKED",
        })
    rows.sort(key=lambda r: (r["status"] != "OK", r["model"].lower()))
    return account, rows


def print_table(account: dict[str, Any], rows: list[dict[str, str]]) -> None:
    print("Antigravity Usage (local IDE)")
    print(f"Account: {account['email']} ({account['name']})")
    print(f"Plan: {account['plan']} | Prompt credits: {account['prompt']} | Flow credits: {account['flow']}")
    print()
    cols = ("Model", "Window", "Left %", "Used %", "Reset in", "Reset at", "Status")
    widths = (32, 8, 7, 7, 10, 16, 10)
    header = " ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))
    if not rows:
        print("No model quota rows returned by Antigravity.")
        return
    for row in rows:
        cells = (
            row["model"][:32],
            row["window"],
            row["left"],
            row["used"],
            row["reset_in"],
            row["reset_at"],
            row["status"],
        )
        print(" ".join(str(c).ljust(w) for c, w in zip(cells, widths)))


def list_captured_accounts() -> list[str]:
    if not SNAP_DIR.exists():
        return []
    return sorted(p.stem.replace("cred_blob_", "") for p in SNAP_DIR.glob("cred_blob_*.bin"))


def load_dispatch_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def print_multi_account_hint() -> int:
    accounts = list_captured_accounts()
    state = load_dispatch_state()
    last = state.get("last_account", "?")
    print("Antigravity multi-account quota")
    print()
    print("antigravity-usage is not installed/configured on PATH.")
    print("Local mode can read only the currently running Antigravity IDE account.")
    print("For all-account quota, install and login once:")
    print("  npm install -g antigravity-usage")
    print("  antigravity-usage login")
    print("  antigravity-usage accounts add")
    print("  antigravity-usage quota --all")
    print()
    print(f"Captured agy dispatch accounts ({len(accounts)}), last dispatch account: {last}")
    for account in accounts:
        marker = "*" if account == last else " "
        print(f" {marker} {account}")
    return 1


def extract_json_array(text: str) -> list[dict[str, Any]]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise RuntimeError("antigravity-usage did not return a JSON array")
    return json.loads(text[start:end + 1])


def bucket_models(models: list[dict[str, Any]], include_autocomplete: bool) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {
        "5h": {"remaining": None, "reset_ms": None, "count": 0},
        "long": {"remaining": None, "reset_ms": None, "count": 0},
        "unknown": {"remaining": None, "reset_ms": None, "count": 0},
    }
    for model in models:
        if model.get("isAutocompleteOnly") and not include_autocomplete:
            continue
        remaining = model.get("remainingPercentage")
        if remaining is None:
            continue
        reset_ms = model.get("timeUntilResetMs")
        if reset_ms is None:
            reset_dt = parse_time(model.get("resetTime"))
            if reset_dt is not None:
                reset_ms = max(0, int((reset_dt - datetime.now(reset_dt.tzinfo)).total_seconds() * 1000))
        bucket = buckets[reset_window_from_ms(reset_ms)]
        bucket["count"] += 1
        if bucket["remaining"] is None or float(remaining) < float(bucket["remaining"]):
            bucket["remaining"] = remaining
        if reset_ms is not None and (bucket["reset_ms"] is None or int(reset_ms) < int(bucket["reset_ms"])):
            bucket["reset_ms"] = int(reset_ms)
    return buckets


def render_all_account_table(results: list[dict[str, Any]], include_autocomplete: bool) -> None:
    print("Antigravity Usage - All Accounts")
    print("5h tracks reset windows <= 6h. Long tracks longer reset windows when Antigravity exposes them.")
    print()
    cols = ("Account", "Act", "Src", "5h left", "5h reset", "Long left", "Long reset", "Models")
    widths = (29, 3, 6, 8, 10, 9, 10, 6)
    header = " ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))
    for item in results:
        email = str(item.get("email") or (item.get("snapshot") or {}).get("email") or "?")
        snapshot = item.get("snapshot") or {}
        models = snapshot.get("models") or []
        buckets = bucket_models(models, include_autocomplete)
        short = buckets["5h"]
        long = buckets["long"]
        model_count = short["count"] + long["count"] + buckets["unknown"]["count"]
        if item.get("status") != "success":
            status = str(item.get("status", "failed"))
            cells = (email[:29], "*" if item.get("isActive") else "", "-", "-", "-", "-", "-", status)
        else:
            cells = (
                email[:29],
                "*" if item.get("isActive") else "",
                str(snapshot.get("method", "?"))[:6],
                pct(short["remaining"]),
                reset_in_from_ms(short["reset_ms"]),
                pct(long["remaining"]),
                reset_in_from_ms(long["reset_ms"]),
                str(model_count),
            )
        print(" ".join(str(c).ljust(w) for c, w in zip(cells, widths)))
    print()
    print("* = active antigravity-usage account. Use --refresh to bypass cache.")


def render_model_table(results: list[dict[str, Any]], needle: str, include_autocomplete: bool) -> None:
    nl = needle.lower()
    print(f"Antigravity Usage - All Accounts (model filter: '{needle}')")
    print()
    cols = ("Account", "Act", "Model", "Left", "Reset in", "Status")
    widths = (29, 3, 30, 6, 11, 8)
    header = " ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))
    any_match = False
    labels_seen: set[str] = set()
    for item in results:
        email = str(item.get("email") or (item.get("snapshot") or {}).get("email") or "?")
        act = "*" if item.get("isActive") else ""
        if item.get("status") != "success":
            print(" ".join(str(c).ljust(w) for c, w in zip((email[:29], act, "-", "-", "-", str(item.get("status", "failed"))), widths)))
            continue
        models = (item.get("snapshot") or {}).get("models") or []
        for m in models:
            if not include_autocomplete and m.get("isAutocompleteOnly"):
                continue
            labels_seen.add(str(m.get("label", "?")))
        matched = [m for m in models
                   if nl in str(m.get("label", "")).lower()
                   and (include_autocomplete or not m.get("isAutocompleteOnly"))]
        if not matched:
            print(" ".join(str(c).ljust(w) for c, w in zip((email[:29], act, f"(no '{needle}')", "-", "-", "-"), widths)))
            continue
        first = True
        for m in matched:
            any_match = True
            rem = m.get("remainingPercentage")
            reset_ms = m.get("timeUntilResetMs")
            if reset_ms is None:
                dt = parse_time(m.get("resetTime"))
                if dt is not None:
                    reset_ms = max(0, int((dt - datetime.now(dt.tzinfo)).total_seconds() * 1000))
            status = "OK" if (rem is not None and float(rem) > 0) else "BLOCKED"
            cells = (email[:29] if first else "", act if first else "",
                     str(m.get("label", "?"))[:30], pct(rem), reset_in_from_ms(reset_ms), status)
            print(" ".join(str(c).ljust(w) for c, w in zip(cells, widths)))
            first = False
    print()
    if not any_match and labels_seen:
        print(f"No model matched '{needle}'. Available models:")
        for lbl in sorted(labels_seen):
            print(f"  {lbl}")
    else:
        print(f"* = active account. Models matching '{needle}'. Add --all-models to include autocomplete-only.")


def run_antigravity_usage(args: argparse.Namespace) -> int:
    exe = shutil.which("antigravity-usage.cmd") if os.name == "nt" else shutil.which("antigravity-usage")
    if not exe:
        exe = shutil.which("antigravity-usage")
    if not exe:
        return print_multi_account_hint()
    cmd = [exe, "quota", "--all", "--json"]
    if args.refresh:
        cmd.append("--refresh")
    if args.all_models:
        cmd.append("--all-models")
    result = subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.stdout and args.json:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode != 0 and "no accounts" in combined:
        print()
        print("Captured agy dispatch snapshots are present, but antigravity-usage")
        print("needs its own one-time account login roster before --all can query quota.")
        print("Run: antigravity-usage login")
        print("Then add the remaining Google accounts with: antigravity-usage accounts add")
        print()
        print(f"Captured snapshots: {', '.join(list_captured_accounts())}")
    elif result.returncode == 0 and not args.json:
        try:
            data = extract_json_array(result.stdout)
            if args.model:
                render_model_table(data, args.model, args.all_models)
            else:
                render_all_account_table(data, args.all_models)
        except Exception as exc:
            print(result.stdout, end="")
            print(f"ERROR: failed to render RIMA quota table: {exc}", file=sys.stderr)
            return 1
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Antigravity quota status")
    parser.add_argument("--all", action="store_true", help="Use antigravity-usage for all configured accounts")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument("--refresh", action="store_true", help="Pass --refresh to antigravity-usage in --all mode")
    parser.add_argument("--all-models", action="store_true", help="Include autocomplete-only models in --all summary")
    parser.add_argument("--model", metavar="NAME", help="Show only models whose name contains NAME (e.g. --model flash). Works with or without --all.")
    args = parser.parse_args()

    if args.all:
        return run_antigravity_usage(args)

    try:
        status = fetch_local_status()
    except Exception as exc:
        print(f"ERROR: failed to fetch local Antigravity quota: {exc}", file=sys.stderr)
        print("Hint: open Antigravity IDE, then rerun this command.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    account, rows = rows_from_status(status)
    if args.model:
        nl = args.model.lower()
        rows = [r for r in rows if nl in r.get("model", "").lower()]
    print_table(account, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
