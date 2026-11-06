from __future__ import annotations
def label_from_pct(pct: int) -> str:
    if pct >= 70:
        return "Green"
    if pct >= 40:
        return "Yellow"
    return "Red"
