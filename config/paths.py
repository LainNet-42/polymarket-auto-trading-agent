"""
Centralized path configuration for polymarket-auto-trading-agent.
Set WORKSPACE_DIR in .env to relocate. Directories are auto-created on import.
"""
from pathlib import Path
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).parent.parent

_env = dotenv_values(PROJECT_ROOT / ".env")
WORKSPACE = PROJECT_ROOT / _env.get("WORKSPACE_DIR", "workspace")

# Polygon PoS RPC endpoint
POLYGON_RPC_URL = _env.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

# Core state
LEDGER_PATH = WORKSPACE / "ledger.json"

# Agent memory
TRADING_LOG_PATH = WORKSPACE / "note" / "trading_log.csv"

# Execution traces (sub-dirs: YYYY-MM-DD/invoke_N.jsonl)
TRACE_DIR = WORKSPACE / "trace"

# Hibernate state (created on first hibernate call, not on import)
HIBERNATE_CSV_PATH = WORKSPACE / "hibernate.csv"

# System logs
DECISIONS_CSV_PATH = WORKSPACE / "log" / "decisions.csv"
SCHEDULER_LOG_PATH = WORKSPACE / "log" / "scheduler.log"
PORTFOLIO_HISTORY_PATH = WORKSPACE / "log" / "portfolio_history.jsonl"

# Auto-create directory structure on first import
for _d in [WORKSPACE / "note", WORKSPACE / "log", TRACE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# Auto-create trading_log.csv with header + INIT row if missing
if not TRADING_LOG_PATH.exists():
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    TRADING_LOG_PATH.write_text(
        f"invoke_num,date,decision,why\n0,{_now},INIT,workspace initialized\n"
    )
