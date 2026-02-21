"""
Polymarket High Certainty Strategy Agent

Main entry point for running the analysis agent.

Usage:
    python -m agent.main
    python -m agent.main --query "Fed"
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# Fix Windows encoding issues
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_agent_sdk import query, ClaudeAgentOptions

from agent.prompts import SYSTEM_PROMPT, SCAN_PROMPT


async def run_agent(
    prompt: str = None,
    verbose: bool = True
):
    """
    Run the Polymarket analysis agent.

    Args:
        prompt: Custom prompt (default: market scan)
        verbose: Print all messages
    """
    # Configure options - use existing MCP server instead of SDK tools
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=[
            "WebSearch",
            "WebFetch",
            "mcp__polymarket__search_markets",
            "mcp__polymarket__get_market_details",
            "mcp__polymarket__analyze_opportunity"
        ],
        permission_mode="bypassPermissions",
        cwd=str(Path(__file__).parent.parent),
        max_turns=10
    )

    # Use provided prompt or default scan prompt
    task_prompt = prompt or SCAN_PROMPT

    print("=" * 60)
    print("Polymarket High Certainty Strategy Agent")
    print("=" * 60)
    print(f"Prompt: {task_prompt[:100]}...")
    print("=" * 60)
    print()

    result_text = ""

    async for message in query(prompt=task_prompt, options=options):
        if verbose:
            _print_message(message)

        # Capture final result
        if hasattr(message, 'result'):
            result_text = message.result

    return result_text


def _safe_print(text: str):
    """Print text, handling encoding errors."""
    try:
        # Remove emojis for Windows compatibility
        import re
        clean_text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
        print(clean_text)
    except Exception:
        print(text.encode('ascii', 'replace').decode('ascii'))


def _print_message(message):
    """Print a message from the agent."""
    if hasattr(message, 'type'):
        msg_type = message.type

        if msg_type == 'assistant':
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        _safe_print(block.text)
                    elif hasattr(block, 'type') and block.type == 'tool_use':
                        _safe_print(f"\n[Tool] {block.name}")

        elif msg_type == 'result':
            if hasattr(message, 'result'):
                _safe_print("\n" + "=" * 40)
                _safe_print("RESULT:")
                _safe_print("=" * 40)
                _safe_print(message.result)

    elif hasattr(message, 'result'):
        _safe_print(message.result)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket High Certainty Strategy Agent"
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="Custom search query (e.g., 'Fed rate', 'Trump')"
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        help="Custom prompt for the agent"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only show final result"
    )

    args = parser.parse_args()

    # Build prompt
    if args.prompt:
        prompt = args.prompt
    elif args.query:
        prompt = f"Search for high-certainty markets related to '{args.query}' and analyze them."
    else:
        prompt = None

    # Run with anyio (required by claude-agent-sdk)
    import anyio

    async def _run():
        return await run_agent(prompt=prompt, verbose=not args.quiet)

    try:
        anyio.run(_run)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
