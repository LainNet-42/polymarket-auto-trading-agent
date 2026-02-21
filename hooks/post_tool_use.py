#!/usr/bin/env python3
"""
PostToolUse Hook - Automatically record Polymarket MCP tool calls.

This hook listens for Polymarket MCP tool calls and records them
to decisions.csv for auditing and analysis.
"""
import json
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

def main():
    # Read hook input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only log polymarket MCP tools
    if not tool_name.startswith("mcp__polymarket__"):
        sys.exit(0)

    # Import centralized paths
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.paths import DECISIONS_CSV_PATH
    csv_path = DECISIONS_CSV_PATH

    # Extract decision info
    decision = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name.replace("mcp__polymarket__", ""),
        "market_slug": tool_input.get("slug", ""),
        "action": "ANALYZE",
        "input": json.dumps(tool_input, ensure_ascii=False),
    }

    # Check if CSV exists and has headers
    file_exists = csv_path.exists()

    # Append to CSV
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "tool", "market_slug", "action", "input"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        # Write header if new file
        if not file_exists:
            writer.writeheader()

        writer.writerow(decision)

    sys.exit(0)

if __name__ == "__main__":
    main()
