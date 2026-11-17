
from extensions.registry import REGISTRY


@REGISTRY.strategy("take_profit")
def build(ctx: dict) -> dict:
    min_liq = ctx.get("min_liquidity_sol", 5.0)
    max_mc = ctx.get("max_entry_mc_sol", 50.0)
    tp = ctx.get("take_profit_pct", 0.25)
    sl = ctx.get("stop_loss_pct", 0.15)

    def enter(ev: dict) -> bool:
        return (
            ev.get("liquidity_sol", 0) >= min_liq
            and ev.get("market_cap_sol", 0) <= max_mc
        )

    def exit(pos: dict, ev: dict):
        entry = pos.get("entry_mc_sol", 0)
        cur = ev.get("market_cap_sol", 0)
        if entry <= 0:
            return None
        pnl = (cur / entry) - 1
        if pnl >= tp:
            return "tp"
        if pnl <= -sl:
            return "sl"
        return None

    return {"enter": enter, "exit": exit}