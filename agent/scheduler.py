"""
Polymarket Trading Agent Scheduler

Runs the trading agent every N minutes.

Usage:
    python -m agent.scheduler              # Run every 30 minutes
    python -m agent.scheduler --interval 15  # Run every 15 minutes
    python -m agent.scheduler --once        # Run once and exit
"""

import asyncio
import argparse
import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_agent_sdk import query, ClaudeAgentOptions
from agent.prompts import SYSTEM_PROMPT, HIBERNATE_SYSTEM_PROMPT, HIBERNATE_USER_PROMPT
from hooks.session_start import get_env_config
from config.paths import LEDGER_PATH, TRADING_LOG_PATH, TRACE_DIR, HIBERNATE_CSV_PATH
from config.risk import HIBERNATE_ENABLED, MAX_HIBERNATE_HOURS, DEFAULT_WAKE_INTERVAL_HOURS


def get_invoke_info() -> dict:
    """Read invoke info from trading_log.csv"""
    import csv

    trading_log_path = TRADING_LOG_PATH

    # Default values
    last_invoke_num = 0
    last_invoke_time = datetime.now(timezone.utc)  # Fallback: treat as just started

    if trading_log_path.exists():
        with open(trading_log_path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        if rows:
            last_row = rows[-1]
            try:
                last_invoke_num = int(last_row.get("invoke_num", 0))
            except:
                last_invoke_num = 0
            date_str = last_row.get("date", "")
            # Parse date (format: 2026-01-25 or 2026-01-25 23:59 or 2026-01-25-test)
            try:
                # Remove non-date suffixes like "-test"
                clean_date = date_str.split("-test")[0] if "-test" in date_str else date_str
                clean_date = clean_date.strip()
                # Try formats: "2026-02-04 14:27:47" or "2026-02-04 14:27" or "2026-02-04"
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        last_invoke_time = datetime.strptime(clean_date, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
            except:
                pass

    current_time = datetime.now(timezone.utc)
    duration = current_time - last_invoke_time

    # Format duration since last run
    hours = duration.total_seconds() / 3600
    if hours < 1:
        count_duration = f"{int(duration.total_seconds() / 60)} minutes"
    elif hours < 24:
        count_duration = f"{hours:.1f} hours"
    else:
        count_duration = f"{duration.days} days"

    # Calculate alive time from INIT row (row 0)
    alive_str = ""
    if rows:
        init_date_str = rows[0].get("date", "").strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                init_time = datetime.strptime(init_date_str, fmt).replace(tzinfo=timezone.utc)
                alive_delta = current_time - init_time
                alive_days = alive_delta.days
                alive_hours = int(alive_delta.total_seconds() % 86400 / 3600)
                alive_str = f"{alive_days}d {alive_hours}h"
                break
            except ValueError:
                continue

    return {
        "latest_invoke_num": last_invoke_num + 1,
        "last_invoke_time": last_invoke_time.strftime("%Y-%m-%d %H:%M"),
        "count_duration": count_duration,
        "current_time": current_time.strftime("%Y-%m-%d %H:%M"),
        "alive": alive_str,
    }


def get_account_state() -> str:
    """Read current account state from workspace files."""
    import csv

    # Read ledger
    ledger_path = LEDGER_PATH
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
    else:
        ledger = {"balance_usdc": 0, "positions": []}

    # Format account state
    balance = ledger.get("balance_usdc", 0)
    positions = ledger.get("positions", [])

    state_lines = [
        f"**Balance:** ${balance:.2f} USDC",
        f"**Positions:** {len(positions)}",
    ]

    if positions:
        state_lines.append("\n**Current Holdings:**")
        for pos in positions:
            slug = pos.get("market_slug", "unknown")
            outcome = pos.get("outcome", "?")
            shares = pos.get("shares", 0)
            entry = pos.get("entry_price", 0)
            state_lines.append(f"  - {outcome} @ {slug}: {shares} shares @ ${entry:.3f}")

    # Read trading log (long-term memory)
    if TRADING_LOG_PATH.exists():
        with open(TRADING_LOG_PATH, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        if rows:
            state_lines.append("\n**Trading Log (Memory):**")
            for row in rows[-10:]:  # Last 10 entries
                num = row.get("invoke_num") or "?"
                date = row.get("date") or ""
                decision = (row.get("decision") or "")[:40]
                why = (row.get("why") or "")[:50]
                state_lines.append(f"  #{num} [{date}] {decision} - {why}")

    return "\n".join(state_lines)


def _read_last_hibernate() -> dict | None:
    """Read the last row from hibernate.csv. Returns dict or None."""
    import csv
    if not HIBERNATE_CSV_PATH.exists():
        return None
    try:
        with open(HIBERNATE_CSV_PATH, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        last = rows[-1]
        return {
            "timestamp": last.get("timestamp", ""),
            "wake_time": last.get("wake_time", ""),
            "hours": last.get("hours", ""),
            "invoke_num": last.get("invoke_num", ""),
            "d_mail": last.get("d_mail", ""),
            "source": last.get("source", ""),
        }
    except Exception:
        return None


def _read_last_tool_hibernate() -> dict | None:
    """Read the last tool-sourced (agent-written) hibernate row, skipping fallbacks."""
    import csv
    if not HIBERNATE_CSV_PATH.exists():
        return None
    try:
        with open(HIBERNATE_CSV_PATH, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for row in reversed(rows):
            if row.get("source") == "tool":
                return {
                    "timestamp": row.get("timestamp", ""),
                    "wake_time": row.get("wake_time", ""),
                    "hours": row.get("hours", ""),
                    "invoke_num": row.get("invoke_num", ""),
                    "d_mail": row.get("d_mail", ""),
                    "source": row.get("source", ""),
                }
        return None
    except Exception:
        return None


def _write_fallback_hibernate(d_mail: str = "", invoke_num: int = None):
    """Write a fallback hibernate row when agent didn't call hibernate() itself."""
    import csv
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    wake_dt = now + timedelta(hours=DEFAULT_WAKE_INTERVAL_HOURS)

    write_header = not HIBERNATE_CSV_PATH.exists()
    with open(HIBERNATE_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "wake_time", "hours", "invoke_num", "d_mail", "source"])
        safe_mail = d_mail.replace("\n", " ").replace("\r", "") if d_mail else ""
        writer.writerow([now.isoformat(), wake_dt.isoformat(), DEFAULT_WAKE_INTERVAL_HOURS, invoke_num or "", safe_mail, "fallback"])


def _build_allowed_tools() -> list[str]:
    """Build allowed_tools list. Hibernate tool only included when enabled."""
    tools = [
        "Read",
        "Edit",
        "Bash",
        "WebSearch",
        "WebFetch",
        "mcp__polymarket__find_opportunities",
        "mcp__polymarket__get_market_details",
        "mcp__polymarket__get_balance",
        "mcp__polymarket__place_order",
        "mcp__polymarket__search_markets",
        "mcp__polymarket__analyze_opportunity",
    ]
    if HIBERNATE_ENABLED:
        tools.append("mcp__polymarket__hibernate")
    return tools


def should_skip_invoke() -> tuple[bool, str]:
    """
    Check if we should skip this invoke due to hibernation.
    Returns (should_skip: bool, reason: str).
    """
    if not HIBERNATE_ENABLED:
        return False, ""

    last = _read_last_hibernate()
    if not last:
        return False, ""

    try:
        wake_dt = datetime.fromisoformat(last["wake_time"])
        if wake_dt.tzinfo is None:
            wake_dt = wake_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False, ""

    now = datetime.now(timezone.utc)
    if now < wake_dt:
        remaining = (wake_dt - now).total_seconds() / 3600
        reason = f"Hibernating until {wake_dt.strftime('%Y-%m-%d %H:%M')} UTC ({remaining:.1f}h remaining)"
        if last.get("d_mail"):
            reason += f" | D-mail: {last['d_mail'][:500]}"
        return True, reason

    return False, ""


def _seconds_until_wake() -> float:
    """Return seconds until wake_time from hibernate.csv. 0 if past or unavailable."""
    last = _read_last_hibernate()
    if not last:
        return 0
    try:
        wake_dt = datetime.fromisoformat(last["wake_time"])
        if wake_dt.tzinfo is None:
            wake_dt = wake_dt.replace(tzinfo=timezone.utc)
        return max(0, (wake_dt - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError):
        return 0


async def run_scheduled_agent(interval_minutes: int = 30, verbose: bool = True, custom_prompt: str = None):
    """Run the agent with account state injected. If custom_prompt is given, replaces the default workflow prompt."""

    # Run session_start hook directly (sync balance, auto-redeem, etc.)
    # This must run BEFORE get_account_state() so ledger.json is up-to-date.
    from hooks.session_start import main as session_start_main
    try:
        session_start_main()
    except Exception as e:
        print(f"[SessionStart] Error: {e}")

    # Get invoke info and account state
    invoke_info = get_invoke_info()
    account_state = get_account_state()

    # Build user prompt with dynamic variables
    current_datetime = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # D-mail injection: show last agent-written D-mail + system notes
    d_mail_section = ""
    if HIBERNATE_ENABLED:
        last_hib = _read_last_hibernate()
        last_tool_hib = _read_last_tool_hibernate()
        d_mail_parts = []
        if last_tool_hib and last_tool_hib.get("d_mail"):
            ts = last_tool_hib.get("timestamp", "?")
            d_mail_parts.append(
                f"[From invoke #{last_tool_hib.get('invoke_num', '?')}, sent {ts}] {last_tool_hib['d_mail']}"
            )
        if last_hib and last_hib.get("d_mail") and last_hib.get("source") != "tool":
            ts = last_hib.get("timestamp", "?")
            d_mail_parts.append(f"[System note, {ts}] {last_hib['d_mail']}")
        if d_mail_parts:
            d_mail_section = "\n## D-mail from your past self\n" + "\n".join(d_mail_parts) + "\n"

    if custom_prompt:
        prompt = f"""
Invocation #{invoke_info['latest_invoke_num']} (CUSTOM PROMPT)
Current Time: {current_datetime}
{d_mail_section}
## Current Account State

{account_state}

---

{custom_prompt}

---
[IMPORTANT] After completing tasks, edit the LAST LINE of {TRADING_LOG_PATH} to fill in decision and why.
   old: {invoke_info['latest_invoke_num']},{current_datetime},,
   new: {invoke_info['latest_invoke_num']},{current_datetime},TEST,<what you did>
"""
    else:
        prompt = f"""
Invocation #{invoke_info['latest_invoke_num']}
Current Time: {current_datetime}
Last Run: {invoke_info['last_invoke_time']} ({invoke_info['count_duration']} ago)
{d_mail_section}
## Current Account State

{account_state}

---

1. Read your trading log ({TRADING_LOG_PATH}).
2. Find opportunities, research, and trade (or NOT).
3. [IMPORTANT] Edit the LAST LINE of {TRADING_LOG_PATH} to record your decision.
   old: {invoke_info['latest_invoke_num']},{current_datetime},,
   new: {invoke_info['latest_invoke_num']},{current_datetime},<decision>,<why>
"""

    if HIBERNATE_ENABLED:
        prompt += HIBERNATE_USER_PROMPT

    # Pre-fill trading_log row: scheduler writes invoke_num + date, agent fills decision + why
    import csv
    with open(TRADING_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([invoke_info["latest_invoke_num"], current_datetime, "", ""])

    # Configure agent with MCP server
    cwd = str(Path(__file__).parent.parent)

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT + (HIBERNATE_SYSTEM_PROMPT if HIBERNATE_ENABLED else ""),
        mcp_servers={
            "polymarket": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "mcp_server.server"],
                "cwd": cwd
            }
        },
        allowed_tools=_build_allowed_tools(),
        permission_mode="bypassPermissions",
        cwd=cwd,
        max_turns=70
    )

    print("=" * 60)
    print(f"[{invoke_info['current_time']}] Polymarket Trading Agent - Invocation #{invoke_info['latest_invoke_num']}")
    print(f"Time since last run: {invoke_info['count_duration']}")
    if invoke_info.get('alive'):
        print(f"Alive: {invoke_info['alive']}")
    print("=" * 60)
    print(f"{account_state.split(chr(10))[0]}")
    print("=" * 60)
    print()

    result_text = ""

    # Trace directory: TRACE_DIR/YYYY-MM-DD/invoke_{num}.jsonl
    trace_dir = TRACE_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"invoke_{invoke_info['latest_invoke_num']}.jsonl"

    MAX_AGENT_RETRIES = 2
    TRANSIENT_KEYWORDS = ["exit code 1", "tool_use", "rate limit", "overloaded"]

    for attempt in range(MAX_AGENT_RETRIES + 1):
        agent_error = None
        result_text = ""
        try:
            async for message in query(prompt=prompt, options=options):
                if verbose:
                    _print_message(message)

                # Log to trace file
                _log_trace(trace_path, invoke_info['latest_invoke_num'], message)

                if hasattr(message, 'result'):
                    result_text = message.result
        except Exception as e:
            agent_error = e
            print(f"Agent SDK error: {e}")

        # Check if transient error worth retrying
        if (
            agent_error
            and attempt < MAX_AGENT_RETRIES
            and any(k in str(agent_error).lower() for k in TRANSIENT_KEYWORDS)
        ):
            print(f"[Retry] Transient error, retrying ({attempt + 1}/{MAX_AGENT_RETRIES})...")
            await asyncio.sleep(5)
            # Use separate trace file for retry
            trace_path = trace_dir / f"invoke_{invoke_info['latest_invoke_num']}_retry{attempt + 1}.jsonl"
            continue

        # Success or non-transient error: exit loop
        break

    # Post-loop: hibernate fallback + error marking (runs once after all retries)
    try:
        if HIBERNATE_ENABLED:
            last_hib = _read_last_hibernate()
            invoke_start = datetime.fromisoformat(current_datetime.replace(" ", "T") + "+00:00")
            agent_set_hibernate = (
                last_hib
                and last_hib.get("source") == "tool"
                and datetime.fromisoformat(last_hib["timestamp"]) > invoke_start
            )
            if not agent_set_hibernate:
                d_mail_msg = (
                    f"(auto) Invoke #{invoke_info['latest_invoke_num']} ERROR: {str(agent_error)[:200]}"
                    if agent_error else
                    f"(auto) Invoke #{invoke_info['latest_invoke_num']} did not set hibernate, using default {DEFAULT_WAKE_INTERVAL_HOURS}h interval"
                )
                _write_fallback_hibernate(d_mail=d_mail_msg, invoke_num=invoke_info['latest_invoke_num'])
                print(f"[Hibernate] Fallback: {DEFAULT_WAKE_INTERVAL_HOURS}h interval")
    except Exception as fallback_err:
        print(f"[Hibernate] Fallback write failed: {fallback_err}")

    # Mark trading_log on error
    if agent_error:
        _mark_trading_log_error(invoke_info['latest_invoke_num'], str(agent_error)[:200])

    if agent_error:
        raise agent_error

    return result_text


def _mark_trading_log_error(invoke_num: int, error_msg: str):
    """Update the pre-filled trading_log row with ERROR status."""
    try:
        # Sanitize: strip newlines to prevent CSV corruption
        safe_msg = error_msg.replace("\n", " ").replace("\r", "")
        lines = TRADING_LOG_PATH.read_text(encoding="utf-8").splitlines()
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith(f"{invoke_num},"):
                parts = lines[i].split(",", 3)
                if len(parts) >= 4 and not parts[2]:
                    parts[2] = "ERROR"
                    parts[3] = safe_msg
                    lines[i] = ",".join(parts)
                    break
        TRADING_LOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def _log_trace(trace_path: Path, invoke_num: int, message):
    """Log message to trace file. Write summary on ResultMessage."""
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "invoke_num": invoke_num,
            "msg_type": type(message).__name__,
        }

        if hasattr(message, 'type'):
            entry["type"] = message.type

        if hasattr(message, 'content'):
            if isinstance(message.content, list):
                entry["content"] = []
                for block in message.content:
                    if hasattr(block, 'text'):
                        entry["content"].append({"type": "text", "text": block.text[:500]})
                    elif hasattr(block, 'name'):
                        entry["content"].append({"type": "tool_use", "name": block.name, "input": getattr(block, 'input', {})})
                    elif hasattr(block, 'tool_use_id'):
                        content_text = str(block.content)[:500] if hasattr(block, 'content') else ""
                        entry["content"].append({"type": "tool_result", "tool_use_id": block.tool_use_id, "content": content_text})

        if hasattr(message, 'result'):
            entry["result"] = message.result[:1000] if message.result else None

        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Write summary file on ResultMessage
        if type(message).__name__ == "ResultMessage":
            summary = {
                "invoke_num": invoke_num,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "num_turns": getattr(message, 'num_turns', None),
                "duration_ms": getattr(message, 'duration_ms', None),
                "duration_api_ms": getattr(message, 'duration_api_ms', None),
                "total_cost_usd": getattr(message, 'total_cost_usd', None),
                "usage": getattr(message, 'usage', None),
                "is_error": getattr(message, 'is_error', None),
                "session_id": getattr(message, 'session_id', None),
                "result": message.result[:2000] if message.result else None,
            }
            summary_path = trace_path.parent / f"invoke_{invoke_num}_summary.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    except Exception as e:
        # Log trace errors to a debug file instead of silently swallowing
        try:
            err_path = trace_path.parent / "trace_errors.log" if trace_path else Path("trace_errors.log")
            with open(err_path, "a", encoding="utf-8") as ef:
                ef.write(f"{datetime.now(timezone.utc).isoformat()} | {type(e).__name__}: {e}\n")
        except Exception:
            pass


def _print_message(message):
    """Print agent message."""
    import re

    def safe_print(text):
        clean = re.sub(r'[\U00010000-\U0010ffff]', '', str(text))
        print(clean)

    if hasattr(message, 'type'):
        if message.type == 'assistant' and hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text'):
                    safe_print(block.text)
                elif hasattr(block, 'type') and block.type == 'tool_use':
                    safe_print(f"\n[Tool] {block.name}")
        elif message.type == 'result' and hasattr(message, 'result'):
            safe_print("\n" + "=" * 40)
            safe_print("RESULT:")
            safe_print("=" * 40)
            safe_print(message.result)


async def run_scheduler(interval_minutes: int = 30, verbose: bool = True, custom_prompt: str = None):
    """Main scheduler loop."""
    print(f"Starting Polymarket Trading Scheduler")
    print(f"Interval: {interval_minutes} minutes")
    print(f"Press Ctrl+C to stop")
    print()

    run_count = 0

    while True:
        run_count += 1
        print(f"\n{'#' * 60}")
        print(f"# Run #{run_count} at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{'#' * 60}\n")

        # Check hibernate (handles scheduler restart with existing hibernate record)
        skip, reason = should_skip_invoke()
        if skip:
            wake_sec = _seconds_until_wake()
            print(f"[Hibernate] {reason}")
            print(f"Sleeping {wake_sec/3600:.2f}h until wake_time.")
            await asyncio.sleep(wake_sec)
            continue

        try:
            await run_scheduled_agent(interval_minutes, verbose, custom_prompt=custom_prompt)
        except Exception as e:
            print(f"Error during run: {e}")

        # After invoke, hibernate.csv has wake_time (tool or fallback) - sleep directly to it
        if HIBERNATE_ENABLED:
            wake_sec = _seconds_until_wake()
            if wake_sec > 0:
                print(f"\nNext wake in {wake_sec/3600:.2f}h")
                await asyncio.sleep(wake_sec)
                continue

        # Fallback: HIBERNATE_ENABLED=False or no valid wake_time
        print(f"\nSleeping {interval_minutes} minutes until next run...")
        await asyncio.sleep(interval_minutes * 60)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket Trading Agent Scheduler"
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=30,
        help="Interval between runs in minutes (default: 30)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (no loop)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only show final results"
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        default=None,
        help="Custom user prompt (replaces default workflow, use with --once)"
    )

    args = parser.parse_args()

    import anyio

    async def _run():
        if args.once:
            skip, reason = should_skip_invoke()
            if skip:
                print(f"[Hibernate] {reason}")
                print("Skipping this invocation (--once). Exiting.")
                return
            return await run_scheduled_agent(args.interval, not args.quiet, custom_prompt=args.prompt)
        else:
            await run_scheduler(args.interval, not args.quiet, custom_prompt=args.prompt)

    try:
        anyio.run(_run)
    except KeyboardInterrupt:
        print("\nScheduler stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
