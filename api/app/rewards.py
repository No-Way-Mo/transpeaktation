"""Route rewards on Solana (devnet): a little SOL for taking transPEAKtation's recommended route.

Every logged trip's plan carries an offer (plan.reward) on the recommended route. Once the rider has arrived on it,
they claim it with a wallet address (POST /trips/{id}/reward) and the treasury pays it right away (SOL transfer + a
memo naming the trip), if the trip took a plausible time.

Rewards are paid by a server treasury wallet (SOLANA_TREASURY_KEY) on devnet/testnet only; riders never sign or
spend anything. Helper for the treasury:
    cd api && .venv/bin/python -m app.rewards keygen | balance | airdrop
"""
from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any

import httpx


LAMPORTS_PER_SOL = 1_000_000_000
REWARD_LAMPORTS = 5_000_000     # 0.005 SOL per trip; above the rent minimum for a brand-new wallet
MIN_TRIP_FRACTION = 0.5       # arriving sooner than half the predicted drive after departing forfeits the reward
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


def rpc_url() -> str:
    return os.environ.get("SOLANA_RPC_URL") or "https://api.devnet.solana.com"


def cluster() -> str | None:
    """devnet / testnet / localnet from the RPC URL; None = anything else (mainnet or unknown): no payouts."""
    url = rpc_url()
    for name in ("devnet", "testnet"):
        if name in url:
            return name
    return "localnet" if "localhost" in url or "127.0.0.1" in url else None


def treasury():
    """The payer keypair from SOLANA_TREASURY_KEY (base58 secret, as Phantom exports it, or solana-keygen's JSON
    byte array). None if unset or unreadable."""
    raw = (os.environ.get("SOLANA_TREASURY_KEY") or "").strip()
    if not raw:
        return None
    from solders.keypair import Keypair
    try:
        return Keypair.from_bytes(json.loads(raw)) if raw.startswith("[") else Keypair.from_base58_string(raw)
    except Exception:
        return None


def available() -> bool:
    return cluster() is not None and treasury() is not None


def status() -> str:
    if cluster() is None:
        return "off (SOLANA_RPC_URL is not devnet/testnet)"
    kp = treasury()
    return f"ready ({cluster()}, treasury {kp.pubkey()})" if kp else "no SOLANA_TREASURY_KEY"


def min_trip_fraction() -> float:
    """REWARD_MIN_TRIP_FRACTION overrides MIN_TRIP_FRACTION; 0 pays on any completed trip (stage demo)."""
    try:
        return float(os.environ.get("REWARD_MIN_TRIP_FRACTION") or MIN_TRIP_FRACTION)
    except ValueError:
        return MIN_TRIP_FRACTION


def valid_wallet(address: str) -> bool:
    from solders.pubkey import Pubkey
    try:
        Pubkey.from_string(address)
    except Exception:
        return False
    return True


def explorer(signature: str) -> str | None:
    c = cluster()
    return f"https://explorer.solana.com/tx/{signature}?cluster={c}" if c in ("devnet", "testnet") else None


# --- the offer ---------------------------------------------------------------------------------------------------

def offer(best: int) -> dict:
    """The reward for taking the recommended route (plan.best)."""
    return {"route": best, "lamports": REWARD_LAMPORTS, "sol": REWARD_LAMPORTS / LAMPORTS_PER_SOL}


# --- payout ------------------------------------------------------------------------------------------------------

class PayoutError(RuntimeError):
    pass


async def _rpc(http: httpx.AsyncClient, method: str, params: list) -> Any:
    try:
        r = await http.post(rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise PayoutError(f"{method}: {type(e).__name__}") from e
    if "error" in body:
        raise PayoutError(f"{method}: {body['error'].get('message', 'error')}")
    return body["result"]


async def pay(http: httpx.AsyncClient, wallet: str, lamports: int, memo: str) -> str:
    """Transfer `lamports` from the treasury to `wallet`, with `memo` on chain. Returns the tx signature once the
    cluster accepted it (not waiting for confirmation)."""
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    from solders.transaction import Transaction

    payer = treasury()
    if payer is None or cluster() is None:
        raise PayoutError("rewards not configured")
    latest = await _rpc(http, "getLatestBlockhash", [{"commitment": "confirmed"}])
    blockhash = Hash.from_string(latest["value"]["blockhash"])
    ixs = [transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=Pubkey.from_string(wallet), lamports=lamports)),
           Instruction(Pubkey.from_string(MEMO_PROGRAM), memo.encode(), [])]
    tx = Transaction([payer], Message.new_with_blockhash(ixs, payer.pubkey(), blockhash), blockhash)
    return await _rpc(http, "sendTransaction", [base64.b64encode(bytes(tx)).decode(),
                                                {"encoding": "base64", "preflightCommitment": "confirmed"}])


async def settle(http: httpx.AsyncClient, reward: dict) -> dict:
    """A claimed reward -> {status, signature?, error?}: paid, too_soon (arrived sooner than MIN_TRIP_FRACTION of the
    predicted drive after departing) or failed (RPC / treasury trouble)."""
    if (reward["arrived_at"] - reward["depart_at"]).total_seconds() < min_trip_fraction() * reward["expected_sec"]:
        return {"status": "too_soon"}
    try:
        sig = await pay(http, reward["wallet"], reward["lamports"], f"transPEAKtation route reward {reward['trip_id']}")
    except PayoutError as e:
        return {"status": "failed", "error": str(e)[:200]}
    return {"status": "paid", "signature": sig}


def view(reward: dict) -> dict:
    """What the app sees about a reward."""
    sig = reward.get("signature")
    return {"status": reward["status"], "lamports": reward["lamports"], "sol": reward["lamports"] / LAMPORTS_PER_SOL,
            "wallet": reward["wallet"], "signature": sig, "explorer": explorer(sig) if sig else None}


# --- treasury helper ---------------------------------------------------------------------------------------------

def _cli(cmd: str) -> None:
    import asyncio
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if cmd == "keygen":
        from solders.keypair import Keypair
        kp = Keypair()
        print(f"SOLANA_TREASURY_KEY={kp}\n# address: {kp.pubkey()}  (add the line above to api/.env, then `airdrop`)")
        return
    kp = treasury()
    if kp is None:
        sys.exit("no SOLANA_TREASURY_KEY in api/.env (run `keygen` first)")
    if cluster() is None:
        sys.exit("SOLANA_RPC_URL must be devnet/testnet/localnet")

    async def run():
        async with httpx.AsyncClient() as http:
            if cmd == "airdrop":
                try:
                    print("airdrop tx:", await _rpc(http, "requestAirdrop", [str(kp.pubkey()), LAMPORTS_PER_SOL]))
                except PayoutError as e:
                    print(f"airdrop refused ({e}); use https://faucet.solana.com with {kp.pubkey()}")
            bal = await _rpc(http, "getBalance", [str(kp.pubkey()), {"commitment": "confirmed"}])
            print(f"{kp.pubkey()} on {cluster()}: {bal['value'] / LAMPORTS_PER_SOL} SOL")
    asyncio.run(run())


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("keygen", "balance", "airdrop"):
        sys.exit("usage: python -m app.rewards keygen | balance | airdrop")
    _cli(sys.argv[1])
