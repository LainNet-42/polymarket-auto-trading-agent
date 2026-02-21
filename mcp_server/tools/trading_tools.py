"""
Trading tools for Polymarket MCP Server
Handles order placement using py-clob-client
"""
import os
import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.paths import LEDGER_PATH, HIBERNATE_CSV_PATH
from config.risk import MAX_BUY_PRICE, MAX_POSITION_PCT, HIBERNATE_ENABLED, MAX_HIBERNATE_HOURS


def _lookup_market_info(token_id: str) -> dict:
    """Lookup market info (event_slug, neg_risk) from token_id via Gamma API"""
    try:
        resp = requests.get(
            f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}",
            timeout=10
        )
        data = resp.json()
        if data:
            market = data[0]
            event_slug = None
            if market.get('events'):
                event_slug = market['events'][0]['slug']
            return {
                'event_slug': event_slug,
                'neg_risk': market.get('negRisk', False)
            }
    except:
        pass
    return {'event_slug': None, 'neg_risk': False}


def _wait_for_chain_confirmation(client, order_id: str, timeout: int = 60, interval: int = 5) -> dict:
    """
    Poll get_trades() to wait for on-chain confirmation after order matched.

    Args:
        client: CLOB client instance
        order_id: The orderID returned by create_and_post_order
        timeout: Max seconds to wait (default 60)
        interval: Seconds between polls (default 5)

    Returns:
        dict with "confirmed" (bool) and "status" (str)
    """
    from py_clob_client.clob_types import TradeParams

    start = time.time()
    while time.time() - start < timeout:
        try:
            trades = client.get_trades(
                TradeParams(maker_address=client.get_address())
            )
            for t in trades:
                if t.get("taker_order_id") == order_id:
                    status = t.get("status", "")
                    if status == "CONFIRMED":
                        return {"confirmed": True, "status": status, "tx": t.get("transaction_hash")}
                    if status in ("FAILED", "CANCELED"):
                        return {"confirmed": False, "status": status}
                    # Still RETRYING or other intermediate status, keep polling
                    break
        except Exception:
            pass
        time.sleep(interval)

    return {"confirmed": False, "status": "TIMEOUT"}


def _update_ledger_position(token_id: str, side: str, size: float, price: float, event_slug: str = None, outcome: str = None, price_source: str = "fill"):
    """Update ledger.json with new position after successful order"""
    ledger_path = LEDGER_PATH

    try:
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text())
        else:
            ledger = {"balance_usdc": 0, "positions": []}

        if "positions" not in ledger:
            ledger["positions"] = []

        # Find existing position or create new
        existing = None
        for pos in ledger["positions"]:
            if pos.get("token_id") == token_id:
                existing = pos
                break

        if existing:
            # Update existing position
            if side.upper() == "BUY":
                existing["shares"] = existing.get("shares", 0) + size
            else:
                existing["shares"] = existing.get("shares", 0) - size
            existing["last_price"] = price
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            # Update market info if provided
            if event_slug:
                existing["event_slug"] = event_slug
            if outcome:
                existing["outcome"] = outcome
        else:
            # Add new position
            ledger["positions"].append({
                "token_id": token_id,
                "event_slug": event_slug or "Unknown",
                "outcome": outcome or "Unknown",
                "side": side,
                "shares": size if side.upper() == "BUY" else -size,
                "entry_price": price,
                "price_source": price_source,
                "last_price": price,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })

        # Update balance estimate (next session_start syncs from chain)
        cost = size * price
        if side.upper() == "BUY":
            ledger["balance_usdc"] = max(0, ledger.get("balance_usdc", 0) - cost)
        else:
            ledger["balance_usdc"] = ledger.get("balance_usdc", 0) + cost
        ledger["total_value"] = ledger.get("balance_usdc", 0) + sum(
            p.get("shares", 0) * p.get("last_price", p.get("entry_price", 0))
            for p in ledger.get("positions", [])
        )

        ledger_path.write_text(json.dumps(ledger, indent=2))
    except Exception:
        pass  # Don't fail order if ledger update fails


def get_clob_client():
    """Initialize CLOB client with credentials from .env (or POLYMARKET_ENV_FILE override)."""
    from py_clob_client.client import ClobClient

    env_file = os.environ.get("POLYMARKET_ENV_FILE", ".env")
    env_path = Path(__file__).parent.parent.parent / env_file
    config = dotenv_values(str(env_path))

    private_key = config.get("POLYGON_WALLET_PRIVATE_KEY")

    if not private_key:
        raise ValueError("Missing POLYGON_WALLET_PRIVATE_KEY in .env")

    # Use signature_type=0 for EOA wallet (no funder needed)
    client = ClobClient(
        "https://clob.polymarket.com",
        key=private_key,
        chain_id=137,
        signature_type=0
    )

    # Derive and set API credentials
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)

    return client


def get_balance() -> str:
    """Get current wallet balances (USDC.e, Native USDC, POL)"""
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
    from web3 import Web3
    from config.paths import POLYGON_RPC_URL

    result = {
        "polymarket_usdc_e": 0,
        "native_usdc": 0,
        "pol": 0,
        "total_usdc": 0,
        "has_gas": False
    }

    try:
        # Get Polymarket USDC.e balance
        client = get_clob_client()
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        balance_resp = client.get_balance_allowance(params)
        result["polymarket_usdc_e"] = int(balance_resp.get('balance', '0')) / 1_000_000

        # Get on-chain balances
        env_file = os.environ.get("POLYMARKET_ENV_FILE", ".env")
        env_path = Path(__file__).parent.parent.parent / env_file
        config = dotenv_values(str(env_path))
        address = config.get("EOA_ADDRESS")

        if address:
            w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))

            # Native USDC
            usdc_addr = '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'
            usdc_abi = [{'constant':True,'inputs':[{'name':'account','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'type':'function'}]
            usdc = w3.eth.contract(address=usdc_addr, abi=usdc_abi)
            result["native_usdc"] = usdc.functions.balanceOf(address).call() / 1_000_000

            # POL balance
            pol_wei = w3.eth.get_balance(address)
            result["pol"] = float(w3.from_wei(pol_wei, 'ether'))
            result["has_gas"] = result["pol"] > 0.001

        result["total_usdc"] = result["polymarket_usdc_e"] + result["native_usdc"]

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e), **result}, indent=2)


def place_order(
    token_id: str,
    side: str,
    size: float,
    price: float = None,
    event_slug: str = None,
    outcome: str = None
) -> str:
    """
    Place an order on Polymarket.

    Args:
        token_id: The token ID of the outcome to trade
        side: "BUY" or "SELL"
        size: Number of shares (cost = size * price)
        price: Limit price (0-1). If None, uses market price.
        event_slug: Market slug for ledger tracking (optional)
        outcome: Outcome name (YES/NO) for ledger tracking (optional)

    Returns:
        Order result as JSON string
    """
    from py_clob_client.order_builder.constants import BUY, SELL
    from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

    try:
        # Auto-lookup market info (event_slug, neg_risk)
        market_info = _lookup_market_info(token_id)
        if not event_slug:
            event_slug = market_info.get('event_slug')
        neg_risk = market_info.get('neg_risk', False)

        client = get_clob_client()

        # Validate side
        side_enum = BUY if side.upper() == "BUY" else SELL

        # BUY: ALWAYS walk order book to calculate real cost, ignore explicit price.
        # Agent-supplied price is unreliable (neg_risk markets diverge from limit price).
        # SELL: use explicit price if given, otherwise walk book.
        estimated_avg_price = None
        if side_enum == BUY or price is None:
            book = client.get_order_book(token_id)
            # CLOB API sorts: asks HIGH→LOW, bids LOW→HIGH
            # For BUY: walk asks reversed (lowest first = best for buyer)
            # For SELL: walk bids reversed (highest first = best for seller)
            if side_enum == BUY:
                if not book.asks:
                    return json.dumps({"success": False, "error": "No asks in order book"})
                available_shares = 0.0
                total_cost = 0.0
                fills = []
                for ask in reversed(book.asks):
                    ask_price = float(ask.price)
                    ask_size = float(ask.size)
                    needed = size - available_shares
                    if needed <= 0:
                        break
                    take = min(ask_size, needed)
                    fills.append({"price": ask_price, "shares": round(take, 4)})
                    available_shares += take
                    total_cost += take * ask_price

                if available_shares < size:
                    return json.dumps({
                        "success": False,
                        "error": f"Insufficient depth: need {size} shares, only {available_shares:.2f} available",
                        "available_shares": round(available_shares, 2),
                        "estimated_cost": round(total_cost, 4),
                        "fills_preview": fills
                    })

                # Limit price = highest fill level (covers all levels we need)
                price = fills[-1]["price"]
                estimated_avg_price = round(total_cost / size, 6)

                # HARD SAFETY LIMIT: reject if avg price >= MAX_BUY_PRICE
                if estimated_avg_price >= MAX_BUY_PRICE:
                    return json.dumps({
                        "success": False,
                        "error": f"REJECTED: avg price ${estimated_avg_price:.4f} >= ${MAX_BUY_PRICE} limit. "
                                 f"Profit would be <= {(1.0 - estimated_avg_price) * 100:.2f}%. "
                                 f"Binary outcomes pay $1.00 - buying at this price is not profitable.",
                        "estimated_avg_price": estimated_avg_price,
                        "limit_price": price,
                        "max_buy_price": MAX_BUY_PRICE,
                        "fills_preview": fills
                    })

                # POSITION SIZE LIMIT: aggregate by event_slug to catch multi-outcome exposure
                try:
                    ledger_data = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else {}
                    total_value = ledger_data.get("total_value", 0)
                    if total_value > 0:
                        order_cost = size * estimated_avg_price
                        existing_value = 0
                        check_slug = event_slug  # resolved at line 234-235
                        for pos in ledger_data.get("positions", []):
                            if check_slug and pos.get("event_slug") == check_slug:
                                existing_value += pos.get("current_value", 0)
                            elif pos.get("token_id") == token_id:
                                existing_value += pos.get("current_value", 0)
                        new_total_position = existing_value + order_cost
                        position_pct = new_total_position / total_value
                        if position_pct > MAX_POSITION_PCT:
                            return json.dumps({
                                "success": False,
                                "error": f"REJECTED: event position limit exceeded. "
                                         f"order ${order_cost:.2f} + existing event exposure ${existing_value:.2f} = "
                                         f"${new_total_position:.2f} ({position_pct*100:.1f}% of ${total_value:.2f}). "
                                         f"Max: {MAX_POSITION_PCT*100:.0f}%. Event: {check_slug}. "
                                         f"Reminder: be very cautious and careful about multi-outcome markets, "
                                         f"this adds complexity.",
                                "order_cost": round(order_cost, 2),
                                "existing_value": round(existing_value, 2),
                                "total_value": round(total_value, 2),
                                "position_pct": round(position_pct * 100, 1),
                                "max_pct": MAX_POSITION_PCT * 100,
                                "event_slug": check_slug,
                            })
                except Exception:
                    pass  # Don't block trade if ledger read fails
            else:
                if not book.bids:
                    return json.dumps({"success": False, "error": "No bids in order book"})
                available_shares = 0.0
                total_revenue = 0.0
                fills = []
                for bid in reversed(book.bids):
                    bid_price = float(bid.price)
                    bid_size = float(bid.size)
                    needed = size - available_shares
                    if needed <= 0:
                        break
                    take = min(bid_size, needed)
                    fills.append({"price": bid_price, "shares": round(take, 4)})
                    available_shares += take
                    total_revenue += take * bid_price

                if available_shares < size:
                    return json.dumps({
                        "success": False,
                        "error": f"Insufficient depth: need {size} shares, only {available_shares:.2f} available",
                        "available_shares": round(available_shares, 2),
                        "estimated_revenue": round(total_revenue, 4),
                        "fills_preview": fills
                    })

                # Limit price = lowest fill level (covers all levels we need)
                price = fills[-1]["price"]
                estimated_avg_price = round(total_revenue / size, 6)

        # FINAL SAFETY CHECK: reject any BUY with price >= MAX_BUY_PRICE
        # This catches both auto-calculated and explicitly passed prices
        if side_enum == BUY and price >= MAX_BUY_PRICE:
            return json.dumps({
                "success": False,
                "error": f"REJECTED: limit price ${price:.4f} >= ${MAX_BUY_PRICE} hard limit. "
                         f"Binary outcomes pay $1.00 - buying at this price is not profitable.",
                "price": price,
                "max_buy_price": MAX_BUY_PRICE,
                "estimated_avg_price": estimated_avg_price,
            })

        # Create order args
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side_enum
        )

        # Options based on market type
        options = PartialCreateOrderOptions(neg_risk=neg_risk)

        # Create and post order
        result = client.create_and_post_order(order_args, options)

        api_status = result.get("status", "unknown")
        order_id = result.get("orderID")
        chain_status = None
        tx_hash = None

        # Parse actual fill data from CLOB response
        taking_raw = result.get("takingAmount") or result.get("taking_amount")
        making_raw = result.get("makingAmount") or result.get("making_amount")
        actual_shares = None
        actual_cost = None
        actual_avg_price = None

        if taking_raw and making_raw:
            # CLOB may return raw token ints ("12870000") or decimal strings ("12.87")
            taking_val = float(taking_raw)
            making_val = float(making_raw)
            if taking_val > 10_000:
                taking_val = taking_val / 1_000_000
            if making_val > 10_000:
                making_val = making_val / 1_000_000
            # takingAmount = what taker receives from the market
            # makingAmount = what taker provides to the market
            # BUY: taker receives shares (taking), provides USDC (making)
            # SELL: taker receives USDC (taking), provides shares (making)
            if side.upper() == "BUY":
                actual_shares = taking_val
                actual_cost = making_val
            else:
                actual_shares = making_val
                actual_cost = taking_val
            if actual_shares > 0:
                actual_avg_price = round(actual_cost / actual_shares, 6)

        if api_status == "matched" and order_id:
            # Wait for on-chain confirmation (up to 60s)
            confirmation = _wait_for_chain_confirmation(client, order_id)
            chain_status = confirmation["status"]
            tx_hash = confirmation.get("tx")

            if confirmation["confirmed"]:
                ledger_size = actual_shares if actual_shares else size
                ledger_price = actual_avg_price if actual_avg_price else price
                # Flag if we're using limit price as fallback (unreliable for neg_risk)
                price_source = "fill" if actual_avg_price else "limit_fallback"
                _update_ledger_position(
                    token_id, side, ledger_size, ledger_price,
                    event_slug, outcome, price_source=price_source
                )

        filled = chain_status == "CONFIRMED"

        # POST-FILL SAFETY CHECK: warn if BUY actual price >= $1.00 (guaranteed loss)
        # Only applies to BUY. For SELL, high avg_price means good exit price.
        post_fill_warning = None
        if filled and side.upper() == "BUY" and actual_avg_price and actual_avg_price >= 1.0:
            post_fill_warning = (
                f"WARNING: LOSS DETECTED. actual_avg_price=${actual_avg_price:.4f} >= $1.00. "
                f"You paid ${actual_cost:.2f} for {actual_shares:.2f} shares that pay max $1.00 each. "
                f"Guaranteed loss: ${actual_cost - actual_shares:.2f}. "
                f"This likely happened on a neg_risk multi-outcome market."
            )

        return json.dumps({
            "success": True,
            "filled": filled,
            "post_fill_warning": post_fill_warning,
            "api_status": api_status,
            "chain_status": chain_status or "N/A",
            "order_id": order_id,
            "tx_hash": tx_hash,
            "side": side,
            # Order parameters
            "requested_size": size,
            "limit_price": price,
            "estimated_avg_price": estimated_avg_price,
            # Actual fill data from CLOB
            "actual_shares": actual_shares,
            "actual_cost": actual_cost,
            "actual_avg_price": actual_avg_price,
            "token_id": token_id,
            "event_slug": event_slug,
            "outcome": outcome,
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "side": side,
            "size": size,
            "price": price,
            "token_id": token_id
        }, indent=2)


def get_open_orders() -> str:
    """Get all open orders"""
    try:
        client = get_clob_client()
        orders = client.get_orders()

        return json.dumps({
            "count": len(orders) if orders else 0,
            "orders": orders
        }, indent=2)
    except Exception as e:
        return f"Error getting orders: {str(e)}"


def cancel_order(order_id: str) -> str:
    """Cancel an order by ID"""
    try:
        client = get_clob_client()
        result = client.cancel(order_id)

        return json.dumps({
            "success": True,
            "order_id": order_id,
            "result": result
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "order_id": order_id
        }, indent=2)


def hibernate(hours: float, d_mail: str = "", invoke_num: int = None) -> str:
    """
    Enter hibernation mode. Scheduler will skip invocations for the specified hours.
    Like Steins;Gate D-mail: send a message to your future self across time.

    Args:
        hours: How many hours to sleep (min 1 minute, max 24)
        d_mail: Message to your future self - what you care about, what to watch for,
                what's on your mind. NOT the same as decision "why" in trading_log.
        invoke_num: Current invocation number (from prompt header)

    Returns:
        Confirmation or error as JSON string
    """
    import csv

    if not HIBERNATE_ENABLED:
        return json.dumps({
            "success": False,
            "error": "Hibernate mode is disabled in config. Set HIBERNATE_ENABLED=True to use."
        })

    # Validate hours
    if not isinstance(hours, (int, float)):
        return json.dumps({
            "success": False,
            "error": f"hours must be a number, got {type(hours).__name__}"
        })

    min_hours = 0.5
    if hours < min_hours:
        return json.dumps({
            "success": False,
            "error": f"hours must be >= {min_hours:.4f} (1 minute minimum). Got {hours}"
        })

    if hours > MAX_HIBERNATE_HOURS:
        return json.dumps({
            "success": False,
            "error": f"hours must be <= {MAX_HIBERNATE_HOURS}. Got {hours}"
        })

    # Validate d_mail length
    if len(d_mail) > 500:
        return json.dumps({
            "success": False,
            "error": f"d_mail too long: {len(d_mail)} chars, max 500."
        })

    now = datetime.now(timezone.utc)
    wake_dt = now + timedelta(hours=hours)

    # Write to hibernate.csv (create with header if not exists)
    csv_path = HIBERNATE_CSV_PATH
    write_header = not csv_path.exists()

    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["timestamp", "wake_time", "hours", "invoke_num", "d_mail", "source"])
            writer.writerow([now.isoformat(), wake_dt.isoformat(), round(hours, 4), invoke_num or "", d_mail, "tool"])

        return json.dumps({
            "success": True,
            "hibernate_until": wake_dt.isoformat(),
            "hours_sleeping": round(hours, 1),
            "d_mail": d_mail if d_mail else "(none)",
            "message": f"Hibernating for {hours}h. Will wake at {wake_dt.strftime('%Y-%m-%d %H:%M')} UTC."
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to write hibernate.csv: {e}"
        })
