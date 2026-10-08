#!/usr/bin/env python3
"""Re-sync TradingView WL 323848747 "Main" into pivot_wl_323848747.txt.

The WL is read-only shared on TradingView: NEVER modify it on TV. This script
only rewrites the LOCAL universe file used by scanner.py
(UNIVERSE_MODE='wl323848747').

Input (pick one):
  --from-file PATH   text or JSON dump (e.g. TradingView MCP
                     mcp-watchlist-get-watchlist output saved to a file). Any
                     EXCHANGE:TICKER tokens are extracted in order.
  SYMBOLS ...        symbols on the command line (space/comma separated).
  (stdin)            if neither is given, read text/JSON from stdin.

Checks (skip with --no-check): yfinance quoteType per ticker. ETFs / funds
(quoteType != EQUITY) are written as comment lines `# EXCLUDED_ETF ...` so the
scanner ignores them (user cannot trade ETFs). Tickers with no Yahoo 5m/daily
data are reported (kept, scanner just skips them).

Examples:
  .venv/bin/python sync_pivot_wl.py --from-file mcp_inbox/wl_323848747.json
  .venv/bin/python sync_pivot_wl.py --dry-run NASDAQ:AMD NYSE:DELL
Writes a timestamped backup of the previous file next to it.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__import__("os").environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)  # locale o box
WL_ID = "323848747"
WL_PATH = BASE / f"pivot_wl_{WL_ID}.txt"
ROME = ZoneInfo("Europe/Rome")
SYM_RE = re.compile(r"\b(NASDAQ|NYSE|AMEX|NYSEARCA|ARCA|BATS|CBOE|OTC)\s*:\s*([A-Z][A-Z0-9.\-]{0,9})\b")


def extract_symbols(text: str) -> list[str]:
    """EXCHANGE:TICKER tokens in order (dedup). Works for plain text or JSON."""
    out = [f"{ex}:{tk}" for ex, tk in SYM_RE.findall(text.upper())]
    return list(dict.fromkeys(out))


def check_one(sym: str) -> dict:
    import yfinance as yf

    t = sym.split(":")[-1].replace(".", "-")
    row = {"symbol": sym, "ticker": t, "quoteType": None, "n5m": 0, "n1d": 0}
    tk = yf.Ticker(t)
    try:
        info = tk.get_info() or {}
        row["quoteType"] = info.get("quoteType")
        row["name"] = info.get("shortName") or info.get("longName")
    except Exception as e:  # noqa: BLE001
        row["info_error"] = f"{type(e).__name__}: {e}"[:120]
    try:
        row["n5m"] = len(tk.history(period="5d", interval="5m", prepost=False))
        row["n1d"] = len(tk.history(period="1mo", interval="1d"))
    except Exception as e:  # noqa: BLE001
        row["data_error"] = f"{type(e).__name__}: {e}"[:120]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbols", nargs="*", help="EXCHANGE:TICKER symbols (space/comma separated)")
    ap.add_argument("--from-file", type=Path, help="text/JSON file containing the WL symbols")
    ap.add_argument("--out", type=Path, default=WL_PATH, help=f"output file (default {WL_PATH})")
    ap.add_argument("--no-check", action="store_true", help="skip yfinance ETF/data check")
    ap.add_argument("--dry-run", action="store_true", help="print result; do not write")
    args = ap.parse_args()

    if args.from_file:
        text = args.from_file.read_text()
    elif args.symbols:
        text = " ".join(args.symbols).replace(",", " ")
    else:
        text = sys.stdin.read()
    syms = extract_symbols(text)
    if not syms:
        print("ERROR: no EXCHANGE:TICKER symbols found in input", file=sys.stderr)
        return 2

    checks: dict[str, dict] = {}
    if not args.no_check:
        with cf.ThreadPoolExecutor(12) as ex:
            for row in ex.map(check_one, syms):
                checks[row["symbol"]] = row

    etfs = [s for s in syms if checks.get(s, {}).get("quoteType") not in (None, "EQUITY")]
    no_data = [s for s in syms if checks and (not checks[s]["n5m"] or not checks[s]["n1d"])]
    unknown_type = [s for s in syms if checks and checks[s].get("quoteType") is None]

    now = datetime.now(tz=ROME).strftime("%Y-%m-%d %H:%M")
    lines = [
        f'# TradingView watchlist {WL_ID} "Main" (read-only shared; NEVER modify on TV)',
        f"# Synced: {now} Rome via sync_pivot_wl.py ({len(syms)} symbols, "
        f"{len(etfs)} ETF excluded)",
        "# Re-sync: .venv/bin/python sync_pivot_wl.py --from-file <dump>",
    ]
    for s in syms:
        if s in etfs:
            qt = checks[s].get("quoteType")
            lines.append(f"# EXCLUDED_ETF {s}  (quoteType={qt})")
        else:
            lines.append(s)
    body = "\n".join(lines) + "\n"

    old = set()
    if args.out.exists():
        old = {l.split("#", 1)[0].strip() for l in args.out.read_text().splitlines()} - {""}
    new = {s for s in syms if s not in etfs}
    report = {
        "symbols_in": len(syms),
        "active": len(new),
        "etf_excluded": etfs,
        "no_data": no_data,
        "unknown_quote_type": unknown_type,
        "added": sorted(new - old),
        "removed": sorted(old - new),
        "out": str(args.out),
        "dry_run": args.dry_run,
    }
    if not args.dry_run:
        if args.out.exists():
            stamp = datetime.now(tz=ROME).strftime("%Y%m%d_%H%M%S")
            shutil.copy2(args.out, args.out.with_name(f"{args.out.name}.bak_{stamp}"))
        args.out.write_text(body)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
