#!/usr/bin/env python3
"""
Set token allowances for Polymarket CLOB trading.

This script must be run ONCE per EOA wallet before trading.
It approves two token types for three exchange contracts:

1. USDC.e (ERC-20 approve) - needed for BUY orders
2. Conditional Tokens / CTF (ERC-1155 setApprovalForAll) - needed for SELL orders

Target contracts:
  - CTF Exchange (standard binary markets)
  - NegRisk CTF Exchange (multi-outcome markets)
  - NegRisk Adapter (multi-outcome adapter)

Based on: https://gist.github.com/poly-rodr/44313920481de58d5a3f6d1f8226bd5e
"""

import sys
import time
from pathlib import Path
from dotenv import dotenv_values
from web3 import Web3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

env_path = Path(__file__).parent.parent / ".env"
config = dotenv_values(str(env_path))

PRIVATE_KEY = config.get("POLYGON_WALLET_PRIVATE_KEY", "")
PUBLIC_KEY = config.get("EOA_ADDRESS", "")
CHAIN_ID = 137

from config.paths import POLYGON_RPC_URL as RPC_URL

# Polymarket contract addresses (Polygon mainnet)
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Exchange targets that need approval
EXCHANGE_TARGETS = {
    "CTF Exchange": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "NegRisk CTF Exchange": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "NegRisk Adapter": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
}

# ABIs (minimal)
ERC20_APPROVE_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

ERC1155_APPROVAL_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "bool", "name": "approved", "type": "bool"},
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"},
            {"internalType": "address", "name": "operator", "type": "address"},
        ],
        "name": "isApprovedForAll",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MAX_UINT256 = 2**256 - 1

# Retry delay between RPC calls (polygon-rpc.com rate limits)
RPC_DELAY = 3


def _wait_for_receipt(w3, tx_hash, timeout=180):
    """Wait for transaction receipt with retry on rate limit."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
        except ValueError as e:
            if "rate limit" in str(e).lower() or "-32090" in str(e):
                time.sleep(12)
                continue
            raise
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError(f"Timeout waiting for tx {tx_hash.hex()}")


def check_allowances(w3, usdc_contract, ctf_contract, owner):
    """Check current allowance status for all targets."""
    print("\n--- Current Allowance Status ---")
    all_ok = True
    for name, target in EXCHANGE_TARGETS.items():
        time.sleep(RPC_DELAY)
        usdc_allowance = usdc_contract.functions.allowance(owner, target).call()
        time.sleep(RPC_DELAY)
        ctf_approved = ctf_contract.functions.isApprovedForAll(owner, target).call()
        usdc_ok = usdc_allowance > 10**12  # > 1M USDC
        status_usdc = "OK" if usdc_ok else "MISSING"
        status_ctf = "OK" if ctf_approved else "MISSING"
        print(f"  {name} ({target[:10]}...):")
        print(f"    USDC.e allowance: {usdc_allowance / 10**6:.0f} USDC [{status_usdc}]")
        print(f"    CTF approved:     {ctf_approved} [{status_ctf}]")
        if not usdc_ok or not ctf_approved:
            all_ok = False
    return all_ok


def _get_gas_params(w3):
    """Get dynamic gas parameters based on current network conditions."""
    try:
        block = w3.eth.get_block("latest")
        base_fee = block.get("baseFeePerGas", w3.to_wei(30, "gwei"))
    except Exception:
        base_fee = w3.to_wei(100, "gwei")
    # 3x base fee for maxFeePerGas, generous priority fee
    max_fee = max(base_fee * 3, w3.to_wei(100, "gwei"))
    priority_fee = min(base_fee, w3.to_wei(100, "gwei"))
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee}


def set_allowances(w3, usdc_contract, ctf_contract, owner, private_key):
    """Send approval transactions for all targets."""
    # Use 'pending' nonce to skip any stuck transactions
    nonce = w3.eth.get_transaction_count(owner, "pending")
    print(f"  Starting nonce: {nonce}")
    gas_params = _get_gas_params(w3)
    print(f"  Gas: maxFee={w3.from_wei(gas_params['maxFeePerGas'], 'gwei'):.0f} gwei, "
          f"priority={w3.from_wei(gas_params['maxPriorityFeePerGas'], 'gwei'):.0f} gwei")
    tx_count = 0

    for name, target in EXCHANGE_TARGETS.items():
        # --- USDC.e ERC-20 approve ---
        time.sleep(RPC_DELAY)
        current_allowance = usdc_contract.functions.allowance(owner, target).call()
        if current_allowance < 10**12:
            print(f"\n  [{name}] Approving USDC.e...")
            tx = usdc_contract.functions.approve(target, MAX_UINT256).build_transaction({
                "chainId": CHAIN_ID,
                "from": owner,
                "nonce": nonce,
                "gas": 100000,
                **gas_params,
            })
            signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
            time.sleep(RPC_DELAY)
            try:
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                print(f"    tx sent: {tx_hash.hex()}")
            except ValueError as e:
                if "already known" in str(e):
                    tx_hash = w3.keccak(signed.raw_transaction)
                    print(f"    tx already in mempool: {tx_hash.hex()}")
                else:
                    raise
            receipt = _wait_for_receipt(w3, tx_hash)
            status = "SUCCESS" if receipt.status == 1 else "FAILED"
            print(f"    confirmed [{status}]")
            nonce += 1
            tx_count += 1
        else:
            print(f"\n  [{name}] USDC.e already approved (skip)")

        # --- CTF ERC-1155 setApprovalForAll ---
        time.sleep(RPC_DELAY)
        is_approved = ctf_contract.functions.isApprovedForAll(owner, target).call()
        if not is_approved:
            print(f"  [{name}] Approving CTF (setApprovalForAll)...")
            tx = ctf_contract.functions.setApprovalForAll(target, True).build_transaction({
                "chainId": CHAIN_ID,
                "from": owner,
                "nonce": nonce,
                "gas": 100000,
                **gas_params,
            })
            signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
            time.sleep(RPC_DELAY)
            try:
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                print(f"    tx sent: {tx_hash.hex()}")
            except ValueError as e:
                if "already known" in str(e):
                    # Transaction already in mempool from previous run
                    tx_hash = w3.keccak(signed.raw_transaction)
                    print(f"    tx already in mempool: {tx_hash.hex()}")
                else:
                    raise
            receipt = _wait_for_receipt(w3, tx_hash)
            status = "SUCCESS" if receipt.status == 1 else "FAILED"
            print(f"    confirmed [{status}]")
            nonce += 1
            tx_count += 1
        else:
            print(f"  [{name}] CTF already approved (skip)")

    return tx_count


def main():
    if not PRIVATE_KEY or not PUBLIC_KEY:
        print("ERROR: Set POLYGON_WALLET_PRIVATE_KEY and EOA_ADDRESS in .env")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    # Polygon is a POA chain; inject middleware to handle extraData > 32 bytes
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except ImportError:
        pass
    if not w3.is_connected():
        print("ERROR: Cannot connect to Polygon RPC")
        sys.exit(1)

    owner = Web3.to_checksum_address(PUBLIC_KEY)
    print(f"Wallet: {owner}")

    # Check POL balance for gas
    pol_balance = w3.eth.get_balance(owner)
    pol_ether = w3.from_wei(pol_balance, "ether")
    print(f"POL balance: {pol_ether:.4f}")
    if pol_balance < w3.to_wei(0.01, "ether"):
        print("WARNING: Very low POL balance, may not have enough gas")

    usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_APPROVE_ABI)
    ctf_contract = w3.eth.contract(address=Web3.to_checksum_address(CTF), abi=ERC1155_APPROVAL_ABI)

    # Check current state
    all_ok = check_allowances(w3, usdc_contract, ctf_contract, owner)

    if all_ok:
        print("\nAll allowances already set. Nothing to do.")
        return

    # Check mode
    if "--check" in sys.argv:
        print("\nRun without --check to set missing allowances.")
        return

    # Set missing allowances
    print("\n--- Setting Missing Allowances ---")
    tx_count = set_allowances(w3, usdc_contract, ctf_contract, owner, PRIVATE_KEY)
    print(f"\nSent {tx_count} transaction(s)")

    # Verify
    print("\n--- Verifying ---")
    check_allowances(w3, usdc_contract, ctf_contract, owner)


if __name__ == "__main__":
    main()
