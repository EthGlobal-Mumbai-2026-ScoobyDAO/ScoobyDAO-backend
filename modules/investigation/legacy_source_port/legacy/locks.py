from __future__ import annotations
from typing import Dict,Any,List
def lp_locked_evidence_v2(w3: Web3, pair: str, known_lockers: List[str], dead_addrs: List[str]) -> Dict[str, Any]:
    c = w3.eth.contract(address=Web3.to_checksum_address(pair), abi=UNIV2_PAIR_ABI)
    total = c.functions.totalSupply().call()
    locker_bal = 0
    dead_bal = 0
    try:
        for a in known_lockers:
            locker_bal += c.functions.balanceOf(Web3.to_checksum_address(a)).call()
        for d in dead_addrs:
            dead_bal += c.functions.balanceOf(Web3.to_checksum_address(d)).call()
    except Exception:
        pass
    locked = locker_bal + dead_bal
    pct_locked = (locked / total * 100.0) if total else 0.0
    return {
        "lpLocked": pct_locked >= 50.0,
        "lockEvidence": {
            "lockerBalance": str(locker_bal),
            "deadAddressBalance": str(dead_bal),
            "pctLocked": round(pct_locked, 4),
        }
    }
