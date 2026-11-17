"""Display formatting for addresses, token amounts, timestamps, durations."""

from datetime import datetime, timezone


def short_addr(addr: str, n: int = 4) -> str:
    if not addr or len(addr) <= 2 * n + 1:
        return addr or "—"
    return f"{addr[:n]}…{addr[-n:]}"


def fmt_token_amount(amount, decimals: int = 6, precision: int = 4) -> str:
    try:
        scaled = float(amount) / (10 ** decimals)
    except (TypeError, ValueError):
        return "—"
    if scaled >= 1_000_000:
        return f"{scaled/1_000_000:.{precision}f}M"
    if scaled >= 1_000:
        return f"{scaled/1_000:.{precision}f}K"
    return f"{scaled:.{precision}f}"


def fmt_timestamp(ts) -> str:
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError):
        return "—"


def fmt_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86_400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86_400}d {(seconds % 86_400) // 3600}h"


def fmt_price(px: float) -> str:
    if px == 0:
        return "0"
    if px < 1e-9:
        return f"{px:.3e}"
    if px < 1e-3:
        return f"{px:.8f}"
    return f"{px:.6f}"