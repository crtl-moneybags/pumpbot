from extensions.registry import REGISTRY


@REGISTRY.metric("basic")
def compute(events: list[dict], **_) -> dict:
    if not events:
        return {"count": 0}
    mcs = [e["market_cap_sol"] for e in events]
    liqs = [e["liquidity_sol"] for e in events]
    n = len(events)
    return {
        "count": n,
        "min_mc": round(min(mcs), 4),
        "max_mc": round(max(mcs), 4),
        "avg_mc": round(sum(mcs) / n, 4),
        "min_liquidity": round(min(liqs), 4),
        "max_liquidity": round(max(liqs), 4),
        "avg_liquidity": round(sum(liqs) / n, 4),
    }