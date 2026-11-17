#!/usr/bin/env python3
"""
pump-research · safe read-only pump.fun research CLI

Interactive mode:
  python main.py            → REPL (wallet-gated; only `connect` works pre-connect)

Single-shot:
  python main.py <command> [options]

Commands:
  connect     connect a wallet (opens a URL, stores public address only)
  disconnect  clear the local session
  status      show session state
  monitor     read-only event monitor
  paper       paper-trading simulator (no wallet, no signing)
  backtest    offline backtest over observed events
  config      show safety/config settings

Placeholder commands (inert, no logic):
  snipe, mev, trade, bundle

Connect URL:
  --url <url>   the URL that `connect` should open. Saved to
                ~/.pump_research/config.json so plain `connect` reuses it.
                Also reads $PUMP_CONNECT_URL.

Local page (when no --url is set):
  Serves on a fixed port (default 5500; override with --port).

  Page resolution at `/`:
    1. widget/main.html      — your page, with `state`/`callback` injected
    2. widget/wallet-connect.js present — generated widget page
    3. otherwise             — built-in manual-address form

  Files are looked up in widget/ first, then scripts/ as a fallback.
  All of `/wallet-connect.js`, `/widget.js`, and any other file under
  widget/ or scripts/ is served on the same port. The injected `state`
  is readable by your widget via window.__PUMP_STATE__ /
  <meta name="pump-state">, and the callback endpoint is
  window.__PUMP_CALLBACK__ ("/callback"). POST or GET `state` +
  `address` there to complete the connect.

Intentionally NOT implemented:
  auto-buy, order signing, transaction submission, MEV, bundling.
Wallet connect stores ONLY a public address. No private keys are read.
"""

import argparse
import json
import os
import re
import secrets
import shlex
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import urlparse, parse_qs


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------

def _enable_ansi_windows() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        pass


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class _C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; MAGENTA = "\033[35m"; CYAN = "\033[36m"
    GREY = "\033[90m"


def _plain_c():
    class P:
        RESET = BOLD = DIM = RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = GREY = ""
    return P


C = _C
EMOJI_ON = True

E = {
    "rocket": "🚀", "wallet": "👛", "lock": "🔒", "unlock": "🔓",
    "watch": "👀", "paper": "🧪", "hist": "📊", "cfg": "⚙️",
    "ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️",
    "snipe": "🎯", "mev": "⚡", "trade": "💱", "bundle": "📦",
    "coin": "🪙", "clock": "🕒", "off": "⏻", "spark": "✨",
    "gate": "🛡️", "link": "🔗",
}


def emo(key: str) -> str:
    return E.get(key, "") if EMOJI_ON else ""


def _paint(text: str, color: str) -> str:
    return f"{color}{text}{C.RESET}" if color else text


def header(title: str, icon: str = "") -> None:
    icon_part = f"{icon} " if icon else ""
    line = f"{icon_part}{title}"
    bar = "─" * max(28, len(line) + 2)
    print()
    print(_paint(f"╭{bar}╮", C.CYAN))
    print(_paint(f"│ {line}", C.CYAN))
    print(_paint(f"╰{bar}╯", C.CYAN))


def divider() -> None:
    print(_paint("─" * 54, C.GREY))


def ok(msg: str) -> None:
    print(f"{emo('ok')} {_paint(msg, C.GREEN)}")


def warn(msg: str) -> None:
    print(f"{emo('warn')} {_paint(msg, C.YELLOW)}")


def err(msg: str) -> None:
    print(f"{emo('err')} {_paint(msg, C.RED)}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"{emo('info')} {msg}")


def kv(key: str, value: str) -> None:
    print(f"   {_paint(key.ljust(14), C.GREY)} {value}")


def table(headers: list[str], rows: list[list[str]], aligns: Optional[list[str]] = None) -> None:
    aligns = aligns or ["left"] * len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(cells):
        out = []
        for i, cell in enumerate(cells):
            s = str(cell)
            out.append(s.rjust(widths[i]) if aligns[i] == "right" else s.ljust(widths[i]))
        return " │ ".join(out)

    top = "┌─" + "─┬─".join("─" * w for w in widths) + "─┐"
    mid = "├─" + "─┼─".join("─" * w for w in widths) + "─┤"
    bot = "└─" + "─┴─".join("─" * w for w in widths) + "─┘"

    print(_paint(top, C.GREY))
    print(_paint("│ " + fmt(headers) + " │", C.BOLD + C.CYAN))
    print(_paint(mid, C.GREY))
    for row in rows:
        print("│ " + fmt(row) + " │")
    print(_paint(bot, C.GREY))


def banner() -> None:
    print(_paint("━" * 54, C.MAGENTA))
    print(_paint(f"  {emo('rocket')}  pump-research", C.BOLD + C.MAGENTA))
    print(_paint(f"     safe read-only research CLI · solana", C.GREY))
    print(_paint("━" * 54, C.MAGENTA))


def welcome() -> None:
    divider()
    rows = [
        [emo("wallet"), "connect",    "connect a wallet (opens a URL)"],
        [emo("lock"),   "status",     "show session state"],
        [emo("off"),    "disconnect", "clear the session"],
        [emo("watch"),  "monitor",    "read-only event monitor"],
        [emo("paper"),  "paper",      "paper-trading simulator"],
        [emo("hist"),   "backtest",   "offline backtest"],
        [emo("cfg"),    "config",     "show safety/config"],
        [emo("snipe"),  "snipe",      "placeholder"],
        [emo("mev"),    "mev",        "placeholder"],
        [emo("trade"),  "trade",      "placeholder"],
        [emo("bundle"), "bundle",     "placeholder"],
    ]
    table(["", "COMMAND", "DESCRIPTION"], rows, aligns=["left", "left", "left"])
    print(f"   {_paint('Type', C.GREY)} {_paint('connect', C.CYAN)} "
          f"{_paint('to link a wallet. Type', C.GREY)} {_paint('help', C.CYAN)} "
          f"{_paint('or', C.GREY)} {_paint('exit', C.CYAN)} {_paint('anytime.', C.GREY)}")
    print(f"   {_paint('Set the connect URL:', C.GREY)} "
          f"{_paint('connect --url <url>', C.CYAN)}")
    print(f"   {_paint('Local page:', C.GREY)} "
          f"{_paint('widget/main.html', C.CYAN)} "
          f"{_paint(f'(served at /, port {CONNECT_PORT})', C.GREY)}")
    divider()


# --------------------------------------------------------------------------
# Session + config storage
# --------------------------------------------------------------------------

SESSION_DIR = os.path.expanduser("~/.pump_research")
SESSION_PATH = os.path.join(SESSION_DIR, "session.json")
CONFIG_PATH = os.path.join(SESSION_DIR, "config.json")
DEFAULT_TTL = 24 * 3600
CONNECT_PORT = 5500   # fixed port for the local server

BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def is_valid_pubkey(s: str) -> bool:
    return bool(BASE58_RE.match(s or ""))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_session(address: str, ttl: int) -> None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    data = {
        "address": address,
        "connected_at": now_iso(),
        "expires_at": time.time() + ttl,
    }
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(SESSION_PATH, 0o600)
    except OSError:
        pass


def load_session() -> Optional[dict]:
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear_session() -> None:
    try:
        os.remove(SESSION_PATH)
    except FileNotFoundError:
        pass


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def is_connected() -> tuple[bool, Optional[dict]]:
    s = load_session()
    if not s:
        return False, None
    if time.time() >= float(s.get("expires_at", 0)):
        return False, s
    return True, s


def require_session() -> dict:
    connected, s = is_connected()
    if not connected:
        print()
        err("No wallet connected.")
        print(f"   {emo('link')} Run: {_paint('python main.py connect', C.CYAN)}")
        print(f"   {_paint('Then re-run this command.', C.GREY)}")
        sys.exit(1)
    return s


# --------------------------------------------------------------------------
# Static assets: widget/ (primary) + scripts/ (fallback)
# --------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
WIDGET_DIR  = os.path.abspath(os.path.join(_HERE, "widget"))
SCRIPTS_DIR = os.path.abspath(os.path.join(_HERE, "scripts"))

MAIN_HTML_NAME = "main.html"
WALLET_JS_NAME = "wallet-connect.js"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm":  "text/html; charset=utf-8",
    ".js":   "text/javascript; charset=utf-8",
    ".mjs":  "text/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map":  "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".ico":  "image/x-icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2":"font/woff2",
    ".ttf":  "font/ttf",
    ".txt":  "text/plain; charset=utf-8",
    ".wasm": "application/wasm",
}


def _safe_join(root: str, rel: str) -> Optional[str]:
    """Resolve rel under root; return None on traversal."""
    rel = rel.lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return None
    target = os.path.abspath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        return None
    return target


def _find_file(rel: str) -> Optional[str]:
    """Return first existing file under widget/, then scripts/."""
    for root in (WIDGET_DIR, SCRIPTS_DIR):
        target = _safe_join(root, rel)
        if target and os.path.isfile(target):
            return target
    return None


def has_main_html() -> bool:
    return _find_file(MAIN_HTML_NAME) is not None


def has_widget() -> bool:
    return _find_file(WALLET_JS_NAME) is not None


# --------------------------------------------------------------------------
# Wallet connect flow (public address only)
# --------------------------------------------------------------------------

CONNECT_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Connect Wallet · pump-research</title>
<style>
 :root{color-scheme:dark}
 body{font-family:ui-sans-serif,system-ui,sans-serif;max-width:540px;margin:64px auto;
      padding:0 20px;background:#0d1117;color:#e6edf3}
 h1{font-size:22px;margin:0 0 4px}
 p.sub{color:#8b949e;margin:0 0 22px;font-size:14px}
 input,button{font-size:15px;padding:11px 13px;width:100%;box-sizing:border-box;
              border-radius:8px;border:1px solid #30363d;background:#161b22;color:#e6edf3}
 input:focus{outline:none;border-color:#8957e5;box-shadow:0 0 0 3px #8957e522}
 button{margin-top:10px;background:#8957e5;border-color:#8957e5;font-weight:600;cursor:pointer}
 button:hover{background:#9d6cf0}
 code{background:#161b22;padding:2px 6px;border-radius:4px;font-size:12px;color:#8b949e}
 .hint{font-size:13px;color:#8b949e;margin-top:16px}
</style></head>
<body>
<h1>👛 Connect Wallet</h1>
<p class="sub">Paste your Solana <b>public</b> address. This tool never asks for a
private key or seed phrase and does not sign transactions.</p>
<form method="POST" action="/callback">
  <input type="hidden" name="state" value="__STATE__">
  <input name="address" placeholder="e.g. 7xKX…9Qm" autofocus required>
  <button type="submit">Connect</button>
</form>
<p class="hint">Stored at <code>~/.pump_research/session.json</code> · expires automatically.</p>
</body></html>
"""

WIDGET_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Connect Wallet · pump-research</title>
<meta name="pump-state" content="__STATE__">
<meta name="pump-callback" content="/callback">
<script>
  window.__PUMP_STATE__ = "__STATE__";
  window.__PUMP_CALLBACK__ = "/callback";
</script>
<style>
 :root{color-scheme:dark}
 body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0d1117;color:#e6edf3;
      max-width:640px;margin:48px auto;padding:0 20px}
 hr{border:0;border-top:1px solid #30363d;margin:28px 0 20px}
 details summary{cursor:pointer;color:#8b949e;font-size:13px}
 form{margin-top:14px}
 input,button{font-size:15px;padding:10px 12px;width:100%;box-sizing:border-box;
              border-radius:8px;border:1px solid #30363d;background:#161b22;
              color:#e6edf3;margin-top:8px}
 input:focus{outline:none;border-color:#8957e5;box-shadow:0 0 0 3px #8957e522}
 button{background:#8957e5;border-color:#8957e5;font-weight:600;cursor:pointer}
 button:hover{background:#9d6cf0}
 code{background:#161b22;padding:2px 6px;border-radius:4px;font-size:12px;color:#8b949e}
</style></head>
<body>
<div id="solana-payment"></div>
<script type="module" src="/wallet-connect.js"></script>

<hr>
<details>
  <summary>Fallback: paste your Solana public address manually</summary>
  <form method="POST" action="/callback">
    <input type="hidden" name="state" value="__STATE__">
    <input name="address" placeholder="e.g. 7xKX…9Qm" required>
    <button type="submit">Connect</button>
  </form>
</details>
<p style="font-size:13px;color:#8b949e;margin-top:18px">
  Nothing is signed. Only the public address is stored, at
  <code>~/.pump_research/session.json</code>.
</p>
</body></html>
"""

CONNECT_OK = """<!doctype html><html><head><meta charset="utf-8">
<title>Connected</title>
<style>body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0d1117;color:#e6edf3;
text-align:center;margin:100px auto;max-width:480px}h1{font-size:22px}</style></head>
<body><h1>✅ Wallet connected</h1>
<p style="color:#8b949e">You can close this tab and return to the terminal.</p>
</body></html>"""


def _inject_state(html: str, state: str) -> str:
    """Add `state` and `callback` so wallet-connect.js can read them."""
    inject = (
        f'<meta name="pump-state" content="{state}">'
        f'<meta name="pump-callback" content="/callback">'
        f'<script>window.__PUMP_STATE__={json.dumps(state)};'
        f'window.__PUMP_CALLBACK__="/callback";</script>'
    )
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        return html[: m.end()] + inject + html[m.end():]
    return inject + html


def _prompt_for_address() -> Optional[str]:
    try:
        addr = input("   Paste Solana public address: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if is_valid_pubkey(addr):
        return addr
    err("Invalid Solana address.")
    return None


def run_local_connect(timeout: int, manual: bool, port: int = CONNECT_PORT) -> Optional[str]:
    """
    Fixed-port local server.
      /                 → widget/main.html if present, else generated page
      /wallet-connect.js, /widget.js, /<anything> → served from widget/, then scripts/
      /callback         → GET/POST `state` + `address`, validates, completes
    """
    state = secrets.token_urlsafe(24)
    result: dict = {}
    done = threading.Event()
    use_main = has_main_html()
    use_widget = has_widget()

    def _send(handler, body: bytes, ctype: str, code: int = 200) -> None:
        handler.send_response(code)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(body)

    def _serve_script(handler, rel: str) -> bool:
        target = _find_file(rel)
        if not target:
            return False
        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError:
            return False
        _send(handler, data, ctype)
        return True

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _ok(self):
            _send(self, CONNECT_OK.encode(), "text/html; charset=utf-8")

        def _err(self, msg: str, code: int = 400):
            _send(self, msg.encode(), "text/plain; charset=utf-8", code)

        def _handle(self, params: dict):
            if params.get("state", [""])[0] != state:
                return self._err("state mismatch")
            addr = params.get("address", [""])[0].strip()
            if not is_valid_pubkey(addr):
                return self._err("invalid Solana address")
            result["address"] = addr
            self._ok()
            done.set()

        def do_GET(self):
            u = urlparse(self.path)
            path = u.path

            if path == "/callback":
                return self._handle(parse_qs(u.query))

            if path == "/":
                if use_main:
                    main_path = _find_file(MAIN_HTML_NAME)
                    if not main_path:
                        return self._err(f"{MAIN_HTML_NAME} disappeared", 500)
                    try:
                        with open(main_path, "r", encoding="utf-8") as f:
                            body = f.read()
                    except OSError as e:
                        return self._err(f"cannot read {MAIN_HTML_NAME}: {e}", 500)
                    body = _inject_state(body, state)
                    return _send(self, body.encode("utf-8"),
                                 "text/html; charset=utf-8")
                page = WIDGET_PAGE if use_widget else CONNECT_PAGE
                return _send(self, page.replace("__STATE__", state).encode(),
                             "text/html; charset=utf-8")

            if path in ("/wallet-connect.js", "/widget.js"):
                if _serve_script(self, path[1:]):
                    return
                return self._err("not found", 404)

            if _serve_script(self, path):
                return

            return self._err("not found", 404)

        def do_POST(self):
            if urlparse(self.path).path != "/callback":
                return self._err("not found", 404)
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode("utf-8", "replace")
            return self._handle(parse_qs(body))

    try:
        srv = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        err(f"Cannot bind 127.0.0.1:{port} — {e}")
        info(f"Another process is probably already using port {port}.")
        info(f"Free it and retry, or run with --port <n>.")
        if manual:
            return _prompt_for_address()
        return None

    threading.Thread(target=srv.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    if use_main:
        p = _find_file(MAIN_HTML_NAME)
        info(f"Page: {_paint(os.path.relpath(p), C.CYAN)}")
    elif use_widget:
        p = _find_file(WALLET_JS_NAME)
        info(f"Widget: {_paint(os.path.relpath(p), C.CYAN)}")
    else:
        info("No widget files found — using built-in form.")
    info(f"Widget dir:  {_paint(WIDGET_DIR, C.GREY)}")
    info(f"Scripts dir: {_paint(SCRIPTS_DIR, C.GREY)}")
    info(f"Listening on {_paint(f'127.0.0.1:{port}', C.BOLD)}")
    info(f"Opening {_paint(url, C.CYAN)}")
    webbrowser.open(url)
    info(f"Waiting for wallet callback… {_paint(f'(timeout {timeout}s)', C.GREY)}")

    got = done.wait(timeout)
    srv.shutdown()
    srv.server_close()

    if got and "address" in result:
        return result["address"]

    warn(f"No address received within {timeout}s.")
    if manual:
        return _prompt_for_address()
    return None


def run_custom_connect(custom_url: str) -> Optional[str]:
    """Open the configured URL, then ask the user for their public address."""
    info(f"Opening {_paint(custom_url, C.CYAN)}")
    webbrowser.open(custom_url)
    info("Complete the connect step in your browser, then come back here.")
    return _prompt_for_address()


def cmd_connect(args) -> None:
    header("Connect Wallet", emo("wallet"))

    cfg = load_config()
    custom_url = (
        args.url
        or os.environ.get("PUMP_CONNECT_URL")
        or cfg.get("connect_url")
        or None
    )

    if args.url:
        cfg["connect_url"] = args.url
        save_config(cfg)
        ok(f"Saved default connect URL: {_paint(args.url, C.BOLD)}")

    if custom_url:
        address = run_custom_connect(custom_url)
    else:
        address = run_local_connect(args.timeout, args.manual, args.port)

    if not address:
        warn("Connect cancelled.")
        return
    save_session(address, args.ttl)
    divider()
    ok(f"Connected {_paint(address, C.BOLD)}")
    kv("Session", SESSION_PATH)
    kv("TTL", f"{args.ttl}s")


def cmd_disconnect(_args) -> None:
    header("Disconnect", emo("off"))
    existed = os.path.exists(SESSION_PATH)
    clear_session()
    (ok if existed else warn)("Session cleared" if existed else "No session to clear")


# --------------------------------------------------------------------------
# Data + read-only / paper commands
# --------------------------------------------------------------------------

@dataclass
class TokenEvent:
    mint: str
    symbol: str
    market_cap_sol: float
    liquidity_sol: float
    created_at: str


@dataclass
class PaperPosition:
    mint: str
    entry_mc_sol: float
    amount_sol: float
    opened_at: str
    exit_mc_sol: Optional[float] = None
    closed_at: Optional[str] = None


def load_events(path: str) -> list[TokenEvent]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        TokenEvent(
            mint=x["mint"],
            symbol=x.get("symbol", "UNKNOWN"),
            market_cap_sol=float(x["market_cap_sol"]),
            liquidity_sol=float(x["liquidity_sol"]),
            created_at=x.get("created_at", now_iso()),
        )
        for x in raw
    ]


def _short(mint: str, n: int = 6) -> str:
    return mint if len(mint) <= 2 * n + 3 else f"{mint[:n]}…{mint[-n:]}"


def cmd_monitor(args) -> None:
    header("Read-only Monitor", emo("watch"))
    kv("RPC", args.rpc)
    kv("Signing", _paint("disabled", C.GREEN))
    kv("Broadcast", _paint("disabled", C.GREEN))
    if not args.events:
        info("No --events file provided; nothing to display.")
        return
    events = load_events(args.events)
    kv("Events", str(len(events)))
    divider()
    for ev in events:
        print(
            f"{emo('coin')} {_paint(ev.symbol, C.BOLD)}  "
            f"{_short(ev.mint)}  "
            f"mc={_paint(f'{ev.market_cap_sol:.2f}', C.CYAN)} SOL  "
            f"liq={_paint(f'{ev.liquidity_sol:.2f}', C.CYAN)} SOL"
        )
        time.sleep(args.delay)


def cmd_paper(args) -> None:
    header("Paper Trading", emo("paper"))
    kv("Amount", f"{args.amount} SOL")
    kv("Min liq", f"{args.min_liquidity} SOL")
    kv("Max MC", f"{args.max_entry_mc} SOL")
    kv("TP / SL", f"{args.take_profit:.0%} / {args.stop_loss:.0%}")
    divider()

    positions: list[PaperPosition] = []
    for ev in load_events(args.events):
        if ev.liquidity_sol >= args.min_liquidity and ev.market_cap_sol <= args.max_entry_mc:
            positions.append(PaperPosition(
                mint=ev.mint, entry_mc_sol=ev.market_cap_sol,
                amount_sol=args.amount, opened_at=now_iso(),
            ))
            print(f"   {emo('spark')} OPEN  {_paint(ev.symbol, C.BOLD)}  "
                  f"@ {ev.market_cap_sol:.2f} SOL")

        for pos in positions:
            if pos.closed_at or ev.mint != pos.mint:
                continue
            pnl = (ev.market_cap_sol / pos.entry_mc_sol) - 1
            if pnl >= args.take_profit:
                pos.exit_mc_sol, pos.closed_at = ev.market_cap_sol, now_iso()
                print(f"   {emo('ok')} TP    {_paint(ev.symbol, C.BOLD)}  "
                      f"pnl={_paint(f'{pnl:+.2%}', C.GREEN)}")
            elif pnl <= -args.stop_loss:
                pos.exit_mc_sol, pos.closed_at = ev.market_cap_sol, now_iso()
                print(f"   {emo('err')} SL    {_paint(ev.symbol, C.BOLD)}  "
                      f"pnl={_paint(f'{pnl:+.2%}', C.RED)}")

    divider()
    if not positions:
        warn("No paper positions opened.")
        return

    rows, total_pnl = [], 0.0
    for pos in positions:
        closed = pos.closed_at is not None
        pnl = ((pos.exit_mc_sol / pos.entry_mc_sol) - 1) if closed else 0.0
        total_pnl += pnl
        rows.append([
            _short(pos.mint),
            "closed" if closed else "open",
            f"{pos.entry_mc_sol:.2f}",
            f"{pos.exit_mc_sol:.2f}" if closed else "—",
            f"{pnl:+.2%}" if closed else "—",
        ])
    table(["MINT", "STATUS", "ENTRY", "EXIT", "PNL"], rows,
          aligns=["left", "left", "right", "right", "right"])
    avg = total_pnl / len(positions)
    print(f"   {_paint('avg pnl', C.GREY)}  "
          f"{_paint(f'{avg:+.2%}', C.GREEN if avg >= 0 else C.RED)}  "
          f"{_paint(f'({len(positions)} positions)', C.GREY)}")


def cmd_backtest(args) -> None:
    header("Backtest", emo("hist"))
    events = load_events(args.events)
    if not events:
        warn("No events to backtest.")
        return
    mcs = [e.market_cap_sol for e in events]
    liqs = [e.liquidity_sol for e in events]
    kv("Events", str(len(events)))
    kv("First / last", f"{events[0].mint[:8]}… → {events[-1].mint[-8:]}…")
    divider()
    table(
        ["METRIC", "MIN", "MAX", "AVG"],
        [
            ["MC (SOL)", f"{min(mcs):.2f}", f"{max(mcs):.2f}", f"{sum(mcs)/len(mcs):.2f}"],
            ["LIQ (SOL)", f"{min(liqs):.2f}", f"{max(liqs):.2f}", f"{sum(liqs)/len(liqs):.2f}"],
        ],
        aligns=["left", "right", "right", "right"],
    )


def cmd_status(_args) -> None:
    header("Session Status", emo("lock"))
    connected, s = is_connected()
    if not connected:
        warn("Not connected.")
        print(f"   {emo('link')} Type {_paint('connect', C.CYAN)} to link a wallet.")
    else:
        remaining = max(int(float(s.get("expires_at", 0)) - time.time()), 0)
        ok("Connected")
        kv("Address", _paint(s.get("address", "—"), C.BOLD))
        kv("Since", s.get("connected_at", "—"))
        kv("Expires in", f"{remaining}s")

    cfg = load_config()
    url = os.environ.get("PUMP_CONNECT_URL") or cfg.get("connect_url")
    if url:
        kv("Connect URL", url)
    else:
        if has_main_html():
            kv("Local page", f"widget/{MAIN_HTML_NAME}")
        elif has_widget():
            kv("Local widget", f"widget/{WALLET_JS_NAME}")
        else:
            kv("Local page", "built-in form")
        kv("Port", str(CONNECT_PORT))


def cmd_config(args) -> None:
    header("Configuration", emo("cfg"))
    kv("RPC", args.rpc)
    kv("Mode", _paint("read-only / paper", C.GREEN))
    kv("Session", SESSION_PATH)
    kv("Config", CONFIG_PATH)
    kv("Widget dir", WIDGET_DIR)
    kv("Scripts dir", SCRIPTS_DIR)
    kv("Port", str(CONNECT_PORT))
    cfg = load_config()
    url = args.url or os.environ.get("PUMP_CONNECT_URL") or cfg.get("connect_url")
    kv("Connect URL", url or _paint("(none — local page)", C.GREY))
    kv("main.html", _paint("present", C.GREEN) if has_main_html()
       else _paint("missing", C.YELLOW))
    kv("wallet-connect.js", _paint("present", C.GREEN) if has_widget()
       else _paint("missing", C.YELLOW))
    divider()
    for label, value, good in [
        ("private keys", "never read", True),
        ("signing", "disabled", True),
        ("broadcast", "disabled", True),
        ("snipe", "placeholder", False),
        ("mev", "placeholder", False),
        ("trade", "placeholder", False),
        ("bundle", "placeholder", False),
    ]:
        mark = emo("ok") if good else emo("warn")
        tone = C.GREEN if good else C.YELLOW
        print(f"   {mark} {_paint(label.ljust(14), C.GREY)} {_paint(value, tone)}")


# --------------------------------------------------------------------------
# Placeholder commands (inert)
# --------------------------------------------------------------------------

PLACEHOLDER_COMMANDS = ("snipe", "mev", "trade", "bundle")
PLACEHOLDER_ICONS = {"snipe": "snipe", "mev": "mev", "trade": "trade", "bundle": "bundle"}


def cmd_placeholder(args) -> None:
    name = args.command
    _, s = is_connected()
    addr = (s or {}).get("address", "unknown")
    header(f"{name.capitalize()} · placeholder", emo(PLACEHOLDER_ICONS[name]))
    ok(f"Wallet connected: {_paint(addr, C.BOLD)}")
    warn(f"No {name} logic is implemented in this tool.")
    print(f"   {_paint('Nothing was signed, broadcast, or executed.', C.GREY)}")
    print(f"   {_paint('Placeholder command — safe by design.', C.GREY)}")


# --------------------------------------------------------------------------
# Parser + gate
# --------------------------------------------------------------------------

GATE_EXEMPT = {"connect", "disconnect", "status", "config"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]) or "pump-research",
        description=f"{emo('rocket')} Safe read-only pump.fun research CLI",
        epilog="No signing, no broadcasting, no sniping, no MEV, no bundling.",
    )
    parser.add_argument("--rpc", default="https://api.mainnet-beta.solana.com",
                        help="Solana RPC endpoint (read-only)")
    parser.add_argument("--plain", action="store_true",
                        help="disable color and emoji")

    sub = parser.add_subparsers(dest="command", required=False)

    con = sub.add_parser("connect", help=f"{emo('wallet')} connect a wallet (public address only)")
    con.add_argument("--timeout", type=int, default=180,
                     help="seconds to wait for the local widget callback")
    con.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    con.add_argument("--manual", action="store_true",
                     help="allow pasting an address as fallback")
    con.add_argument("--port", type=int, default=CONNECT_PORT,
                     help=f"port for the local server (default {CONNECT_PORT})")
    con.add_argument("--url", default=None,
                     help="the URL that `connect` should open. Saved to config, "
                          "so plain `connect` reuses it next time.")
    con.set_defaults(func=cmd_connect)

    sub.add_parser("disconnect", help=f"{emo('off')} clear the session").set_defaults(func=cmd_disconnect)
    sub.add_parser("status", help=f"{emo('lock')} show session state").set_defaults(func=cmd_status)
    sub.add_parser("config", help=f"{emo('cfg')} show safety/config").set_defaults(func=cmd_config)

    mon = sub.add_parser("monitor", help=f"{emo('watch')} read-only event monitor")
    mon.add_argument("--events")
    mon.add_argument("--delay", type=float, default=0.25)
    mon.set_defaults(func=cmd_monitor)

    paper = sub.add_parser("paper", help=f"{emo('paper')} paper-trading simulator")
    paper.add_argument("--events", required=True)
    paper.add_argument("--amount", type=float, default=0.1)
    paper.add_argument("--min-liquidity", type=float, default=5.0)
    paper.add_argument("--max-entry-mc", type=float, default=50.0)
    paper.add_argument("--take-profit", type=float, default=0.25)
    paper.add_argument("--stop-loss", type=float, default=0.15)
    paper.set_defaults(func=cmd_paper)

    bt = sub.add_parser("backtest", help=f"{emo('hist')} offline backtest")
    bt.add_argument("--events", required=True)
    bt.set_defaults(func=cmd_backtest)

    for name in PLACEHOLDER_COMMANDS:
        sp = sub.add_parser(
            name,
            help=f"{emo(PLACEHOLDER_ICONS[name])} placeholder: prompts to connect wallet",
        )
        sp.set_defaults(func=cmd_placeholder)

    return parser


# --------------------------------------------------------------------------
# REPL
# --------------------------------------------------------------------------

EXIT_TOKENS = {"exit", "quit", "q"}
HELP_TOKENS = {"help", "?", "commands"}


def _prompt() -> str:
    connected, s = is_connected()
    if connected:
        addr = s.get("address", "")
        short = (addr[:4] + "…" + addr[-4:]) if len(addr) > 8 else addr
        return f"\n{emo('wallet')} {_paint(short, C.CYAN)} › "
    return f"\n{emo('lock')} {_paint('not connected', C.GREY)} › "


def repl() -> None:
    global C, EMOJI_ON
    banner()
    welcome()
    parser = build_parser()

    while True:
        try:
            line = input(_prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not line:
            continue

        low = line.lower()
        if low in EXIT_TOKENS:
            print(_paint("bye.", C.GREY))
            return
        if low in HELP_TOKENS:
            welcome()
            continue

        try:
            argv = shlex.split(line)
        except ValueError as e:
            err(f"Parse error: {e}")
            continue
        if not argv:
            continue

        connected, _ = is_connected()
        if not connected and argv[0] != "connect":
            warn("Wallet not connected.")
            print(f"   {emo('link')} Type {_paint('connect', C.CYAN)} "
                  f"to link a wallet first.")
            continue

        try:
            args = parser.parse_args(argv)
        except SystemExit:
            continue

        if args.plain or not _supports_color():
            C = _plain_c()
        if args.plain:
            EMOJI_ON = False

        if args.command is None:
            welcome()
            continue

        try:
            args.func(args)
        except SystemExit:
            pass
        except Exception as e:
            err(f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main() -> None:
    global C, EMOJI_ON
    _enable_ansi_windows()

    parser = build_parser()
    args = parser.parse_args()

    if args.plain or not _supports_color():
        C = _plain_c()
    if args.plain:
        EMOJI_ON = False

    if args.command is not None:
        banner()
        if args.command not in GATE_EXEMPT:
            require_session()
        args.func(args)
        return

    repl()


if __name__ == "__main__":
    main()