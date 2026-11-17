"""Input validators. No network, no crypto libs."""

import re

BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_pubkey(s: str) -> bool:
    return bool(BASE58_RE.match(s or ""))


def is_positive_float(s, *, max_val: float = None) -> bool:
    try:
        v = float(s)
    except (TypeError, ValueError):
        return False
    if v <= 0:
        return False
    if max_val is not None and v > max_val:
        return False
    return True


def is_lamports(s) -> bool:
    try:
        return int(s) >= 0
    except (TypeError, ValueError):
        return False


def parse_sol(s) -> float:
    if not is_positive_float(s):
        raise ValueError(f"invalid SOL amount: {s!r}")
    return float(s)


def parse_pct(s) -> float:
    """Parse '25%' or '0.25' or '25' → 0.25."""
    text = str(s).strip().rstrip("%")
    v = float(text)
    return v / 100.0 if v > 1 else v