
from extensions.registry import REGISTRY


@REGISTRY.strategy("ladder")
def build(ctx: dict) -> dict:
    min_liq = ctx.get("min_liquidity_sol", 5.0)
    max_mc = ctx.get("max_entry_mc_sol", 50.0)
    stop = ctx.get("stop_loss_pct", 0.15)
    levels = ctx.get("tp_levels", [0.15, 0.30, 0.60])

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

        stepped = pos.get("stepped", 0)
        while stepped < len(levels) and pnl >= levels[stepped]:
            stepped += 1
            pos["stepped"] = stepped
            return f"tp_{stepped}"

        if pnl <= -stop:
            return "sl"
        return None

    return {"enter": enter, "exit": exit}