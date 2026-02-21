"""
Read-only file readers for workspace data.
All functions return plain dicts/lists, no side effects.
"""
import csv
import json
from pathlib import Path
from typing import Optional


def read_ledger(workspace: Path) -> dict:
    """Read ledger.json -> account state."""
    path = workspace / "ledger.json"
    if not path.exists():
        return {"balance_usdc": 0, "positions": [], "trades": [], "total_value": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def read_trading_log(workspace: Path) -> list[dict]:
    """Read trading_log.csv -> list of decision entries (newest first)."""
    path = workspace / "note" / "trading_log.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Convert invoke_num to int, reverse for newest first
    for row in rows:
        try:
            row["invoke_num"] = int(row.get("invoke_num", 0))
        except (ValueError, TypeError):
            row["invoke_num"] = 0
    rows.reverse()
    return rows


def read_portfolio_history(workspace: Path) -> list[dict]:
    """Read portfolio_history.jsonl -> list of snapshots (oldest first)."""
    path = workspace / "log" / "portfolio_history.jsonl"
    if not path.exists():
        return []
    snapshots = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    snapshots.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return snapshots


def list_traces(workspace: Path) -> list[dict]:
    """Scan trace directories, return invoke summaries (newest first)."""
    trace_dir = workspace / "trace"
    if not trace_dir.exists():
        return []

    summaries = []
    for date_dir in sorted(trace_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for summary_file in sorted(date_dir.glob("invoke_*_summary.json"), reverse=True):
            try:
                data = json.loads(summary_file.read_text(encoding="utf-8"))
                data["date"] = date_dir.name
                summaries.append(data)
            except (json.JSONDecodeError, OSError):
                continue
    return summaries


def read_trace(workspace: Path, invoke_num: int) -> Optional[list[dict]]:
    """Find and parse trace JSONL for a specific invoke number."""
    trace_dir = workspace / "trace"
    if not trace_dir.exists():
        return None

    # Search across date directories
    for date_dir in sorted(trace_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        trace_file = date_dir / f"invoke_{invoke_num}.jsonl"
        if trace_file.exists():
            messages = []
            with open(trace_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return messages
    return None
