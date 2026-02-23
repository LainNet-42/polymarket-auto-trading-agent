#!/usr/bin/env python3
"""One-command setup for Polymarket Auto Trading Agent.

Usage:
    python setup.py             # Full setup (venv, wallet, .env, MCP, hooks)
    python setup.py --approve   # Set wallet allowances (after funding)
    python setup.py --status    # Check current setup status
    python setup.py --test      # Verify everything works
"""

import getpass
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WIN = platform.system() == "Windows"
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts" if WIN else "bin") / ("python.exe" if WIN else "python")
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
HOOKS_SRC = ROOT / ".claude" / "settings.local.json.example"
HOOKS_DST = ROOT / ".claude" / "settings.local.json"
MCP_JSON = ROOT / ".mcp.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_step(num, total, msg):
    print(f"\n{'='*60}")
    print(f"  [{num}/{total}] {msg}")
    print(f"{'='*60}")


def _ok(msg="OK"):
    print(f"  -> {msg}")


def _skip(msg):
    print(f"  -> skip: {msg}")


def _fail(msg):
    print(f"\n  !! ERROR: {msg}")


def _run(cmd, check=True, capture=False, timeout=120, **kwargs):
    """Run a subprocess command. Uses shell=True on Windows for .cmd scripts."""
    shell = WIN and isinstance(cmd, list) and cmd[0] in ("claude", "npm", "npx")
    try:
        if capture:
            result = subprocess.run(
                cmd, capture_output=True, text=True, shell=shell,
                timeout=timeout, **kwargs,
            )
            if check and result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or f"Command failed: {cmd}")
            return result
        return subprocess.run(cmd, check=check, shell=shell, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out ({timeout}s): {cmd}")


def _ask_choice(prompt, options):
    """Ask user to pick from numbered options. Returns 1-based index."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"    [{i}] {opt}")
    while True:
        try:
            choice = int(input(f"  > ").strip())
            if 1 <= choice <= len(options):
                return choice
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(options)}")


def _ask_yn(prompt, default=True):
    """Ask yes/no question. Returns bool."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(f"  {prompt}{suffix}").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# Step 1: Check prerequisites
# ---------------------------------------------------------------------------

def check_prerequisites():
    _print_step(1, 6, "Checking prerequisites")

    # Python version
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 11):
        _fail(f"Python 3.11+ required, got {ver_str}")
        print("  Install from https://www.python.org/downloads/")
        sys.exit(1)
    _ok(f"Python {ver_str}")

    # Claude Code CLI
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        _fail("Claude Code CLI not found")
        print("  Install: npm install -g @anthropic-ai/claude-code")
        print("  Then:    claude login")
        sys.exit(1)
    _ok(f"Claude Code CLI ({claude_cmd})")


# ---------------------------------------------------------------------------
# Step 2: Virtual environment + dependencies
# ---------------------------------------------------------------------------

def setup_venv():
    _print_step(2, 6, "Setting up virtual environment")

    if not VENV_DIR.exists():
        print("  Creating .venv ...")
        _run([sys.executable, "-m", "venv", str(VENV_DIR)])
        _ok(".venv created")
    else:
        _skip(".venv already exists")

    print("  Installing dependencies (this may take a minute) ...")
    _run(
        [str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[trading]", "--quiet"],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    _ok("Dependencies installed")


# ---------------------------------------------------------------------------
# Step 3: Wallet setup
# ---------------------------------------------------------------------------

def setup_wallet():
    """Returns (address, private_key) or (None, None) if .env already configured."""
    _print_step(3, 6, "Wallet setup")

    # Check if .env already has valid keys
    if ENV_FILE.exists():
        existing = _read_env()
        pk = existing.get("POLYGON_WALLET_PRIVATE_KEY", "")
        addr = existing.get("EOA_ADDRESS", "")
        if pk and not pk.startswith("0x_your") and addr and not addr.startswith("0x_your"):
            _skip(f".env already has wallet configured ({addr[:10]}...)")
            return None, None

    choice = _ask_choice(
        "How do you want to set up your wallet?",
        [
            "Generate a new wallet",
            "I have a private key",
        ],
    )

    if choice == 1:
        return _generate_wallet()
    else:
        return _import_wallet()


def _generate_wallet():
    """Generate a new wallet using eth_account (from venv)."""
    result = _run(
        [
            str(VENV_PYTHON), "-c",
            "from eth_account import Account; "
            "a = Account.create(); "
            "print(a.address); "
            "print(a.key.hex())",
        ],
        capture=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        _fail("Failed to generate wallet")
        print(f"  stderr: {result.stderr}")
        sys.exit(1)

    address = lines[0].strip()
    private_key = lines[1].strip()

    print(f"\n  New wallet generated:")
    print(f"    Address:     {address}")
    print(f"    Private Key: {private_key}")
    print()
    print("  !! SAVE YOUR PRIVATE KEY SOMEWHERE SAFE !!")
    print("  !! If you lose it, your funds are gone forever !!")
    return address, private_key


def _import_wallet():
    """Import existing private key, derive address."""
    print()
    pk = getpass.getpass("  Enter your private key (hidden): ").strip()
    if not pk:
        _fail("No private key entered")
        sys.exit(1)
    if not pk.startswith("0x"):
        pk = "0x" + pk

    # Derive address from private key
    result = _run(
        [
            str(VENV_PYTHON), "-c",
            f"from eth_account import Account; "
            f"a = Account.from_key('{pk}'); "
            f"print(a.address)",
        ],
        capture=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        _fail("Invalid private key")
        print(f"  {result.stderr.strip()}")
        sys.exit(1)

    address = result.stdout.strip()
    _ok(f"Wallet address: {address}")
    return address, pk


# ---------------------------------------------------------------------------
# Step 4: Write .env
# ---------------------------------------------------------------------------

def _read_env():
    """Read .env into a dict (simple parser, no dependencies)."""
    result = {}
    if not ENV_FILE.exists():
        return result
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def setup_env(address, private_key):
    _print_step(4, 6, "Configuring .env")

    if address is None:
        _skip(".env wallet already configured")
        return

    if ENV_FILE.exists():
        if not _ask_yn(".env already exists. Overwrite wallet keys?"):
            _skip("Keeping existing .env")
            return

    # Read template
    if ENV_EXAMPLE.exists():
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
    else:
        content = (
            "POLYGON_WALLET_PRIVATE_KEY=\n"
            "EOA_ADDRESS=\n"
            "WORKSPACE_DIR=workspace\n"
        )

    # Replace placeholder values
    new_lines = []
    for line in content.splitlines():
        if line.startswith("POLYGON_WALLET_PRIVATE_KEY="):
            new_lines.append(f"POLYGON_WALLET_PRIVATE_KEY={private_key}")
        elif line.startswith("EOA_ADDRESS="):
            new_lines.append(f"EOA_ADDRESS={address}")
        else:
            new_lines.append(line)

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    _ok(f".env written ({address[:10]}...)")


# ---------------------------------------------------------------------------
# Step 5: Register MCP server
# ---------------------------------------------------------------------------

def _mcp_has_polymarket():
    """Check if .mcp.json already has polymarket server configured."""
    if not MCP_JSON.exists():
        return False
    try:
        data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        return "polymarket" in data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return False


def setup_mcp():
    _print_step(5, 6, "Registering MCP server")

    if _mcp_has_polymarket():
        _skip("MCP server 'polymarket' already in .mcp.json")
        return

    # Read existing .mcp.json or create new
    if MCP_JSON.exists():
        try:
            data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    servers["polymarket"] = {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "mcp_server.server"],
    }

    MCP_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _ok("MCP server registered (.mcp.json)")


# ---------------------------------------------------------------------------
# Step 6: Enable hooks
# ---------------------------------------------------------------------------

def setup_hooks():
    _print_step(6, 6, "Enabling hooks")

    if HOOKS_DST.exists():
        _skip("settings.local.json already exists")
        return

    if not HOOKS_SRC.exists():
        _fail(f"Template not found: {HOOKS_SRC}")
        return

    shutil.copy2(HOOKS_SRC, HOOKS_DST)
    _ok("Hooks enabled (SessionStart + PostToolUse)")


# ---------------------------------------------------------------------------
# --approve: Set wallet allowances
# ---------------------------------------------------------------------------

def _check_pol_balance():
    """Check POL balance before running approve. Returns balance as float."""
    env = _read_env()
    address = env.get("EOA_ADDRESS", "")
    if not address:
        return 0.0

    result = _run(
        [
            str(VENV_PYTHON), "-c",
            f"""
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
balance = w3.eth.get_balance('{address}')
print(float(w3.from_wei(balance, 'ether')))
""",
        ],
        capture=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def run_approve():
    print("\n" + "=" * 60)
    print("  Setting wallet allowances (one-time)")
    print("=" * 60)

    if not ENV_FILE.exists():
        _fail(".env not found. Run 'python setup.py' first.")
        sys.exit(1)

    env = _read_env()
    if not env.get("POLYGON_WALLET_PRIVATE_KEY") or env["POLYGON_WALLET_PRIVATE_KEY"].startswith("0x_your"):
        _fail("Wallet not configured in .env. Run 'python setup.py' first.")
        sys.exit(1)

    # Check POL balance before proceeding
    print("\n  Checking POL balance...")
    pol_balance = _check_pol_balance()
    print(f"  POL balance: {pol_balance:.4f}")

    if pol_balance < 0.1:
        _fail(f"Insufficient POL for gas. Need ~1-2 POL, have {pol_balance:.4f}")
        print(f"\n  Fund your wallet with POL on Polygon network:")
        print(f"  Address: {env.get('EOA_ADDRESS', '???')}")
        print(f"  Required: ~2 POL (~$1)")
        sys.exit(1)

    script = ROOT / "scripts" / "set_allowances.py"
    if not script.exists():
        _fail(f"Script not found: {script}")
        sys.exit(1)

    _run(
        [str(VENV_PYTHON), str(script)],
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        cwd=str(ROOT),
    )


# ---------------------------------------------------------------------------
# --status: Check setup status
# ---------------------------------------------------------------------------

def show_status():
    print("\nSetup Status:")
    print("-" * 40)

    checks = [
        (".venv", VENV_DIR.exists()),
        (".env", ENV_FILE.exists() and "0x_your" not in ENV_FILE.read_text(encoding="utf-8")),
        ("Hooks", HOOKS_DST.exists()),
    ]

    # MCP check (read .mcp.json directly)
    checks.append(("MCP server", _mcp_has_polymarket()))

    for name, ok in checks:
        status = "OK" if ok else "NOT SET"
        print(f"  {name:20s} [{status}]")

    if ENV_FILE.exists():
        env = _read_env()
        addr = env.get("EOA_ADDRESS", "")
        if addr and not addr.startswith("0x_your"):
            print(f"\n  Wallet: {addr}")

    all_ok = all(ok for _, ok in checks)
    if all_ok:
        print("\n  All configured! Run: python -m agent.scheduler")
    else:
        print("\n  Run 'python setup.py' to complete setup")


# ---------------------------------------------------------------------------
# --test: Verify setup works
# ---------------------------------------------------------------------------

def run_test():
    print("\n" + "=" * 60)
    print("  Testing setup")
    print("=" * 60)

    errors = []

    # Use venv python if available, otherwise system python
    test_python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

    # Test 1: Check .env
    print("\n  [1/4] Checking .env...")
    if not ENV_FILE.exists():
        errors.append(".env not found")
        _fail(".env not found")
    else:
        env = _read_env()
        if not env.get("EOA_ADDRESS") or env["EOA_ADDRESS"].startswith("0x_your"):
            errors.append("Wallet not configured in .env")
            _fail("Wallet not configured")
        else:
            _ok(f"Wallet: {env['EOA_ADDRESS'][:16]}...")

    # Test 2: Check MCP server can start
    print("\n  [2/4] Testing MCP server...")
    result = _run(
        [test_python, "-c", "from mcp_server.server import app; print('MCP OK')"],
        capture=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        errors.append("MCP server import failed")
        _fail(f"MCP import failed: {result.stderr.strip()[:100]}")
    else:
        _ok("MCP server module loads")

    # Test 3: Check balance tool
    print("\n  [3/4] Testing get_balance tool...")
    result = _run(
        [
            test_python, "-c",
            "from mcp_server.tools.trading_tools import get_balance; print(get_balance())",
        ],
        capture=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        timeout=30,
    )
    if result.returncode != 0:
        errors.append("get_balance failed")
        _fail(f"get_balance failed: {result.stderr.strip()[:100]}")
    else:
        _ok(f"Balance check works")
        # Parse and show balance
        try:
            import json as json_mod
            data = json_mod.loads(result.stdout.strip())
            pol = data.get("pol", 0)
            usdc = data.get("polymarket_usdc_e", 0) + data.get("native_usdc", 0)
            print(f"       POL: {pol:.4f}, USDC: ${usdc:.2f}")
        except Exception:
            print(f"       {result.stdout.strip()[:80]}")

    # Test 4: Check hooks file
    print("\n  [4/4] Checking hooks...")
    if not HOOKS_DST.exists():
        errors.append("Hooks not configured")
        _fail("settings.local.json not found")
    else:
        _ok("Hooks file exists")

    # Summary
    print("\n" + "-" * 40)
    if errors:
        print(f"  FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print("  All tests passed!")
        print("\n  Ready to run: python -m agent.scheduler --once")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print("  Polymarket Auto Trading Agent - Setup")
    print("  " + "=" * 42)

    if "--approve" in sys.argv:
        run_approve()
        return

    if "--status" in sys.argv:
        show_status()
        return

    if "--test" in sys.argv:
        run_test()
        return

    # Full setup
    check_prerequisites()
    setup_venv()
    address, private_key = setup_wallet()
    setup_env(address, private_key)
    setup_mcp()
    setup_hooks()

    # Final instructions
    env = _read_env()
    wallet_addr = env.get("EOA_ADDRESS", "0x???")

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print("  Next steps:")
    print()
    print("  1. Fund your wallet on the Polygon network:")
    print(f"     Address: {wallet_addr}")
    print("     - Send ~5 POL for gas")
    print("     - Send USDC for trading capital")
    print("     - IMPORTANT: Use Polygon network, NOT Ethereum!")
    print()
    print("  2. After funding, authorize the wallet:")
    print("     python setup.py --approve")
    print()
    print("  3. Start the agent:")
    print("     python -m agent.scheduler        # continuous mode")
    print("     python -m agent.scheduler --once  # single run")
    print()


if __name__ == "__main__":
    main()
