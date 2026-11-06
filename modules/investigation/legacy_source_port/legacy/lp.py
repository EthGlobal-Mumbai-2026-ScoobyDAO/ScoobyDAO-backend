from __future__ import annotations
from typing import Dict
from collections import defaultdict
def lp_concentration(subgraph_url: str, pool_id_lower: str, current_tick: int) -> Dict[str, float]:
    g = GraphQLClient(subgraph_url)
    pool_id_lower = pool_id_lower.lower()  # ensure lowercase for subgraph

    owners = defaultdict(int)
    total_L = 0

    positions = _fetch_positions_any(g, pool_id_lower, current_tick)

    for p in positions:
      rawL = p.get("liquidity", 0)
      try:
          L = int(rawL)
      except Exception:
          L = int(str(rawL or "0"))
      if L <= 0:
          continue
      owners[p.get("owner","0x0")] += L
      total_L += L


    if total_L == 0 or not owners:
        return {"top1Share": 0.0, "top5Share": 0.0, "hhi": 0.0, "sampledPositions": 0.0}

    values = sorted(owners.values(), reverse=True)
    shares = [v / total_L for v in values]
    top1 = shares[0] if shares else 0.0
    top5 = sum(shares[:5]) if len(shares) >= 5 else sum(shares)
    hhi = sum(s*s for s in shares)

    return {
        "top1Share": float(top1),
        "top5Share": float(top5),
        "hhi": float(hhi),
        "sampledPositions": float(len(values))
    }
