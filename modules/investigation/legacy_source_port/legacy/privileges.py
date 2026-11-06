from __future__ import annotations
from typing import Dict,Any,List
PRIV_KEYWORDS = {
    "blacklist": ["blacklist", "isBlacklisted", "setBlacklist", "unblacklist"],
    "tax": ["transferTaxRate", "setTaxFeePercent", "_taxFee", "marketingFee", "liquidityFee"],
    "max": ["maxTxAmount","maxTransactionAmount","maxWallet","maxWalletAmount"],
    "pause": ["pause","unpause","paused"],
    "trading": ["setTradingEnabled","openTrading","setSwapEnabled","enableTrading","disableTrading"],
    "mint_burn": ["mint", "burn", "burnFrom"]
}

def scan_abi_for_keywords(abi: List[dict]) -> Dict[str, List[str]]:
    hits = {k: [] for k in PRIV_KEYWORDS}
    for item in abi or []:
        if item.get("type") == "function":
            nm = item.get("name","")
            lname = nm.lower()
            for k, words in PRIV_KEYWORDS.items():
                for w in words:
                    if w.lower() in lname:
                        hits[k].append(nm)
                        break
    return hits

def privileged_facts(w3: Web3, addr: str, abi: List[dict] | None, source_code: str | None) -> Dict[str, Any]:
    hits = scan_abi_for_keywords(abi or [])
    # Augment with source keyword matches when available
    if source_code:
        lower = source_code.lower()
        for k, words in PRIV_KEYWORDS.items():
            for w in words:
                if w.lower() in lower and w not in hits[k]:
                    hits[k].append(w)

    facts: Dict[str, Any] = {
        "pauseStatus": read_pause_status(w3, addr) or "unknown",
        "blacklistPrimitives": hits["blacklist"],
        "taxPrimitives": hits["tax"],
        "maxTxPrimitives": hits["max"],
        "tradingPrimitives": hits["trading"],
        "mintBurnPrimitives": hits["mint_burn"],
    }
    return facts
