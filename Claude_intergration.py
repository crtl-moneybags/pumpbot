

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit(
        'Missing dependency. Install it with: python3 -m pip install "mcp[cli]"'
    ) from exc


ROOT = Path(os.environ.get("PUMPBOT_ROOT", Path.cwd())).expanduser().resolve()
DB_PATH = ROOT / "pumpbot.db"

mcp = FastMCP("pumpbot")

# In-memory paper account only. It is reset whenever this MCP process restarts.
PAPER_START_SOL = float(os.environ.get("PUMPBOT_PAPER_START_SOL", "10"))
_paper_balance = PAPER_START_SOL
_paper_positions: dict[str, dict[str, Any]] = {}
_paper_history: list[dict[str, Any]] = []
_paper_lock = Lock()

SECRET_KEY_PATTERN = re.compile(
    r"(secret|private|seed|mnemonic|api.?key|token|password|credential)",
    re.IGNORECASE,
)
ADDRESS_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _safe_path(relative_path: str) -> Path:
    """Resolve a repository path and reject traversal/out-of-root paths."""
    candidate = (ROOT / relative_path).resolve()
    if candidate != ROOT and ROOT not in candidate.parents:
        raise ValueError("Path is outside the configured PumpBot repository.")
    if not candidate.exists():
        raise FileNotFoundError(f"Not found in repository: {relative_path}")
    if not candidate.is_file():
        raise ValueError("Only files can be read.")
    if candidate.name.lower() in {".env", ".env.local", "id.json", "wallet.json"}:
        raise ValueError("Sensitive wallet/environment files cannot be read.")
    return candidate


def _redact(value: Any, key: str = "") -> Any:
    """Recursively redact likely secrets before returning config values."""
    if SECRET_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value


@mcp.tool()
def pumpbot_overview() -> dict[str, Any]:
    """Return repository layout and key project files; does not execute PumpBot."""
    if not ROOT.is_dir():
        raise ValueError(f"PUMPBOT_ROOT is not a directory: {ROOT}")

    files: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if len(files) < 300:
            files.append(rel)

    return {
        "repository_root": str(ROOT),
        "files": sorted(files),
        "entry_point_exists": (ROOT / "main.py").is_file(),
        "database_exists": DB_PATH.is_file(),
        "note": (
            "This bridge exposes repository inspection and paper simulation only. "
            "It does not execute live trades or MEV/sniping workflows."
        ),
    }


@mcp.tool()
def pumpbot_read_source(relative_path: str, max_chars: int = 16000) -> str:
    """
    Read a non-secret source/config/documentation file inside the repository.
    Use for code understanding. Never use this to retrieve credentials.
    """
    if max_chars < 1 or max_chars > 30000:
        raise ValueError("max_chars must be between 1 and 30000.")
    path = _safe_path(relative_path)
    if path.suffix.lower() not in {
        ".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg"
    }:
        raise ValueError("Unsupported file type for this read-only tool.")
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars] + ("\n...[truncated]" if len(text) > max_chars else "")


@mcp.tool()
def pumpbot_config_summary() -> dict[str, Any]:
    """Read YAML config files and return values with secret-like keys redacted."""
    try:
        import yaml
    except ImportError:
        return {
            "error": "PyYAML is not installed. Install with: python3 -m pip install PyYAML"
        }

    config_dir = ROOT / "config"
    if not config_dir.is_dir():
        return {"error": "No config/ directory found.", "repository_root": str(ROOT)}

    result: dict[str, Any] = {}
    for path in sorted(config_dir.glob("*.y*ml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            result[path.name] = _redact(raw)
        except Exception as exc:
            result[path.name] = {"error": f"Could not parse YAML: {type(exc).__name__}"}
    return result


@mcp.tool()
def pumpbot_database_summary() -> dict[str, Any]:
    """
    Return SQLite table names, column names, and row counts only.
    Does not expose row contents or modify the database.
    """
    if not DB_PATH.is_file():
        return {"error": "pumpbot.db was not found.", "database": str(DB_PATH)}

    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=3)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        summary = []
        for (table_name,) in tables:
            # Table names originate from sqlite_master; quote safely.
            quoted = '"' + table_name.replace('"', '""') + '"'
            columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            summary.append({
                "table": table_name,
                "columns": [column[1] for column in columns],
                "row_count": count,
            })
        return {"database": str(DB_PATH), "tables": summary, "read_only": True}
    finally:
        conn.close()


@mcp.tool()
def paper_account_status() -> dict[str, Any]:
    """Show the isolated in-memory paper account; no wallet or RPC is accessed."""
    with _paper_lock:
        return {
            "mode": "PAPER_ONLY",
            "starting_balance_sol": PAPER_START_SOL,
            "balance_sol": round(_paper_balance, 9),
            "open_positions": _paper_positions.copy(),
            "trade_count": len(_paper_history),
        }


@mcp.tool()
def paper_buy(token_mint: str, sol_amount: float, simulated_token_price: float) -> dict[str, Any]:
    """
    Simulate a buy in the isolated paper ledger.
    Prices and fills are user-supplied assumptions; no market API is called.
    """
    global _paper_balance

    if not ADDRESS_PATTERN.fullmatch(token_mint):
        raise ValueError("token_mint must look like a Solana base58 address.")
    if not (0 < sol_amount <= 1000):
        raise ValueError("sol_amount must be greater than 0 and at most 1000.")
    if not (simulated_token_price > 0):
        raise ValueError("simulated_token_price must be positive.")

    with _paper_lock:
        if sol_amount > _paper_balance:
            raise ValueError("Insufficient paper SOL balance.")
        tokens = sol_amount / simulated_token_price
        position = _paper_positions.setdefault(
            token_mint, {"token_mint": token_mint, "tokens": 0.0, "cost_sol": 0.0}
        )
        position["tokens"] += tokens
        position["cost_sol"] += sol_amount
        _paper_balance -= sol_amount

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "PAPER_ONLY",
            "side": "BUY",
            "token_mint": token_mint,
            "sol_amount": sol_amount,
            "simulated_token_price": simulated_token_price,
            "simulated_tokens_received": tokens,
        }
        _paper_history.append(record)
        return record


@mcp.tool()
def paper_sell(token_mint: str, token_amount: float, simulated_token_price: float) -> dict[str, Any]:
    """
    Simulate a sale from the isolated paper ledger.
    No transaction is signed or broadcast.
    """
    global _paper_balance

    if not ADDRESS_PATTERN.fullmatch(token_mint):
        raise ValueError("token_mint must look like a Solana base58 address.")
    if not (token_amount > 0):
        raise ValueError("token_amount must be positive.")
    if not (simulated_token_price > 0):
        raise ValueError("simulated_token_price must be positive.")

    with _paper_lock:
        position = _paper_positions.get(token_mint)
        if not position or token_amount > position["tokens"]:
            raise ValueError("Not enough tokens in the paper position.")

        sol_received = token_amount * simulated_token_price
        average_cost = position["cost_sol"] / position["tokens"]
        cost_basis = average_cost * token_amount
        pnl = sol_received - cost_basis

        position["tokens"] -= token_amount
        position["cost_sol"] -= cost_basis
        if position["tokens"] <= 1e-12:
            del _paper_positions[token_mint]

        _paper_balance += sol_received
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "PAPER_ONLY",
            "side": "SELL",
            "token_mint": token_mint,
            "token_amount": token_amount,
            "simulated_token_price": simulated_token_price,
            "simulated_sol_received": sol_received,
            "estimated_realized_pnl_sol": pnl,
        }
        _paper_history.append(record)
        return record


@mcp.tool()
def paper_trade_history(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent simulated trades from this MCP process."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500.")
    with _paper_lock:
        return _paper_history[-limit:]


@mcp.tool()
def paper_reset(confirm: bool) -> dict[str, Any]:
    """Reset the paper account. Requires confirm=true. This never touches real funds."""
    global _paper_balance
    if confirm is not True:
        raise ValueError("Set confirm=true to reset the simulated account.")
    with _paper_lock:
        _paper_balance = PAPER_START_SOL
        _paper_positions.clear()
        _paper_history.clear()
    return {"reset": True, "mode": "PAPER_ONLY", "balance_sol": PAPER_START_SOL}


if __name__ == "__main__":
    if not ROOT.is_dir():
        raise SystemExit(
            f"PumpBot repository not found at {ROOT}. Set PUMPBOT_ROOT to its path."
        )
    mcp.run(transport="stdio")
