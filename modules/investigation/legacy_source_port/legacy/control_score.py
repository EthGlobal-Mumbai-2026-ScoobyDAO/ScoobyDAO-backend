from __future__ import annotations
from typing import Dict,Any
from .labels import label_from_pct
def compute_score(facts: Dict[str, Any], flags: list[Dict[str, Any]]) -> Dict[str, int | str]:
    # Start 100, subtract per spec
    s = 100

    owner = facts.get("owner")
    ownership_model = facts.get("ownershipModel")
    multisig = facts.get("multisig") or {}
    proxy = facts.get("proxy") or {}
    priv = facts

    # Ownership & upgrades
    if ownership_model == "Ownable" and not facts.get("renounced"):
        # if owner EOA and has mint/pause/upgrade power (approx by primitives)
        if facts.get("mintBurnPrimitives") or facts.get("pauseStatus") == "paused" or proxy.get("type") in ("UUPS","Transparent"):
            s -= 25
    if multisig.get("isSafe") and (multisig.get("threshold", 0) >= 2):
        s -= 0
    if proxy.get("type") in ("UUPS","Transparent") and proxy.get("admin"):
        # admin EOA vs Safe distinction
        if not multisig.get("isSafe") and proxy.get("admin") == owner:
            s -= 20
        elif multisig.get("isSafe"):
            s -= 5
    if facts.get("renounced"):
        s += 5

    # Privileges
    if facts.get("pauseStatus") == "paused":
        s -= 10
    if (facts.get("blacklistPrimitives") or []):
        s -= 10
    # fee on transfer hint -> use presence as proxy; stronger if we had log-derived pct >= 5
    if (facts.get("taxPrimitives") or []):
        s -= 10
    if (facts.get("maxTxPrimitives") or []):
        s -= 5

    # Supply & holders
    top = (facts.get("supply") or {}).get("topHolders") or []
    if top:
        if top[0].get("pct", 0) >= 20:
            s -= 15
        top10 = sum(h.get("pct",0) for h in top[:10])
        if top10 >= 70:
            s -= 10

    # Liquidity
    liq = facts.get("liquidity") or {}
    if liq.get("lpLocked") and (liq.get("lockEvidence") or {}).get("pctLocked", 0) >= 50:
        s += 5
    elif liq.get("pair") and not liq.get("lpLocked"):
        s -= 15

    # Honeypot risk
    hp = facts.get("honeypot") or {}
    if hp.get("risk") == "high":
        s -= 25
    elif hp.get("risk") == "medium":
        s -= 10

    s = max(0, min(100, s))
    return {"fundamentals_score": s, "label": label_from_pct(s)}
