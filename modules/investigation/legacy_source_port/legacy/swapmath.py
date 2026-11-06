from __future__ import annotations
from decimal import Decimal,getcontext
from typing import Dict,List,Tuple
from .math_utils import sqrtX96_to_unscaled_sqrt,sqrt_price_at_tick_unscaled,to_float
getcontext().prec=80
class TickLadder:
    """Tracks initialized ticks and allows walking across them updating active L."""
    def __init__(self, ticks):
        # Defensive coercion (handles subgraphs that return strings)
        cleaned = []
        for t in ticks:
            cleaned.append({
                "tick": int(t.get("tick") if "tick" in t else t.get("tickIdx")),
                "liquidityNet": int(t.get("liquidityNet", 0)),
                "liquidityGross": int(t.get("liquidityGross", 0)),
            })
        self.ticks = sorted(cleaned, key=lambda x: x["tick"])
        self.index_by_tick = {t["tick"]: i for i, t in enumerate(self.ticks)}

    def next_tick_above(self, current_tick: int):
        for t in self.ticks:
            if t["tick"] > current_tick:
                return t["tick"]
        return None

    def next_tick_below(self, current_tick: int):
        prev = None
        for t in self.ticks:
            if t["tick"] >= current_tick:
                return prev
            prev = t["tick"]
        return prev

def _walk_up_to_s(S: Decimal, targetS: Decimal, L: Decimal, ladder: TickLadder, current_tick: int) -> Tuple[Decimal, Decimal]:
    """Walk price upward from S to targetS (S < targetS) with constant L per segment.
    Returns (token1_in_effective, token0_out). No fee adjustment here.
    """
    token1_in_eff = Decimal(0)
    token0_out = Decimal(0)
    cursorS = S
    tick = current_tick
    while cursorS < targetS:
        next_tick = ladder.next_tick_above(tick) if ladder else None
        step_end_S = targetS
        # If there is a tick above and its sqrt is within the target, stop there to update L
        if next_tick is not None:
            next_tick_S = sqrt_price_at_tick_unscaled(next_tick)
            if next_tick_S < step_end_S:
                step_end_S = next_tick_S
        # compute deltas in this segment
        dy_eff = L * (step_end_S - cursorS)  # token1 in effective
        dx_out = L * ( (Decimal(1)/step_end_S) - (Decimal(1)/cursorS) )  # negative -> make positive
        dx_out = -dx_out
        token1_in_eff += dy_eff
        token0_out += dx_out
        cursorS = step_end_S
        if next_tick is not None and cursorS == next_tick_S:
            # cross: L increases by liquidityNet at that tick when moving upward
            i = ladder.index_by_tick[next_tick]
            L += Decimal(ladder.ticks[i]['liquidityNet'])
            tick = next_tick
        else:
            break  # reached target
    return token1_in_eff, token0_out

def _walk_down_to_s(S: Decimal, targetS: Decimal, L: Decimal, ladder: TickLadder, current_tick: int) -> Tuple[Decimal, Decimal]:
    """Walk price downward from S to targetS (S > targetS).
    Returns (token0_in_effective, token1_out). No fee adjustment here.
    """
    token0_in_eff = Decimal(0)
    token1_out = Decimal(0)
    cursorS = S
    tick = current_tick
    while cursorS > targetS:
        prev_tick = ladder.next_tick_below(tick) if ladder else None
        step_end_S = targetS
        if prev_tick is not None:
            prev_tick_S = sqrt_price_at_tick_unscaled(prev_tick)
            if prev_tick_S > step_end_S:
                step_end_S = prev_tick_S
        dx_eff = L * ( (Decimal(1)/step_end_S) - (Decimal(1)/cursorS) )  # token0 in effective, positive as step_end_S < cursorS
        dy_out = L * (cursorS - step_end_S)  # token1 out
        token0_in_eff += dx_eff
        token1_out += dy_out
        cursorS = step_end_S
        if prev_tick is not None and cursorS == prev_tick_S:
            # crossing downward reduces L by liquidityNet at that tick (inverse of moving up)
            i = ladder.index_by_tick[prev_tick]
            L -= Decimal(ladder.ticks[i]['liquidityNet'])
            tick = prev_tick
        else:
            break
    return token0_in_eff, token1_out

def notional_for_pct_moves(sqrtPriceX96: int, tick: int, L: int, ticks: List[Dict[str, int]], pct_list=(Decimal('0.02'), Decimal('0.05'), Decimal('0.10')), fee_bps: int = 3000) -> Dict[str, Dict[str, float]]:
    """Compute quote notional required to move the mid by +/- given percentages.

    Returns dict: {'up': {'pct2':..., 'pct5':..., 'pct10':...}, 'down': {...}}

    Fee is applied on input leg, so we gross-up inputs by 1/(1-fee).

    """
    S = sqrtX96_to_unscaled_sqrt(sqrtPriceX96)
    ladder = TickLadder(ticks)
    Ld = Decimal(L)
    fee = Decimal(fee_bps) / Decimal(1_000_000)

    out = {"up": {}, "down": {}}
    for pct in pct_list:
        target_up = S * ( (Decimal(1) + pct) ** Decimal(0.5) )
        dy_eff, _ = _walk_up_to_s(S, target_up, Ld, ladder, tick)
        # gross-up for fee, since fee charged on token1 in (quote in) for upward move
        dy_in = dy_eff / (Decimal(1) - fee)
        out["up"][f"pct{int(pct*100)}"] = float(dy_in)

        target_down = S / ( (Decimal(1) + pct) ** Decimal(0.5) )
        dx_eff, _ = _walk_down_to_s(S, target_down, Ld, ladder, tick)
        dx_in = dx_eff / (Decimal(1) - fee)  # base in
        # We'll return base input in token0 units; caller converts to quote notional
        out["down"][f"pct{int(pct*100)}"] = float(dx_in)
    return out

def slippage_curve_for_quote_in(sqrtPriceX96: int, tick: int, L: int, ticks: List[Dict[str, int]], trade_sizes_quote: List[float], fee_bps: int = 3000) -> List[Dict[str, float]]:
    """Simulate quote->base trades (token1 in) and compute end-price slippage in percent.

    Returns list of {'notionalQuote': size_quote, 'slippagePct': pct_float}.

    """
    S0 = sqrtX96_to_unscaled_sqrt(sqrtPriceX96)
    ladder = TickLadder(ticks)
    Ld = Decimal(L)
    fee = Decimal(fee_bps) / Decimal(1_000_000)
    out = []
    for size in trade_sizes_quote:
        dy_raw = Decimal(size)
        dy_eff_remaining = dy_raw * (Decimal(1) - fee)
        cursorS = S0
        tick_cursor = tick
        Lc = Ld
        # Walk upward consuming effective input
        while dy_eff_remaining > 0:
            next_tick = ladder.next_tick_above(tick_cursor) if ladder else None
            step_end_S = None
            if next_tick is not None:
                next_tick_S = sqrt_price_at_tick_unscaled(next_tick)
                step_end_S = next_tick_S
            # Maximum effective dy to reach boundary
            if step_end_S is None or step_end_S <= cursorS:
                # Safeguard
                step_end_S = cursorS * Decimal(1.0000000001)
            dy_max = Lc * (step_end_S - cursorS)
            if dy_eff_remaining <= dy_max:
                # end inside the current segment
                S_end = cursorS + (dy_eff_remaining / Lc)
                dy_eff_remaining = Decimal(0)
                cursorS = S_end
            else:
                # consume segment and cross
                dy_eff_remaining -= dy_max
                cursorS = step_end_S
                if next_tick is not None and cursorS == next_tick_S:
                    i = ladder.index_by_tick[next_tick]
                    Lc += Decimal(ladder.ticks[i]['liquidityNet'])
                    tick_cursor = next_tick
                else:
                    break
        P0 = S0 * S0
        Pend = cursorS * cursorS
        slippagePct = ((Pend - P0) / P0) * Decimal(100)
        out.append({"notionalQuote": float(dy_raw), "slippagePct": float(slippagePct)})
    return out
