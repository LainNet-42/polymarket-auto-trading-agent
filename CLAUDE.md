# Polymarket Auto Trading Agent

## Code Structure

| Module | Description | Path |
|--------|-------------|------|
| Config | API endpoints, market slugs | `polymarket/config.py` |
| Data Models | Market, Outcome, PricePoint | `polymarket/models.py` |
| API Client | Gamma + CLOB dual API wrapper | `polymarket/client.py` |
| Data Fetcher | Batch market data fetching | `polymarket/fetcher.py` |
| Analyzer | Market statistics analysis | `polymarket/analyzer.py` |
| Anomaly Detector | Price movement detection | `polymarket/anomaly_detector.py` |

## API Quick Reference

```
Gamma API: https://gamma-api.polymarket.com
  GET /events?slug={slug}

CLOB API: https://clob.polymarket.com
  GET /prices-history?market={token_id}&interval=max&fidelity=60
```

## Hooks (Claude Code)

| Hook | Status | Path | Purpose |
|------|--------|------|---------|
| SessionStart | done | `hooks/session_start.py` | Auto-redeem, sync positions, inject balance context |
| PostToolUse | done | `hooks/post_tool_use.py` | Audit log MCP tool calls to CSV |

Config: `.claude/settings.local.json`

## Workspace

Path controlled by `.env` `WORKSPACE_DIR`, all paths defined in `config/paths.py`.

| File | Purpose |
|------|---------|
| `ledger.json` | Account balance, positions (auto-updated by SessionStart) |
| `note/trading_log.csv` | Agent long-term memory (decision log) |
| `trace/YYYY-MM-DD/invoke_N.jsonl` | Execution traces |
| `log/decisions.csv` | MCP tool call audit |
| `log/scheduler.log` | Scheduler runtime log |

## Credentials

Stored in `.env` (in .gitignore):
- `POLYGON_WALLET_PRIVATE_KEY` - EOA wallet private key (CLOB API creds auto-derived)
- `EOA_ADDRESS` - EOA wallet address
- `WORKSPACE_DIR` - Workspace directory (default: workspace)

## Web UI Dashboard

- Frontend: `web-ui/frontend/` (React/Vite), run `npm run build` after changes
- Backend: `web-ui/backend-py/`, run `uvicorn main:app --host 0.0.0.0 --port 8080`

## Maintenance Notes

- Code should prioritize reusability and extensibility
- No emoji in code
