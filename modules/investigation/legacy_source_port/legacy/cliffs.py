from __future__ import annotations
from decimal import Decimal
from typing import Dict,List
def _clean_ticks(ticks: List[Dict]) -> List[Dict[str, int]]:
    cleaned = []
    for t in ticks:
        cleaned.append({
            "tick": int(t.get("tick") if "tick" in t else t.get("tickIdx")),
            "liquidityNet": int(t.get("liquidityNet", 0)),
            "liquidityGross": int(t.get("liquidityGross", 0)),
        })
    return cleaned

def detect_liquidity_cliffs(ticks: List[Dict[str, int]], active_tick: int, window_ticks: int = 400) -> List[Dict[str, float]]:
    """Compute deltaLRatio across initialized ticks near the active tick."""
    ticks = _clean_ticks(ticks)  # ✅ ensure ints
    windowed = [t for t in ticks if (active_tick - window_ticks) <= t["tick"] <= (active_tick + window_ticks)]
    windowed.sort(key=lambda x: x["tick"])

    # Reconstruct relative L change to compute a scale-free ratio
    cliffs: List[Dict[str, float]] = []
    L = Decimal(1)
    prev_L = L
    for t in windowed:
        L_after = prev_L + Decimal(t["liquidityNet"])
        ratio = float(abs(L_after - prev_L) / max(prev_L, Decimal(1)))
        cliffs.append({"tick": float(t["tick"]), "deltaLRatio": ratio})
        prev_L = L_after

    cliffs.sort(key=lambda x: x["deltaLRatio"], reverse=True)
    return cliffs[:8]

def active_liquidity_ratio(ticks: List[Dict[str, int]], active_tick: int, active_L: int, band_ticks: int = 600) -> float:
    """Estimate active liquidity ratio in a local band."""
    ticks = _clean_ticks(ticks)  # ✅ ensure ints
    windowed = [t for t in ticks if (active_tick - band_ticks) <= t["tick"] <= (active_tick + band_ticks)]
    windowed.sort(key=lambda x: x["tick"])
    if len(windowed) < 2:
        return 1.0

    from decimal import Decimal
    ad = Decimal(active_L if active_L > 0 else 1)
    L = ad
    total = Decimal(0)
    for i in range(len(windowed) - 1):
        seg_len = abs(windowed[i + 1]["tick"] - windowed[i]["tick"])
        total += abs(L) * seg_len
        L += Decimal(windowed[i + 1]["liquidityNet"])

    span = abs(windowed[-1]["tick"] - windowed[0]["tick"])
    avg_seg_len = (span / (len(windowed) - 1)) if (len(windowed) - 1) else 1
    denom = (total / Decimal(avg_seg_len)) if avg_seg_len > 0 else total
    if denom <= 0:
        return 1.0
    return float(ad / denom)
