#!/usr/bin/env python3
"""
Withdraw USDC.e from Polymarket EOA wallet to an external address.

For signature_type=0 (EOA), USDC.e sits directly in the EOA wallet,
not inside the Exchange contract. The Exchange is non-custodial and uses
transferFrom at trade time. So withdrawal is a simple ERC-20 transfer.

Set WITHDRAW_DESTINATION in .env to your target address.

Usage:
    python scripts/withdraw.py status
    python scripts/withdraw.py send --amount 50
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
from config.paths import POLYGON_RPC_URL as POLYGON_RPC

def _load_withdraw_destination():
    """Load withdraw destination address from .env."""
    from dotenv import dotenv_values
    env_path = Path(__file__).parent.parent / ".env"
    config = dotenv_values(str(env_path))
    dest = config.get("WITHDRAW_DESTINATION")
    if not dest:
        print("ERROR: Missing WITHDRAW_DESTINATION in .env")
        sys.exit(1)
    return dest
CHAIN_ID = 137
USDC_DECIMALS = 6

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_env():
    """Load .env config from project root."""
    from dotenv import dotenv_values
    env_path = Path(__file__).parent.parent / ".env"
    config = dotenv_values(str(env_path))
    pk = config.get("POLYGON_WALLET_PRIVATE_KEY")
    eoa = config.get("EOA_ADDRESS")
    if not pk or not eoa:
        print("ERROR: Missing POLYGON_WALLET_PRIVATE_KEY or EOA_ADDRESS in .env")
        sys.exit(1)
    return pk, eoa


def _get_web3():
    from web3 import Web3
    return Web3(Web3.HTTPProvider(POLYGON_RPC))


def _get_balances(w3, address):
    """Return (usdc_e_balance_human, pol_balance_human, usdc_e_raw)."""
    addr = w3.to_checksum_address(address)
    usdc = w3.eth.contract(address=w3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    usdc_raw = usdc.functions.balanceOf(addr).call()
    usdc_human = Decimal(usdc_raw) / Decimal(10 ** USDC_DECIMALS)
    pol_raw = w3.eth.get_balance(addr)
    pol_human = Decimal(pol_raw) / Decimal(10 ** 18)
    return usdc_human, pol_human, usdc_raw


def _get_api_balance():
    """Get Polymarket API balance (should match on-chain for EOA)."""
    try:
        pk, _ = _load_env()
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        client = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137, signature_type=0)
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        resp = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        raw = int(resp.get("balance", "0"))
        return Decimal(raw) / Decimal(10 ** USDC_DECIMALS)
    except Exception as e:
        return f"Error: {e}"


def _send_tx_with_retry(w3, signed_tx, max_retries=2, delay=10, timeout=120):
    """Send tx with retry on transient errors.
    Returns (tx_hash, receipt). On nonce-too-low after rate limit,
    recovers the tx hash from the signed tx and waits for receipt.
    """
    import time
    from eth_account import Account

    # Pre-compute tx hash so we can recover it on nonce-too-low
    tx_hash_precomputed = w3.keccak(signed_tx.raw_transaction)

    for attempt in range(max_retries + 1):
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return tx_hash, receipt
        except Exception as e:
            msg = str(e).lower()
            if "nonce too low" in msg:
                # TX was already mined from a prior broadcast attempt
                print("  Nonce too low - recovering prior tx...")
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash_precomputed, timeout=30)
                    return tx_hash_precomputed, receipt
                except Exception:
                    print("  Could not recover receipt. TX likely succeeded on-chain.")
                    return tx_hash_precomputed, None
            if attempt < max_retries and ("rate limit" in msg or "too many" in msg):
                print(f"  Rate limited, retrying in {delay}s ({attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            raise


def _record_withdrawal(amount, tx_hex):
    """Append WITHDRAW entry to ledger.json trades array."""
    # Resolve ledger path relative to project root (parent of scripts/)
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    from config.paths import LEDGER_PATH

    try:
        ledger = json.loads(LEDGER_PATH.read_text())
    except Exception:
        print("  WARNING: Could not read ledger.json, skipping record.")
        return

    ledger["trades"].insert(0, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "side": "WITHDRAW",
        "size": amount,
        "price": 1.0,
        "outcome": "USDC.e",
        "event_slug": "withdraw",
        "tx": tx_hex,
    })

    # Update balance to reflect withdrawal
    ledger["balance_usdc"] = float(Decimal(str(ledger["balance_usdc"])) - Decimal(str(amount)))
    ledger["total_value"] = ledger["balance_usdc"] + sum(
        p.get("current_value", 0) for p in ledger.get("positions", [])
    )
    ledger["last_updated"] = datetime.now(timezone.utc).isoformat()

    LEDGER_PATH.write_text(json.dumps(ledger, indent=2))
    print(f"  Ledger updated: WITHDRAW ${amount:.2f} recorded.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_status():
    """Show all balances."""
    pk, eoa = _load_env()
    withdraw_dest = _load_withdraw_destination()
    w3 = _get_web3()
    usdc_bal, pol_bal, _ = _get_balances(w3, eoa)
    api_bal = _get_api_balance()

    print("=== Polymarket Wallet Status ===")
    print(f"  EOA Address:     {eoa}")
    print(f"  USDC.e (chain):  ${usdc_bal:.6f}")
    print(f"  USDC.e (API):    ${api_bal}")
    print(f"  POL (gas):       {pol_bal:.6f} POL")
    print(f"  Withdraw target: {withdraw_dest}")
    print()

    if usdc_bal < Decimal("0.01"):
        print("  No USDC.e available to withdraw.")
    else:
        print(f"  Available to withdraw: ${usdc_bal:.2f}")


def cmd_send(amount: float):
    """Transfer USDC.e from EOA to destination address."""
    from eth_account import Account

    pk, eoa = _load_env()
    withdraw_dest = _load_withdraw_destination()
    w3 = _get_web3()

    usdc_bal, pol_bal, _ = _get_balances(w3, eoa)
    amount_decimal = Decimal(str(amount))
    amount_raw = int(amount_decimal * Decimal(10 ** USDC_DECIMALS))

    print("=== Withdraw USDC.e ===")
    print(f"  From:    {eoa}")
    print(f"  To:      {withdraw_dest}")
    print(f"  Amount:  ${amount_decimal:.6f} USDC.e")
    print(f"  Balance: ${usdc_bal:.6f} USDC.e")
    print(f"  Gas:     {pol_bal:.6f} POL")
    print()

    if amount_decimal > usdc_bal:
        print(f"ERROR: Insufficient balance. Have ${usdc_bal:.2f}, need ${amount_decimal:.2f}")
        sys.exit(1)

    if pol_bal < Decimal("0.01"):
        print("ERROR: Insufficient POL for gas. Need at least 0.01 POL.")
        sys.exit(1)

    confirm = input("Confirm withdrawal? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    addr = w3.to_checksum_address(eoa)
    account = Account.from_key(pk)
    usdc_contract = w3.eth.contract(address=w3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    to_addr = w3.to_checksum_address(withdraw_dest)
    nonce = w3.eth.get_transaction_count(addr)

    # Estimate gas
    gas_estimate = usdc_contract.functions.transfer(to_addr, amount_raw).estimate_gas({"from": addr})
    gas_limit = int(gas_estimate * 1.3)  # 30% buffer

    tx = usdc_contract.functions.transfer(to_addr, amount_raw).build_transaction({
        "chainId": CHAIN_ID,
        "from": addr,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": w3.eth.gas_price,
    })

    signed = account.sign_transaction(tx)
    print(f"  Sending tx (gas limit: {gas_limit})...")

    tx_hash, receipt = _send_tx_with_retry(w3, signed)

    tx_hex = tx_hash.hex() if tx_hash else "unknown"

    if receipt is None:
        # Nonce collision recovery - tx likely succeeded but no receipt
        print(f"  TX likely succeeded (nonce recovery): {tx_hex}")
        print(f"  https://polygonscan.com/tx/{tx_hex}")
        _record_withdrawal(amount, tx_hex)
        new_bal, _, _ = _get_balances(w3, eoa)
        print(f"  New balance: ${new_bal:.6f} USDC.e")
    elif receipt.status == 1:
        print(f"  SUCCESS! TX: {tx_hex}")
        print(f"  https://polygonscan.com/tx/{tx_hex}")
        _record_withdrawal(amount, tx_hex)
        new_bal, _, _ = _get_balances(w3, eoa)
        print(f"  New balance: ${new_bal:.6f} USDC.e")
    else:
        print(f"  FAILED! TX reverted: {tx_hex}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Withdraw USDC.e from Polymarket EOA wallet")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show wallet balances")

    send_parser = sub.add_parser("send", help="Send USDC.e to destination")
    send_parser.add_argument("--amount", type=float, required=True, help="Amount in USDC to send")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "send":
        cmd_send(args.amount)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
