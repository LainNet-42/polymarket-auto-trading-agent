"""
Hooks for risk control and audit logging.

Phase 1: Logging only (read-only agent)
Phase 2: Will add order limits and risk controls
"""

import json
from datetime import datetime, timezone
from pathlib import Path


# Audit log file (inside workspace)
from config.paths import WORKSPACE
AUDIT_LOG = WORKSPACE / "log" / "agent_audit.jsonl"


async def audit_log_hook(input_data: dict, tool_use_id: str, context: dict) -> dict:
    """
    Log all tool uses to audit file.

    PostToolUse hook - runs after each tool execution.
    """
    try:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_use_id": tool_use_id,
            "tool_name": input_data.get("tool_name", "unknown"),
            "tool_input": input_data.get("tool_input", {}),
        }

        # Ensure data directory exists
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

        # Append to log
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    except Exception as e:
        # Don't fail on logging errors
        print(f"[AUDIT] Failed to log: {e}")

    # Don't modify behavior, just log
    return {}


async def risk_control_hook(input_data: dict, tool_use_id: str, context: dict) -> dict:
    """
    Pre-tool-use risk control.

    Phase 1: Just logs warnings (read-only mode)
    Phase 2: Will block dangerous operations
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Phase 2: Uncomment to enable order limits
    # if tool_name == "place_order":
    #     amount = tool_input.get("amount", 0)
    #     MAX_ORDER = 100  # $100 limit
    #
    #     if amount > MAX_ORDER:
    #         return {
    #             "hookSpecificOutput": {
    #                 "hookEventName": "PreToolUse",
    #                 "permissionDecision": "deny",
    #                 "permissionDecisionReason": f"Order amount ${amount} exceeds limit ${MAX_ORDER}"
    #             }
    #         }

    # Phase 1: Just log the action
    print(f"[RISK] Tool: {tool_name}, Input: {json.dumps(tool_input, ensure_ascii=False)[:200]}")

    return {}
