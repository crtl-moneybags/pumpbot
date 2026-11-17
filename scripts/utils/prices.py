"""Display-only bonding-curve math.

These are the standard constant-product formulas used by every DEX UI to show
price impact and expected output. They are pure functions — no RPC, no signing,
no submissions. Use them in `monitor`, `paper`, and `backtest` to render what a
trade *would* have done.
"""


def price(sol_reserve: float, token_reserve: float) -> float:
    """Marginal price of 1 token expressed in SOL."""
    if token_reserve <= 0:
        return 0.0
    return sol_reserve / token_reserve


def market_cap(px: float, total_supply: float) -> float:
    return px * total_supply


def buy_out(sol_in: float, sol_reserve: float, token_reserve: float) -> float:
    """Tokens out for a constant-product buy."""
    if sol_in <= 0 or sol_reserve <= 0:
        return 0.0
    k = sol_reserve * token_reserve
    return token_reserve - k / (sol_reserve + sol_in)


def sell_out(token_in: float, sol_reserve: float, token_reserve: float) -> float:
    """SOL out for a constant-product sell."""
    if token_in <= 0 or token_reserve <= 0:
        return 0.0
    k = sol_reserve * token_reserve
    return sol_reserve - k / (token_reserve + token_in)


def impact(sol_in: float, sol_reserve: float) -> float:
    """Fractional price impact of a buy against a pool."""
    if sol_reserve <= 0:
        return 0.0
    return sol_in / (sol_reserve + sol_in)


def sol_for_mc(target_mc: float, total_supply: float,
               sol_reserve: float, token_reserve: float) -> float:
    """Rough SOL needed to push market cap to `target_mc` (display only)."""
    if total_supply <= 0 or token_reserve <= 0:
        return 0.0
    target_px = target_mc / total_supply
    target_tokens_remaining = sol_reserve / target_px if target_px > 0 else 0
    tokens_to_buy = max(token_reserve - target_tokens_remaining, 0.0)
    if tokens_to_buy <= 0:
        return 0.0
    k = sol_reserve * token_reserve
    return k / (token_reserve - tokens_to_buy) - sol_reserve