from __future__ import annotations
from typing import Dict,List
def mev_exposure_proxy(depth_up_5_quote: float, slippage_curve: List[Dict[str, float]]) -> Dict[str, any]:
    """Heuristic proxy when no sandwich dataset is wired.

    - Elevated if a 5k trade moves > 50 bps or a 10k trade > 100 bps, or depth_up_5_quote < 100k.

    Returns {'score': 0..100, 'evidence': {...}} where higher is worse exposure.

    """
    def get_slip(size: float) -> float:
        for pt in slippage_curve:
            if abs(pt['notionalQuote'] - size) < 1e-6:
                return abs(pt['slippagePct'])*100  # in percent
        # nearest
        if not slippage_curve:
            return 0.0
        nearest = min(slippage_curve, key=lambda p: abs(p['notionalQuote'] - size))
        return abs(nearest['slippagePct'])*100

    slip5k = get_slip(5000.0)
    slip10k = get_slip(10000.0)
    elevated = (slip5k > 0.5) or (slip10k > 1.0) or (depth_up_5_quote < 100000.0)
    if elevated:
        score = 68
        badge = "elevated"
    else:
        score = 40
        badge = "normal"
    return {"score": score, "evidence": {"sandwichDensity": badge, "depthThin": elevated}}
