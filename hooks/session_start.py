#!/usr/bin/env python3
"""
SessionStart Hook - Auto redeem, sync positions, fetch balance, inject into context.

Flow (serial):
1. auto_redeem() - Redeem all settled positions -> USDC
2. sync_positions() - Sync real positions from API
3. get_real_balance() - Fetch USDC balance
4. Update ledger.json
5. Output to stdout (injected into Agent context)
"""
import json
import csv
import requests
from pathlib import Path
from datetime import datetime, timezone

def get_env_config():
    """Load environment config."""
    from dotenv import dotenv_values
    env_path = Path(__file__).parent.parent / ".env"
    return dotenv_values(str(env_path))


def get_clob_client(config):
    """Create CLOB client."""
    from py_clob_client.client import ClobClient

    private_key = config.get("POLYGON_WALLET_PRIVATE_KEY")
    if not private_key:
        raise ValueError("Missing POLYGON_WALLET_PRIVATE_KEY in .env")

    client = ClobClient(
        "https://clob.polymarket.com",
        key=private_key,
        chain_id=137,
        signature_type=0
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


def _send_tx_with_retry(w3, signed_tx, max_retries=2, delay=10, timeout=120):
    """Send tx with retry on rate limit / transient RPC errors."""
    import time
    for attempt in range(max_retries + 1):
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return tx_hash, receipt
        except Exception as e:
            msg = str(e).lower()
            # nonce too low = nonce was used, but prior tx could have FAILED
            if "nonce too low" in msg:
                print(f"  Nonce too low - prior tx used this nonce (may have failed), treating as failure")
                return None, type("Receipt", (), {"status": 0})()
            if attempt < max_retries and ("rate limit" in msg or "too many" in msg):
                print(f"  TX rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            raise


def auto_swap_usdc(config):
    """
    Auto swap native USDC -> USDC.e via Uniswap V3.
    Polymarket CLOB only accepts USDC.e, so convert any native USDC on startup.
    Returns: dict with swap results or skip reason.
    """
    try:
        from web3 import Web3
        from eth_account import Account
        from config.paths import POLYGON_RPC_URL
        import time as _time

        private_key = config.get("POLYGON_WALLET_PRIVATE_KEY")
        if not private_key:
            return {"skipped": True, "reason": "Missing private key"}

        NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
        USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        SWAP_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

        w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
        account = Account.from_key(private_key)
        address = account.address

        native_usdc = w3.to_checksum_address(NATIVE_USDC)
        usdc_e = w3.to_checksum_address(USDC_E)
        router_addr = w3.to_checksum_address(SWAP_ROUTER)

        # Check native USDC balance
        erc20_abi = [
            {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
            {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
        ]
        usdc_contract = w3.eth.contract(address=native_usdc, abi=erc20_abi)

        balance_raw = usdc_contract.functions.balanceOf(address).call()
        balance = balance_raw / 1_000_000

        if balance < 0.10:
            return {"skipped": True, "reason": f"Native USDC too low: ${balance:.2f}"}

        nonce = w3.eth.get_transaction_count(address)
        gas_price = w3.eth.gas_price

        # Approve router if needed
        allowance = usdc_contract.functions.allowance(address, router_addr).call()
        if allowance < balance_raw:
            approve_tx = usdc_contract.functions.approve(router_addr, 2**256 - 1).build_transaction({
                "from": address,
                "nonce": nonce,
                "gas": 60000,
                "gasPrice": gas_price,
                "chainId": 137,
            })
            signed = account.sign_transaction(approve_tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            nonce += 1

        # Swap via Uniswap V3 exactInputSingle
        router_abi = [{
            "inputs": [{"components": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "recipient", "type": "address"},
                {"name": "deadline", "type": "uint256"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMinimum", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"},
            ], "name": "params", "type": "tuple"}],
            "name": "exactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "stateMutability": "payable",
            "type": "function",
        }]
        router = w3.eth.contract(address=router_addr, abi=router_abi)

        min_out = int(balance_raw * 0.99)  # 1% slippage
        deadline = int(_time.time()) + 300
        swap_params = (native_usdc, usdc_e, 100, address, deadline, balance_raw, min_out, 0)

        swap_tx = router.functions.exactInputSingle(swap_params).build_transaction({
            "from": address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": gas_price,
            "chainId": 137,
            "value": 0,
        })
        signed = account.sign_transaction(swap_tx)
        tx_hash, receipt = _send_tx_with_retry(w3, signed, timeout=60)

        if receipt is None:
            # nonce-too-low: prior tx succeeded, treat as success
            return {"success": True, "amount": balance, "tx": "nonce-confirmed", "note": "prior tx already confirmed"}
        if receipt.status == 1:
            return {
                "success": True,
                "amount": balance,
                "tx": tx_hash.hex(),
            }
        else:
            return {"error": f"Swap tx reverted: {tx_hash.hex()}"}

    except Exception as e:
        return {"error": str(e)}


def auto_redeem(config):
    """
    Auto redeem all settled positions via direct contract calls.
    Supports both neg_risk (NegRiskAdapter) and normal (CTF) markets.
    Returns: dict with redeem results or error.
    """
    try:
        from web3 import Web3
        from eth_account import Account
        from config.paths import POLYGON_RPC_URL

        private_key = config.get("POLYGON_WALLET_PRIVATE_KEY")
        if not private_key:
            return {"skipped": True, "reason": "Missing private key"}

        # Contract addresses
        CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
        USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

        # ABIs
        CTF_ABI = [
            {
                "name": "setApprovalForAll",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "operator", "type": "address"},
                    {"name": "approved", "type": "bool"}
                ],
                "outputs": []
            },
            {
                "name": "isApprovedForAll",
                "type": "function",
                "stateMutability": "view",
                "inputs": [
                    {"name": "account", "type": "address"},
                    {"name": "operator", "type": "address"}
                ],
                "outputs": [{"name": "", "type": "bool"}]
            },
            {
                "name": "redeemPositions",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "collateralToken", "type": "address"},
                    {"name": "parentCollectionId", "type": "bytes32"},
                    {"name": "conditionId", "type": "bytes32"},
                    {"name": "indexSets", "type": "uint256[]"}
                ],
                "outputs": []
            }
        ]
        NEG_RISK_ABI = [{
            "name": "redeemPositions",
            "type": "function",
            "stateMutability": "nonpayable",
            "inputs": [
                {"name": "_conditionId", "type": "bytes32"},
                {"name": "_amounts", "type": "uint256[]"}
            ],
            "outputs": []
        }]

        # Setup web3
        w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
        account = Account.from_key(private_key)
        ctf = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
        neg_risk_adapter = w3.eth.contract(address=NEG_RISK_ADAPTER, abi=NEG_RISK_ABI)

        # Fetch redeemable positions from Data API
        resp = requests.get(
            "https://data-api.polymarket.com/positions",
            params={"user": account.address, "sizeThreshold": 0.01},
            timeout=10
        )
        positions = resp.json() if resp.status_code == 200 else []

        # Filter redeemable positions
        redeemable = [p for p in positions if p.get("redeemable")]
        if not redeemable:
            return {"skipped": True, "reason": "No redeemable positions"}

        # Group by condition and neg_risk type, keep position details
        neg_risk_positions = {}  # conditionId -> {0: amount, 1: amount, "details": [...]}
        normal_positions = {}    # conditionId -> {"details": [...]}

        for p in redeemable:
            condition_id = p.get("conditionId")
            if not condition_id:
                continue

            detail = {
                "token_id": str(p.get("asset", "")),
                "event_slug": p.get("eventSlug"),
                "outcome": p.get("outcome"),
                "size": p.get("size", 0),
                "pnl": p.get("cashPnl", 0),
            }

            if p.get("negativeRisk"):
                idx = p.get("outcomeIndex", 0)
                size = p.get("size", 0)
                if condition_id not in neg_risk_positions:
                    neg_risk_positions[condition_id] = {0: 0, 1: 0, "details": []}
                neg_risk_positions[condition_id][idx] += size
                neg_risk_positions[condition_id]["details"].append(detail)
            else:
                if condition_id not in normal_positions:
                    normal_positions[condition_id] = {"details": []}
                normal_positions[condition_id]["details"].append(detail)

        redeemed = []
        nonce = w3.eth.get_transaction_count(account.address)
        gas_price = int(w3.eth.gas_price * 1.5)

        # Ensure NegRiskAdapter is approved (if needed)
        if neg_risk_positions:
            is_approved = ctf.functions.isApprovedForAll(account.address, NEG_RISK_ADAPTER).call()
            if not is_approved:
                tx = ctf.functions.setApprovalForAll(NEG_RISK_ADAPTER, True).build_transaction({
                    "from": account.address,
                    "nonce": nonce,
                    "gas": 100000,
                    "gasPrice": gas_price,
                    "chainId": 137
                })
                signed = account.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                nonce += 1

        # Redeem neg_risk positions
        for condition_id, data in neg_risk_positions.items():
            amounts_list = [int(data[0] * 1e6), int(data[1] * 1e6)]
            call_args = (bytes.fromhex(condition_id[2:]), amounts_list)
            # Estimate gas dynamically - neg_risk redeems need more than 250k
            try:
                estimated_gas = neg_risk_adapter.functions.redeemPositions(
                    *call_args
                ).estimate_gas({"from": account.address})
                gas_limit = int(estimated_gas * 1.3)  # 30% buffer
            except Exception:
                gas_limit = 500000  # safe fallback
            tx = neg_risk_adapter.functions.redeemPositions(
                *call_args
            ).build_transaction({
                "from": account.address,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": 137
            })
            signed = account.sign_transaction(tx)
            tx_hash, receipt = _send_tx_with_retry(w3, signed)
            confirmed = receipt.status == 1 if receipt else False
            if confirmed:
                for detail in data["details"]:
                    redeemed.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "token_id": detail["token_id"],
                        "event_slug": detail["event_slug"],
                        "outcome": detail["outcome"],
                        "shares": detail["size"],
                        "pnl": detail["pnl"],
                        "tx": tx_hash.hex() if tx_hash else "nonce-confirmed",
                    })
            nonce += 1

        # Redeem normal positions
        for condition_id, data in normal_positions.items():
            call_args = (USDC_E, bytes(32), bytes.fromhex(condition_id[2:]), [1, 2])
            try:
                estimated_gas = ctf.functions.redeemPositions(
                    *call_args
                ).estimate_gas({"from": account.address})
                gas_limit = int(estimated_gas * 1.3)
            except Exception:
                gas_limit = 300000
            tx = ctf.functions.redeemPositions(
                *call_args
            ).build_transaction({
                "from": account.address,
                "nonce": nonce,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": 137
            })
            signed = account.sign_transaction(tx)
            tx_hash, receipt = _send_tx_with_retry(w3, signed)
            confirmed = receipt.status == 1 if receipt else False
            if confirmed:
                for detail in data["details"]:
                    redeemed.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "token_id": detail["token_id"],
                        "event_slug": detail["event_slug"],
                        "outcome": detail["outcome"],
                        "shares": detail["size"],
                        "pnl": detail["pnl"],
                        "tx": tx_hash.hex() if tx_hash else "nonce-confirmed",
                    })
            nonce += 1

        return {"success": True, "redeemed": redeemed}

    except Exception as e:
        return {"error": str(e)}


def auto_stop_loss(config, ledger):
    """
    Auto sell positions that dropped >= STOP_LOSS_DROP_PCT from entry price.
    Uses CLOB order book to sell at best bid (market sell).
    Runs after sync_positions so entry_price and shares are up to date.

    Returns: list of AUTO_SELL action dicts (empty if nothing triggered).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.risk import STOP_LOSS_DROP_PCT

    actions = []
    positions = ledger.get("positions", [])
    if not positions:
        return actions

    for pos in positions:
        entry_price = pos.get("entry_price")
        shares = pos.get("shares", 0)
        token_id = pos.get("token_id")

        if not entry_price or not token_id or shares <= 0:
            continue

        # Get current best bid from CLOB order book
        try:
            resp = requests.get(
                f"https://clob.polymarket.com/book?token_id={token_id}",
                timeout=5
            )
            book = resp.json()
            bids = book.get("bids", [])
            if not bids:
                continue
            # CLOB API: bids sorted LOW->HIGH, best bid = last element
            best_bid = float(bids[-1]["price"])
        except Exception:
            continue

        # Check if dropped >= threshold from entry
        drop_pct = (entry_price - best_bid) / entry_price
        if drop_pct < STOP_LOSS_DROP_PCT:
            continue

        # Execute market sell at best bid
        try:
            from py_clob_client.order_builder.constants import SELL
            from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

            client = get_clob_client(config)

            # Lookup neg_risk for this token
            neg_risk = False
            try:
                market_resp = requests.get(
                    f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}",
                    timeout=10
                )
                market_data = market_resp.json()
                if market_data:
                    neg_risk = market_data[0].get("negRisk", False)
            except Exception:
                pass

            order_args = OrderArgs(
                token_id=token_id,
                price=best_bid,
                size=shares,
                side=SELL
            )
            options = PartialCreateOrderOptions(neg_risk=neg_risk)
            result = client.create_and_post_order(order_args, options)

            if result.get("status") == "matched":
                actions.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "side": "STOP_LOSS",
                    "size": shares,
                    "price": best_bid,
                    "outcome": pos.get("outcome", "?"),
                    "event_slug": pos.get("event_slug", "?"),
                    "token_id": token_id,
                    "entry_price": entry_price,
                    "drop_pct": round(drop_pct * 100, 1),
                    "order_id": result.get("orderID"),
                })
        except Exception:
            continue

    return actions


def sync_positions(config, ledger, redeemed_token_ids=None):
    """
    Sync positions from Data API.
    Updates ledger with real-time data (shares, current_value, pnl, redeemable)
    but PRESERVES our own entry_price from actual order fills.

    redeemed_token_ids: set of token_ids just redeemed this session.
    Excluded from positions since their value is already in balance.

    The API's avgPrice is not reliable for cost basis (especially for neg_risk
    markets where CLOB fill price can exceed the displayed ask price).
    """
    redeemed_token_ids = redeemed_token_ids or set()
    try:
        eoa_address = config.get("EOA_ADDRESS")
        if not eoa_address:
            # Derive from private key
            from eth_account import Account
            private_key = config.get("POLYGON_WALLET_PRIVATE_KEY")
            if private_key:
                account = Account.from_key(private_key)
                eoa_address = account.address

        if not eoa_address:
            return ledger, "No EOA address"

        # Save our entry_prices before sync (keyed by token_id)
        # These come from actual CLOB fills in place_order, not the API
        saved_entry_prices = {}
        for pos in ledger.get("positions", []):
            tid = pos.get("token_id")
            if tid:
                ep = pos.get("entry_price") or pos.get("avg_price")
                if ep:
                    saved_entry_prices[tid] = ep

        # Fetch positions from Data API
        resp = requests.get(
            "https://data-api.polymarket.com/positions",
            params={"user": eoa_address, "sizeThreshold": 0.01},
            timeout=10
        )
        positions = resp.json() if resp.status_code == 200 else []

        # Detect positions that vanished (redeemed elsewhere, expired, or hook crashed before write)
        previous = {str(p.get("token_id")): p for p in ledger.get("positions", [])}
        current_ids = {str(p.get("asset")) for p in positions}

        for tid, prev in previous.items():
            if tid not in current_ids and str(tid) not in redeemed_token_ids:
                # Position disappeared - check if we already have a record for it
                has_record = any(
                    str(t.get("token_id", "")) == tid
                    and t.get("side") in ("REDEEM", "SELL", "STOP_LOSS", "RESOLVED")
                    for t in ledger.get("trades", [])
                )
                if not has_record:
                    ledger.setdefault("trades", []).insert(0, {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "side": "RESOLVED",
                        "size": prev.get("shares", 0),
                        "price": 0,
                        "outcome": prev.get("outcome", "?"),
                        "event_slug": prev.get("event_slug", "?"),
                        "token_id": tid,
                        "note": "position vanished from API without prior record",
                    })

        # Rebuild positions with API real-time data + our preserved entry_price
        ledger["positions"] = []
        for p in positions:
            event_slug = p.get("eventSlug")
            token_id = p.get("asset")

            # Skip positions that were just redeemed (value already in balance)
            if str(token_id) in redeemed_token_ids:
                continue
            # Get detailed end date from Gamma API (includes time)
            end_date = get_market_end_date(event_slug) if event_slug else p.get("endDate")

            # Use our saved entry_price if available, otherwise fall back to API avgPrice
            entry_price = saved_entry_prices.get(token_id, p.get("avgPrice", 0))

            ledger["positions"].append({
                "token_id": token_id,
                "event_slug": event_slug,
                "market_slug": p.get("slug"),
                "outcome": p.get("outcome"),
                "shares": p.get("size", 0),
                "entry_price": entry_price,
                "avg_price": p.get("avgPrice", 0),
                "current_value": p.get("currentValue", 0),
                "pnl": p.get("cashPnl", 0),
                "redeemable": p.get("redeemable", False),
                "end_date": end_date,
            })

        return ledger, None

    except Exception as e:
        return ledger, str(e)


def get_real_balance(client):
    """Fetch real balance from Polymarket API."""
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        balance_resp = client.get_balance_allowance(params)

        balance_raw = int(balance_resp.get('balance', '0'))
        balance_usdc = balance_raw / 1_000_000

        return balance_usdc, None

    except Exception as e:
        return None, str(e)


def lookup_event_slug(token_id):
    """Lookup event_slug from token_id via Gamma API."""
    try:
        resp = requests.get(
            f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}",
            timeout=10
        )
        data = resp.json()
        if data and data[0].get("events"):
            return data[0]["events"][0]["slug"]
    except:
        pass
    return None


def get_market_end_date(event_slug):
    """Get detailed end date from Gamma API (returns full ISO timestamp)."""
    try:
        resp = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={"slug": event_slug},
            timeout=10
        )
        data = resp.json()
        if data:
            return data[0].get("endDate")  # e.g. "2026-01-28T00:00:00Z"
    except:
        pass
    return None


def sync_trades(client, ledger, limit=10):
    """
    Sync trade history from CLOB API.
    Preserves REDEEM records, merges with BUY/SELL from API.
    """
    try:
        from py_clob_client.clob_types import TradeParams

        resp = client.get_trades(
            TradeParams(maker_address=client.get_address())
        )

        # API trades (BUY/SELL) - only include CONFIRMED trades
        api_trades = []
        for t in resp[:limit]:
            # Skip non-confirmed trades (RETRYING, FAILED, etc.)
            if t.get("status") != "CONFIRMED":
                continue

            ts = datetime.fromtimestamp(int(t.get("match_time", 0)), tz=timezone.utc).isoformat()
            asset_id = t.get("asset_id")
            event_slug = lookup_event_slug(asset_id) if asset_id else None

            api_trades.append({
                "timestamp": ts,
                "side": t.get("side"),
                "size": float(t.get("size", 0)),
                "price": float(t.get("price", 0)),
                "outcome": t.get("outcome"),
                "event_slug": event_slug,
            })

        # Preserve non-API records (REDEEM, DEPOSIT, AUTO_SELL, STOP_LOSS, etc.)
        preserved = [t for t in ledger.get("trades", []) if t.get("side") not in ("BUY", "SELL")]

        # Merge and sort by timestamp desc
        all_trades = preserved + api_trades
        all_trades.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        ledger["trades"] = all_trades
        return ledger, None

    except Exception as e:
        return ledger, str(e)


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.paths import LEDGER_PATH, DECISIONS_CSV_PATH
    ledger_path = LEDGER_PATH

    # Load config
    config = get_env_config()

    # Load existing ledger
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
    else:
        ledger = {"balance_usdc": 0, "positions": []}

    api_status = "(live)"
    redeem_info = ""

    # Step 1: Auto redeem settled positions
    redeemed_token_ids = set()
    redeem_result = auto_redeem(config)
    if redeem_result.get("error"):
        redeem_info = f"Redeem error: {redeem_result['error']}"
    elif redeem_result.get("skipped"):
        redeem_info = ""  # Silent skip if no redeemable positions
    elif redeem_result.get("redeemed"):
        # Record redeems as trades (side=REDEEM)
        if "trades" not in ledger:
            ledger["trades"] = []
        for r in redeem_result["redeemed"]:
            ledger["trades"].insert(0, {
                "timestamp": r["timestamp"],
                "side": "REDEEM",
                "size": r["shares"],
                "price": 1.0,  # Redeem always at $1
                "outcome": r["outcome"],
                "event_slug": r["event_slug"],
                "pnl": r["pnl"],
                "tx": r["tx"],
            })
            if r.get("token_id"):
                redeemed_token_ids.add(str(r["token_id"]))
        redeem_info = f"Redeemed {len(redeem_result['redeemed'])} positions"
        # Immediately persist REDEEM records to disk.
        # On-chain tx is irreversible - if hook crashes later, we must not lose the record.
        ledger_path.write_text(json.dumps(ledger, indent=2))

    # Step 1.5: Auto swap native USDC -> USDC.e
    swap_info = ""
    swap_result = auto_swap_usdc(config)
    if swap_result.get("error"):
        swap_info = f"Swap error: {swap_result['error']}"
    elif swap_result.get("skipped"):
        swap_info = ""
    elif swap_result.get("success"):
        # Record as DEPOSIT in trades
        if "trades" not in ledger:
            ledger["trades"] = []
        ledger["trades"].insert(0, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "side": "DEPOSIT",
            "size": swap_result["amount"],
            "price": 1.0,
            "outcome": "USDC",
            "event_slug": "usdc-deposit",
            "tx": swap_result["tx"],
        })
        swap_info = f"Converted ${swap_result['amount']:.2f} native USDC -> USDC.e (tx: {swap_result['tx'][:16]}...)"

    # Step 2: Sync positions from API
    # Exclude just-redeemed positions to prevent double-counting
    # (Data API has lag and may still return positions after on-chain redeem)
    ledger, sync_error = sync_positions(config, ledger, redeemed_token_ids=redeemed_token_ids)
    if sync_error:
        api_status = f"(sync error: {sync_error})"

    # Step 2.5: Auto stop-loss check (after sync so entry_price/shares are fresh)
    stop_loss_info = ""
    stop_loss_actions = auto_stop_loss(config, ledger)
    if stop_loss_actions:
        if "trades" not in ledger:
            ledger["trades"] = []
        sold_token_ids = set()
        for action in stop_loss_actions:
            ledger["trades"].insert(0, action)
            tid = action.get("token_id")
            if tid:
                sold_token_ids.add(tid)
        # Remove sold positions from ledger
        if sold_token_ids:
            ledger["positions"] = [
                p for p in ledger.get("positions", [])
                if p.get("token_id") not in sold_token_ids
            ]
        stop_loss_info = f"STOP-LOSS triggered: sold {len(stop_loss_actions)} position(s)"
        for a in stop_loss_actions:
            stop_loss_info += (
                f"\n  - {a['outcome']} @ {a['event_slug']}: "
                f"{a['size']}sh sold @ ${a['price']:.3f} "
                f"(entry ${a['entry_price']:.3f}, drop {a['drop_pct']:.1f}%)"
            )

    # Step 3: Create CLOB client (used for trades and balance)
    client = None
    try:
        client = get_clob_client(config)
    except Exception as e:
        api_status = f"(client error: {e})"

    # Step 4: Sync trades from API
    if client:
        ledger, trades_error = sync_trades(client, ledger)
        if trades_error:
            pass  # Silent fail, trades are optional

    # Step 5: Get real balance
    if client:
        balance_usdc, balance_error = get_real_balance(client)
        if balance_error:
            api_status = f"(balance error: {balance_error})"
        else:
            ledger["balance_usdc"] = balance_usdc

    # Calculate total value (balance + positions)
    positions_value = sum(p.get("current_value", 0) for p in ledger.get("positions", []))
    ledger["total_value"] = ledger.get("balance_usdc", 0) + positions_value
    ledger["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Save updated ledger
    ledger_path.write_text(json.dumps(ledger, indent=2))

    # Append portfolio snapshot for dashboard chart
    from config.paths import PORTFOLIO_HISTORY_PATH
    snapshot = {
        "timestamp": ledger.get("last_updated", ""),
        "balance": ledger.get("balance_usdc", 0),
        "positions_value": positions_value,
        "total_value": ledger.get("total_value", 0),
    }
    try:
        with open(PORTFOLIO_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot) + "\n")
    except Exception:
        pass  # Don't fail session start if history append fails

    # Read recent decisions (last 5)
    decisions = []
    csv_path = DECISIONS_CSV_PATH
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            decisions = list(csv.DictReader(f))[-5:]

    # Format positions
    positions_str = ""
    if ledger.get("positions"):
        for pos in ledger["positions"]:
            value_str = f"${pos.get('current_value', 0):.2f}"
            pnl = pos.get("pnl", 0)
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            redeemable = " [REDEEMABLE]" if pos.get("redeemable") else ""
            entry = pos.get("entry_price") or pos.get("avg_price", 0)
            entry_str = f"entry=${entry:.4f}" if entry else ""
            # Format end_date: "2026-01-28T00:00:00Z" -> "2026-01-28 00:00 UTC"
            end_date_raw = pos.get("end_date", "?")
            if end_date_raw and "T" in str(end_date_raw):
                end_date = end_date_raw.replace("T", " ").replace("Z", " UTC").replace(":00 UTC", " UTC")
            else:
                end_date = end_date_raw
            positions_str += f"  - {pos.get('outcome', '?')} @ {pos.get('event_slug', '?')}: {pos.get('shares', 0)} shares = {value_str} ({pnl_str}) {entry_str} | Closes: {end_date}{redeemable}\n"
    else:
        positions_str = "  (no positions)"

    # Format recent trades
    trades_str = ""
    if ledger.get("trades"):
        for t in ledger["trades"][:5]:  # Show last 5
            ts = t.get("timestamp", "")[:16].replace("T", " ")
            side = t.get("side")
            if side == "REDEEM":
                pnl = t.get("pnl", 0)
                pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                trades_str += f"  - {ts} | REDEEM {t.get('size')} {t.get('outcome')} @ $1.00 ({pnl_str}) | {t.get('event_slug', '?')}\n"
            else:
                trades_str += f"  - {ts} | {side} {t.get('size')} {t.get('outcome')} @ ${t.get('price')} | {t.get('event_slug', '?')}\n"
    else:
        trades_str = "  (no trades)"

    # Format recent decisions
    decisions_str = ""
    if decisions:
        for d in decisions:
            decisions_str += f"  - [{d.get('timestamp', '')}] {d.get('action', '')} on {d.get('market_slug', '')}\n"
    else:
        decisions_str = "  (no recent decisions)"

    # Format redeem/swap/stop-loss info
    redeem_str = f"\n**Redeem:** {redeem_info}" if redeem_info else ""
    swap_str = f"\n**Swap:** {swap_info}" if swap_info else ""
    stop_loss_str = f"\n**Stop-Loss:** {stop_loss_info}" if stop_loss_info else ""

    # Output to stdout - this gets injected into Agent context
    print(f"""
## Polymarket Account Status {api_status}

**Balance:** ${ledger.get('balance_usdc', 0):.2f} USDC
**Positions Value:** ${positions_value:.2f}
**Total Value:** ${ledger.get('total_value', 0):.2f}
**Last Updated:** {ledger.get('last_updated', 'Never')}{redeem_str}{swap_str}{stop_loss_str}

### Current Positions
{positions_str}

### Recent Trades
{trades_str}

### Recent Decisions
{decisions_str}
""")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        from config.paths import WORKSPACE
        err_path = WORKSPACE / "log" / "hook_errors.log"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now(timezone.utc).isoformat()} ---\n")
            traceback.print_exc(file=f)
        print(f"\n## Polymarket Account Status (HOOK ERROR)\n\n**Error:** {exc}\n")
        raise
