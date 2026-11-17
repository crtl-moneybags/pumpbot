"""Position sizing and risk math (display-only; never adjusts wallets)."""


def size_position(balance_sol: float, risk_pct: float, stop_loss_pct: float) -> float:
    """SOL to risk such that a stop-loss hit costs exactly `risk_pct` of balance."""
    if stop_loss_pct <= 0:
        return 0.0
    return max(balance_sol * risk_pct / stop_loss_pct, 0.0)


def max_loss(sol_in: float, stop_loss_pct: float) -> float:
    return sol_in * stop_loss_pct


def r_multiple(entry: float, exit_: float, stop: float) -> float:
    risk = entry - stop
    if risk == 0:
        return 0.0
    return (exit_ - entry) / risk


def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """Kelly stake as a fraction of bankroll, clamped to [0, 0.25] for safety."""
    if win_loss_ratio <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / win_loss_ratio
    return min(max(f, 0.0), 0.25)


def drawdown(peak: float, current: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)