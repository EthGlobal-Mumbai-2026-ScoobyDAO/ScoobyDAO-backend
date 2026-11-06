from __future__ import annotations
from decimal import Decimal,getcontext
from typing import Tuple
getcontext().prec=80
Q96=Decimal(2)**96
ONE_BPS=Decimal(1)/Decimal(10000)
def sqrtX96_to_unscaled_sqrt(sqrtX96: int) -> Decimal:
    return Decimal(sqrtX96) / Q96

def unscaled_sqrt_to_sqrtX96(s: Decimal) -> int:
    return int((s * Q96).to_integral_value(rounding="ROUND_FLOOR"))

def price_from_sqrtX96(sqrtX96: int, decimals0: int, decimals1: int, base_is_token0: bool, quote_is_token1: bool) -> Decimal:
    """Return price = quote per base in human units.

    - sqrtX96 is Uniswap v3 sqrtPriceX96
    - decimals0, decimals1 are token decimals
    - base_is_token0 indicates whether 'base' in the requested pair equals pool.token0
    - quote_is_token1 indicates whether 'quote' equals pool.token1

    We compute raw price r = token1/token0 (contract units). The human price must
    adjust for decimals and orientation.
    """
    s = sqrtX96_to_unscaled_sqrt(sqrtX96)
    raw = s * s  # token1 per token0 (contract units)
    # adjust for decimals to human units
    scale = Decimal(10) ** Decimal(decimals0 - decimals1)
    token1_per_token0_human = raw * scale

    if base_is_token0 and quote_is_token1:
        return token1_per_token0_human
    elif (not base_is_token0) and (not quote_is_token1):
        # price should be token0 per token1
        return Decimal(1) / token1_per_token0_human
    elif base_is_token0 and (not quote_is_token1):
        # quote is token0, base is token0 -> invalid orientation; return 1
        return Decimal(1)
    else:
        # base is token1, quote is token1 -> price = 1
        return Decimal(1)

def sqrt_price_at_tick_unscaled(tick: int) -> Decimal:
    """Unscaled sqrt price S = sqrt(1.0001 ** tick).
    This ignores token decimals and Q96 scaling; consistent with formulas in spec.
    """
    # Using Decimal exponent for precision
    base = Decimal('1.0001')
    return base ** (Decimal(tick) / Decimal(2))

def price_at_tick_human(tick: int, decimals0: int, decimals1: int, base_is_token0: bool, quote_is_token1: bool) -> Decimal:
    s = sqrt_price_at_tick_unscaled(tick)
    raw = s * s
    scale = Decimal(10) ** Decimal(decimals0 - decimals1)
    token1_per_token0 = raw * scale
    if base_is_token0 and quote_is_token1:
        return token1_per_token0
    else:
        return Decimal(1) / token1_per_token0

def to_float(d: Decimal) -> float:
    try:
        return float(d)
    except Exception:
        # Clamp if out-of-float-range
        return float(d.quantize(Decimal('1.000000000000000000')))
