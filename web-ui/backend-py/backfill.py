"""
Reconstruct portfolio value history from trades in ledger.json.
Used as fallback when portfolio_history.jsonl doesn't exist yet.
Interpolates hourly between trade events for smoother charts.
"""
import os
from datetime import datetime, timezone, timedelta


INITIAL_DEPOSIT = float(os.environ.get("INITIAL_DEPOSIT", "100"))  # Starting capital
INTERPOLATION_INTERVAL = timedelta(hours=1)


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    # Handle both +00:00 and Z formats
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def backfill_from_trades(trades: list[dict], current_total: float = 0) -> list[dict]:
    """
    Build approximate portfolio value timeline from trade history.
    Interpolates hourly between trade events for a smoother chart.

    Returns list of {timestamp, total_value} sorted oldest first.
    """
    if not trades:
        return []

    # Sort oldest first
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", ""))

    cash = INITIAL_DEPOSIT
    positions_cost = 0.0
    raw_points: list[tuple[datetime, float]] = []

    # Initial point
    first_dt = _parse_ts(sorted_trades[0].get("timestamp", ""))
    raw_points.append((first_dt, INITIAL_DEPOSIT))

    for trade in sorted_trades:
        side = trade.get("side", "").upper()
        size = float(trade.get("size", 0))
        price = float(trade.get("price", 0))
        dt = _parse_ts(trade.get("timestamp", ""))

        if side == "BUY":
            cost = size * price
            cash -= cost
            positions_cost += cost
        elif side in ("SELL", "AUTO_SELL"):
            revenue = size * price
            cash += revenue
            positions_cost -= size * price
            positions_cost = max(0, positions_cost)
        elif side == "REDEEM":
            payout = size * price
            cash += payout
            positions_cost -= size * 0.95
            positions_cost = max(0, positions_cost)
        elif side == "DEPOSIT":
            cash += size * price

        total = cash + positions_cost
        raw_points.append((dt, round(total, 2)))

    # Add current total as final point
    if current_total > 0:
        raw_points.append((datetime.now(timezone.utc), round(current_total, 2)))

    # Interpolate hourly between raw points for smoother chart
    history: list[dict] = []
    for i in range(len(raw_points) - 1):
        t0, v0 = raw_points[i]
        t1, v1 = raw_points[i + 1]

        history.append({"timestamp": t0.isoformat(), "total_value": v0})

        # Fill hourly gaps with linear interpolation
        gap = (t1 - t0).total_seconds()
        if gap > INTERPOLATION_INTERVAL.total_seconds() * 1.5:
            steps = int(gap / INTERPOLATION_INTERVAL.total_seconds())
            steps = min(steps, 200)  # cap to prevent huge output
            for s in range(1, steps):
                frac = s / steps
                interp_t = t0 + timedelta(seconds=gap * frac)
                interp_v = round(v0 + (v1 - v0) * frac, 2)
                history.append({
                    "timestamp": interp_t.isoformat(),
                    "total_value": interp_v,
                })

    # Add last point
    if raw_points:
        last_dt, last_val = raw_points[-1]
        history.append({"timestamp": last_dt.isoformat(), "total_value": last_val})

    return history
