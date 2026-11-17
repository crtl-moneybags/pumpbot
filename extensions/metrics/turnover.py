

from extensions.registry import REGISTRY


@REGISTRY.metric("turnover")
def compute(events: list[dict], **_) -> dict:
    if not events:
        return {"turnover": 0.0}
    total = 0.0
    for e in events:
        liq = e.get("liquidity_sol", 0)
        if liq > 0:
            total += e.get("market_cap_sol", 0) / liq
    return {"turnover": round(total, 4)}