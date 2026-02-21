"""
Polymarket Dashboard API - Read-only FastAPI server.
Serves workspace data for the web dashboard.
WebSocket pushes real-time position prices every 10s.
"""
import asyncio
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Add project root so we can import config
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values
from config.paths import WORKSPACE
from data_reader import (
    read_ledger,
    read_trading_log,
    read_portfolio_history,
    list_traces,
    read_trace,
)
from backfill import backfill_from_trades

_env = dotenv_values(PROJECT_ROOT / ".env")
EOA_ADDRESS = _env.get("EOA_ADDRESS", "")

app = FastAPI(title="Polymarket Dashboard", version="1.0.0")

# CORS for development (Vite on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------- Image cache ----------
_image_cache: dict[str, str] = {}

# ---------- REST endpoints ----------


@app.get("/api/status")
def get_status():
    """Current account state from ledger.json."""
    ledger = read_ledger(WORKSPACE)
    balance = ledger.get("balance_usdc", 0)
    positions_value = sum(p.get("current_value", 0) for p in ledger.get("positions", []))
    return {
        "balance_usdc": balance,
        "positions_value": round(positions_value, 2),
        "total_value": round(balance + positions_value, 2),
        "num_positions": len(ledger.get("positions", [])),
        "last_updated": ledger.get("last_updated", ""),
        "positions": ledger.get("positions", []),
    }


@app.get("/api/portfolio-history")
def get_portfolio_history():
    """Portfolio value over time for chart. Merges backfill + real snapshots."""
    ledger = read_ledger(WORKSPACE)
    trades = ledger.get("trades", [])
    current_total = ledger.get("total_value", 0)

    backfill = backfill_from_trades(trades, current_total=0)
    real = read_portfolio_history(WORKSPACE)

    # Only use backfill for timestamps before the first real snapshot
    if real:
        first_real_ts = real[0].get("timestamp", "")
        backfill = [p for p in backfill if p.get("timestamp", "") < first_real_ts]

    combined = backfill + real
    combined.sort(key=lambda p: p.get("timestamp", ""))
    return combined


@app.get("/api/trading-log")
def get_trading_log():
    """Agent decision history from trading_log.csv."""
    return read_trading_log(WORKSPACE)


@app.get("/api/trades")
def get_trades():
    """Trade history from ledger.json."""
    ledger = read_ledger(WORKSPACE)
    return ledger.get("trades", [])


@app.get("/api/trace/list")
def get_trace_list():
    """List all invoke trace summaries."""
    return list_traces(WORKSPACE)


@app.get("/api/trace/{invoke_num}")
def get_trace_detail(invoke_num: int):
    """Full trace for a specific invoke."""
    messages = read_trace(WORKSPACE, invoke_num)
    if messages is None:
        raise HTTPException(status_code=404, detail=f"Trace for invoke #{invoke_num} not found")
    return messages


@app.get("/api/wallet")
def get_wallet():
    """Return wallet address for Polygonscan link."""
    return {"address": EOA_ADDRESS}


@app.get("/api/hibernate")
def get_hibernate():
    """Return latest hibernate entry from hibernate.csv with full d_mail data."""
    import csv
    from datetime import datetime, timezone

    hibernate_file = WORKSPACE / "hibernate.csv"
    empty = {"hibernating": False, "wake_time": None, "invoke_num": None,
             "d_mail": None, "timestamp": None, "source": None}
    if not hibernate_file.exists():
        return empty
    try:
        with open(hibernate_file, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return empty
        latest = rows[-1]
        wake_time = latest.get("wake_time", "")
        now = datetime.now(timezone.utc)
        try:
            wake_dt = datetime.fromisoformat(wake_time)
            if wake_dt.tzinfo is None:
                wake_dt = wake_dt.replace(tzinfo=timezone.utc)
            is_hibernating = now < wake_dt
        except (ValueError, TypeError):
            is_hibernating = False
        return {
            "hibernating": is_hibernating,
            "wake_time": wake_time,
            "invoke_num": int(latest.get("invoke_num", 0)),
            "hours": float(latest.get("hours", 0)),
            "d_mail": latest.get("d_mail", ""),
            "timestamp": latest.get("timestamp", ""),
            "source": latest.get("source", ""),
        }
    except Exception:
        return empty


@app.get("/api/config")
def get_config():
    """Return risk management parameters from config/risk.py."""
    from config.risk import (
        MAX_BUY_PRICE,
        MAX_POSITION_PCT,
        STOP_LOSS_DROP_PCT,
        HIBERNATE_ENABLED,
        MAX_HIBERNATE_HOURS,
        DEFAULT_WAKE_INTERVAL_HOURS,
    )
    return {
        "risk": [
            {"key": "MAX_BUY_PRICE", "value": MAX_BUY_PRICE, "desc": "Reject BUY at or above this price. Binary pays $1.00, so >= $0.99 means <= 1% profit."},
            {"key": "MAX_POSITION_PCT", "value": MAX_POSITION_PCT, "desc": "Reject BUY if position exceeds this % of total value. Prevents over-concentration."},
            {"key": "STOP_LOSS_DROP_PCT", "value": STOP_LOSS_DROP_PCT, "desc": "Auto-sell if best bid drops this % below entry price. Limits losses."},
        ],
        "hibernate": [
            {"key": "HIBERNATE_ENABLED", "value": HIBERNATE_ENABLED, "desc": "Allow agent to set its own wake time and leave a D-Mail."},
            {"key": "MAX_HIBERNATE_HOURS", "value": MAX_HIBERNATE_HOURS, "desc": "Maximum sleep duration the agent can set."},
            {"key": "DEFAULT_WAKE_INTERVAL", "value": DEFAULT_WAKE_INTERVAL_HOURS, "desc": "Fallback interval if agent did not call hibernate()."},
        ],
    }


@app.get("/api/market-image/{slug}")
async def get_market_image(slug: str):
    """Proxy market image URL from Gamma API. Cached."""
    if slug in _image_cache:
        return {"image": _image_cache[slug]}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://gamma-api.polymarket.com/events?slug={slug}"
            )
            if resp.status_code == 200:
                events = resp.json()
                if events and len(events) > 0:
                    image_url = events[0].get("image", "")
                    _image_cache[slug] = image_url
                    return {"image": image_url}
    except Exception:
        pass

    return {"image": ""}


# ---------- WebSocket: real-time price push ----------

_ws_clients: list[WebSocket] = []


async def _fetch_live_prices() -> dict[str, Any] | None:
    """Fetch current prices for all positions from CLOB API."""
    try:
        ledger = read_ledger(WORKSPACE)
        positions = ledger.get("positions", [])
        if not positions:
            return None

        updated_positions = []
        total_positions_value = 0.0

        async with httpx.AsyncClient(timeout=8) as client:
            for pos in positions:
                token_id = pos.get("token_id", "")
                if not token_id:
                    updated_positions.append(pos)
                    total_positions_value += pos.get("current_value", 0)
                    continue

                try:
                    # Redeemable positions are worth $1.00/share, CLOB returns 0
                    if pos.get("redeemable"):
                        live_price = 1.0
                    else:
                        resp = await client.get(
                            f"https://clob.polymarket.com/price",
                            params={"token_id": token_id, "side": "sell"},
                        )
                        if resp.status_code == 200:
                            price_data = resp.json()
                            live_price = float(price_data.get("price", 0))
                        else:
                            live_price = 0

                    if live_price > 0:
                        shares = pos.get("shares", 0)
                        entry_price = pos.get("avg_price", pos.get("entry_price", 0))

                        current_value = round(shares * live_price, 4)
                        pnl = round(current_value - shares * entry_price, 4)

                        updated_pos = {**pos, "current_value": current_value, "pnl": pnl, "live_price": live_price}
                        updated_positions.append(updated_pos)
                        total_positions_value += current_value
                    else:
                        updated_positions.append(pos)
                        total_positions_value += pos.get("current_value", 0)
                except Exception:
                    updated_positions.append(pos)
                    total_positions_value += pos.get("current_value", 0)

        balance = ledger.get("balance_usdc", 0)
        total_value = round(balance + total_positions_value, 2)

        from datetime import datetime, timezone
        return {
            "type": "price_update",
            "balance_usdc": balance,
            "positions_value": round(total_positions_value, 2),
            "total_value": total_value,
            "num_positions": len(updated_positions),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "positions": updated_positions,
        }
    except Exception:
        return None


async def _price_push_loop():
    """Background loop: fetch prices every 10s and push to all WS clients."""
    while True:
        await asyncio.sleep(10)
        if not _ws_clients:
            continue

        data = await _fetch_live_prices()
        if data is None:
            continue

        message = json.dumps(data)
        disconnected = []
        for ws in _ws_clients:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            if ws in _ws_clients:
                _ws_clients.remove(ws)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_price_push_loop())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        # Send initial data immediately
        data = await _fetch_live_prices()
        if data:
            await ws.send_text(json.dumps(data))

        # Keep connection alive, listen for pings
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ---------- Frontend static files (catch-all, must be last) ----------

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    """Serve frontend static files. Catch-all after /api routes."""
    if not DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")

    file_path = DIST_DIR / full_path
    if file_path.is_file():
        media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return FileResponse(str(file_path), media_type=media_type)

    index_path = DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path), media_type="text/html")

    raise HTTPException(status_code=404, detail="Not found")
