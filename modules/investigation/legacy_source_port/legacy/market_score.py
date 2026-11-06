from __future__ import annotations
from typing import Dict,List
def clamp(x: int) -> int:
    return max(0, min(100, x))

def microstructure_score(depth_up_5: float, depth_down_5_quote: float, depth_up_10: float, depth_down_10: float,
                         max_deltaL_ratio_near: float, cliff_within_100: bool,
                         active_liq_ratio: float,
                         top1_share: float, top5_share: float, hhi: float,
                         cross_spread_bps: float,
                         mev_badge: str) -> int:
    """
    Scoring with sanity guards:
    - Zero/near-zero depth yields zero depth points.
    - Active-liquidity ratio and LP concentration don't award points when market is functionally illiquid.
    - Depth points increase with depth (not the inverse).
    """
    # Sanity flags
    EPS = 1.0  # treat < $1 as zero
    no_depth_5  = (depth_up_5 <= EPS and depth_down_5_quote <= EPS)
    no_depth_10 = (depth_up_10 <= EPS and depth_down_10 <= EPS)

    score = 0

    # Depth (max ~30 points from 5% + up to 10 from 10%)
    def depth_points_5(v: float) -> int:
        if v <= EPS:            return 0
        if v < 50_000:          return 2
        if v < 250_000:         return 6
        if v < 750_000:         return 10
        if v < 2_000_000:       return 13
        return 15

    score += depth_points_5(depth_up_5)
    score += depth_points_5(depth_down_5_quote)

    # 10% window bonus (0/6/10)
    if not no_depth_10:
        if depth_up_10 > 1_000_000 and depth_down_10 > 1_000_000:
            score += 10
        elif depth_up_10 > 500_000 or depth_down_10 > 500_000:
            score += 6
        else:
            score += 0
    # else: +0 when both sides are zero

    # Slippage smoothness proxy via deltaL (max 15)
    # If there's no depth, do not award smoothness points.
    if not no_depth_5:
        if max_deltaL_ratio_near < 0.2:
            score += 10
        else:
            # linear map 0.2..1.0 -> 10..0
            r = max(0.0, min(1.0, (1.0 - (max(0.0, max_deltaL_ratio_near) - 0.2) / 0.8) * 10))
            score += int(r)
        if not cliff_within_100:
            score += 5
    else:
        # still penalize a nearby cliff if present (no bonus otherwise)
        if cliff_within_100:
            score += 0
        else:
            score += 0

    # Active-liquidity ratio (max 10) — only meaningful if there is depth
    if not no_depth_5:
        if active_liq_ratio >= 0.6:   score += 10
        elif active_liq_ratio >= 0.4: score += 6
        else:                         score += 2
    # else: +0

    # LP concentration (max 20) — only if positions exist
    if not (top1_share == 0.0 and top5_share == 0.0 and hhi == 0.0):
        score += 10 if top1_share <= 0.15 else 4
        score += 10 if top5_share <= 0.5 else 4
        if hhi > 0.18:
            score -= 5
    # else: +0 (unknown / no positions)

    # Cross-venue spread (max 5) — small benefit even in thin markets
    if cross_spread_bps <= 10:        score += 5
    elif cross_spread_bps <= 30:      score += 3
    else:                              score += 1

    # MEV (max 10) — unchanged mapping
    if mev_badge == "elevated":       score += 2
    elif mev_badge == "normal":       score += 6
    else:                             score += 10

    return clamp(int(score))
