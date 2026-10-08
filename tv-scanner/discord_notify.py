#!/usr/bin/env python3
"""Post LONG alerts to Discord webhook. Silent if no signals / no webhook."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROME = ZoneInfo("Europe/Rome")
SECRETS_PATH = Path(__import__("os").environ.get("TV_SCANNER_SECRETS", "/home/box/agent-data/box-secrets.json"))


def load_webhook_url() -> Optional[str]:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url and url.startswith("http"):
        return url.strip()
    try:
        data = json.loads(SECRETS_PATH.read_text())
        card = data.get("card") or {}
        url = card.get("DISCORD_WEBHOOK_URL")
        if isinstance(url, str) and url.startswith("http"):
            return url.strip()
    except Exception:
        return None
    return None


def _ticker(symbol: str) -> str:
    return symbol.split(":")[-1] if ":" in symbol else symbol


def _bar_rome(bar_t: int) -> str:
    """5m bar CLOSE time in Europe/Rome (bar_t is open; +5m)."""
    return datetime.fromtimestamp(int(bar_t) + 300, tz=ROME).strftime("%H:%M")


def _split_buckets(
    signals: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """EMA 6/20, VWAP, Daily EMA pullback, SMA30 65m pullback, 30m pivot."""
    vwap, ema, daily, sma30, pivot30 = [], [], [], [], []
    for s in signals:
        tu = str(s.get("trigger", "")).upper()
        if "30M" in tu and "PIVOT" in tu:
            pivot30.append(s)
        elif "SMA30" in tu and "PULLBACK" in tu:
            sma30.append(s)
        elif "DAILY" in tu and "PULLBACK" in tu:
            daily.append(s)
        elif "VWAP" in tu:
            vwap.append(s)
        else:
            ema.append(s)  # day-monitor EMA 6/20 (and unknowns)
    return ema, vwap, daily, sma30, pivot30


def _daily_ema_label(signal: dict[str, Any]) -> Optional[str]:
    """Return the normalized Daily EMA label used by a pullback signal."""
    raw = signal.get("nearest_daily_ma") or signal.get("nearest_ma")
    compact = re.sub(r"\s+", "", str(raw or "").upper())
    match = re.fullmatch(r"(?:EMA)?(9|21)", compact)
    return f"EMA{match.group(1)}" if match else None


def _daily_ema_groups(
    signals: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group Daily EMA pullbacks EMA9 -> EMA21 (EMA50 dropped 2026-09-30)."""
    groups: dict[str, list[dict[str, Any]]] = {
        key: [] for key in ("EMA9", "EMA21")
    }
    unspecified: list[dict[str, Any]] = []
    for signal in signals:
        label = _daily_ema_label(signal)
        if label in groups:
            groups[label].append(signal)
        else:
            unspecified.append(signal)
    out = [(label, bucket) for label, bucket in groups.items() if bucket]
    if unspecified:
        out.append(("EMA unspecified", unspecified))
    return out


def _title_line(signals: list[dict[str, Any]], *, ansi: bool = False) -> str:
    """Remy title: time + Close only — no EMA tags (those live in body groups)."""
    bar_label = _bar_rome(int(signals[0]["bar_t"]))
    core = f"🦅 {bar_label} Close"
    if ansi:
        BCY = "\u001b[1;36m"
        RST = "\u001b[0m"
        return f"{BCY}{core}{RST}"
    return core


def _aligned_rows(sigs: list[dict[str, Any]]) -> list[str]:
    """Pad tickers (and prices) so columns line up. No rank on Remy."""
    tickers = [_ticker(s["symbol"]) for s in sigs]
    prices = [f"{float(s['price']):.2f}" for s in sigs]
    wt = max((len(t) for t in tickers), default=0)
    wp = max((len(x) for x in prices), default=0)
    return [f"{t:<{wt}}  @ {px:>{wp}}" for t, px in zip(tickers, prices)]


def _pivot30_kind(signal: dict[str, Any]) -> str:
    """Row label: break | cross | break + cross (default break)."""
    raw = str(signal.get("pivot_kind") or signal.get("kind") or "break").strip().lower()
    if raw in {"cross", "break + cross", "break+cross", "break and cross"}:
        if raw in {"break+cross", "break and cross"}:
            return "break + cross"
        return raw if raw == "cross" else "break + cross"
    return "break"


def _aligned_pivot30_rows(sigs: list[dict[str, Any]]) -> list[str]:
    """30m pivot rows: ``TICKER  @ price  break  H 194.79 / L 188.82  RS 92``.

    Re-breaks (alert_n >= 2) insert `` (n°)`` after price. Same H/L range for
    ``break``, ``cross``, and ``break + cross`` kinds. Columns aligned.
    Trailing ``RS n`` when ``rs_rating`` is present.
    """
    tickers = [_ticker(s["symbol"]) for s in sigs]
    prices = [f"{float(s['price']):.2f}" for s in sigs]
    degrees: list[str] = []
    kinds: list[str] = []
    highs: list[str] = []
    lows: list[str] = []
    rs_vals: list[str] = []
    for s in sigs:
        n = s.get("pivot_alert_n")
        try:
            n_int = int(n) if n is not None else 1
        except (TypeError, ValueError):
            n_int = 1
        degrees.append(f"({n_int}°)" if n_int >= 2 else "")
        kinds.append(_pivot30_kind(s))
        ph = s.get("pivot_high")
        pl = s.get("pivot_low")
        highs.append(f"{float(ph):.2f}" if ph is not None else "n/a")
        lows.append(f"{float(pl):.2f}" if pl is not None else "n/a")
        rs = s.get("rs_rating")
        if rs is None:
            rs_vals.append("")
        else:
            try:
                rs_vals.append(str(int(rs)))
            except (TypeError, ValueError):
                rs_vals.append("")

    wt = max((len(t) for t in tickers), default=0)
    wp = max((len(x) for x in prices), default=0)
    wd = max((len(d) for d in degrees), default=0)
    wk = max((len(k) for k in kinds), default=0)
    wh = max((len(x) for x in highs), default=0)
    wl = max((len(x) for x in lows), default=0)
    wr = max((len(x) for x in rs_vals), default=0)
    show_rs = any(rs_vals)

    rows: list[str] = []
    for t, px, deg, kind, h, l, rs in zip(
        tickers, prices, degrees, kinds, highs, lows, rs_vals
    ):
        if wd > 0:
            deg_part = f"  {deg:<{wd}}" if deg else f"  {'':<{wd}}"
        else:
            deg_part = ""
        base = (
            f"{t:<{wt}}  @ {px:>{wp}}{deg_part}  {kind:<{wk}}  "
            f"H {h:>{wh}} / L {l:>{wl}}"
        )
        if show_rs:
            rs_part = f"  RS {rs:>{wr}}" if rs else f"  RS {'':>{wr}}"
            rows.append(base + rs_part)
        else:
            rows.append(base)
    return rows


def format_discord_body(signals: list[dict[str, Any]]) -> str:
    """Main Remy embed body (no 30m pivot — those use a separate embed)."""
    if not signals:
        return ""
    ema, vwap, daily, sma30, _pivot30 = _split_buckets(signals)
    main = ema + vwap + daily + sma30
    if not main:
        return ""
    lines: list[str] = [_title_line(main)]
    sections = [
        ("• Ema 6/20 cross:", ema),
        ("• Vwap cross:", vwap),
        ("• Daily EMA pullback:", daily),
        ("• 5 MA Daily:", sma30),
    ]
    first = True
    for header, bucket in sections:
        if not bucket:
            continue
        if not first:
            lines.append("")
        first = False
        lines.append(header)
        if header == "• Daily EMA pullback:":
            for label, group in _daily_ema_groups(bucket):
                lines.append(f"• {label}")
                lines.extend(_aligned_rows(group))
                lines.append("")
            lines.pop()
        else:
            lines.extend(_aligned_rows(bucket))
    return "\n".join(lines).strip()


def format_pivot30_body(signals: list[dict[str, Any]]) -> str:
    """30m pivot embed body: aligned rows only (no section header)."""
    if not signals:
        return ""
    _ema, _vwap, _daily, _sma30, pivot30 = _split_buckets(signals)
    if not pivot30:
        return ""
    return "\n".join(_aligned_pivot30_rows(pivot30)).strip()


def _pivot30_title(signals: list[dict[str, Any]]) -> str:
    """Exact title: ``30 minute pivot • HH:MM Close`` (5m close Rome)."""
    bar_label = _bar_rome(int(signals[0]["bar_t"]))
    return f"30 minute pivot • {bar_label} Close"


def build_discord_embed(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Main Remy plain embed (excludes 30m pivot)."""
    if not signals:
        return {}
    body = format_discord_body(signals)
    if not body:
        return {}
    lines = body.splitlines()
    title = lines[0].strip()
    description = "\n".join(lines[1:]).strip()
    embed: dict[str, Any] = {
        "title": title,
        "color": 0x5DADE2,
    }
    if description:
        embed["description"] = description
    return embed


def build_pivot30_embed(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate 30m pivot embed. Title ``30 minute pivot • HH:MM Close``."""
    if not signals:
        return {}
    _e, _v, _d, _s, pivot30 = _split_buckets(signals)
    if not pivot30:
        return {}
    description = format_pivot30_body(signals)
    if not description:
        return {}
    return {
        "title": _pivot30_title(pivot30),
        "color": 0x5DADE2,
        "description": description,
    }


def build_discord_embeds(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return [main, pivot] subset present — order main then pivot."""
    embeds: list[dict[str, Any]] = []
    main = build_discord_embed(signals)
    if main.get("title"):
        # main may have title-only if somehow empty desc — require description for main
        if main.get("description"):
            embeds.append(main)
    pivot = build_pivot30_embed(signals)
    if pivot.get("title") and pivot.get("description"):
        embeds.append(pivot)
    return embeds


def _normalize(signals: list[Any]) -> list[dict[str, Any]]:
    norm: list[dict[str, Any]] = []
    for s in signals:
        if hasattr(s, "__dict__") and not isinstance(s, dict):
            d = {
                "symbol": s.symbol,
                "trigger": s.trigger,
                "price": s.price,
                "bar_t": s.bar_t,
            }
            ma = getattr(s, "nearest_daily_ma", None)
            if ma:
                d["nearest_daily_ma"] = ma
            n = getattr(s, "pivot_alert_n", None)
            if n is not None:
                d["pivot_alert_n"] = n
            ph = getattr(s, "pivot_high", None)
            if ph is not None:
                d["pivot_high"] = ph
            pl = getattr(s, "pivot_low", None)
            if pl is not None:
                d["pivot_low"] = pl
            pk = getattr(s, "pivot_kind", None)
            if pk:
                d["pivot_kind"] = pk
            rr = getattr(s, "rs_rating", None)
            if rr is not None:
                d["rs_rating"] = rr
            norm.append(d)
        else:
            norm.append(dict(s))
    return norm


def send_discord(signals: list[Any], dry_run: bool = False) -> dict[str, Any]:
    """Send only if signals non-empty and webhook configured. Never posts empty.

    Payload embeds: [main, pivot] when both; only pivot or only main alone.
    """
    if not signals:
        return {"sent": False, "reason": "no_signals"}

    norm = _normalize(signals)
    embeds = build_discord_embeds(norm)
    if not embeds:
        return {"sent": False, "reason": "empty_body"}

    url = load_webhook_url()
    if not url:
        return {"sent": False, "reason": "webhook_missing"}

    payload = {"embeds": embeds}
    chars = sum(len(str(e.get("description", ""))) for e in embeds)
    if dry_run:
        return {
            "sent": False,
            "reason": "dry_run",
            "chars": chars,
            "embeds": embeds,
            "embed": embeds[0],  # backward-compat first embed
            "body": embeds[0].get("description", ""),
            "payload": payload,
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "tv-scanner/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        status = resp.status
    return {
        "sent": True,
        "status": status,
        "chars": chars,
        "embeds_n": len(embeds),
    }




if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="Discord alerts for CONFIRMED LONG: day-monitor Ema 6/20, "
        "Daily EMA9/21, SMA30 65m pullback, 30m pivot. Silent if no NEW signals."
    )
    ap.add_argument("--check", action="store_true", help="Print webhook_ok / webhook_missing (exit 0/1)")
    ap.add_argument(
        "--test-format",
        action="store_true",
        help="Print sample format body without posting",
    )
    args = ap.parse_args()
    if args.check:
        ok = load_webhook_url() is not None
        print("webhook_ok" if ok else "webhook_missing")
        sys.exit(0 if ok else 1)
    if args.test_format:
        sample = [
            {"symbol": "NASDAQ:FORM", "trigger": "PRICE/VWAP CROSS", "price": 135.07, "bar_t": 1790689800},
            {"symbol": "NYSE:ASX", "trigger": "EMA 6/20 CROSS", "price": 44.17, "bar_t": 1790689800},
            {
                "symbol": "NASDAQ:AMD",
                "trigger": "DAILY EMA PULLBACK",
                "price": 160.25,
                "bar_t": 1790689800,
                "nearest_daily_ma": "EMA21",
            },
            {
                "symbol": "NASDAQ:NVDA",
                "trigger": "SMA30 65m PULLBACK",
                "price": 120.50,
                "bar_t": 1790689800,
            },
            {
                "symbol": "NASDAQ:CRDO",
                "trigger": "30M PIVOT",
                "price": 195.40,
                "bar_t": 1790689800,
                "pivot_alert_n": 1,
                "pivot_high": 194.79,
                "pivot_low": 188.82,
                "pivot_kind": "break",
                "rs_rating": 92,
            },
            {
                "symbol": "NASDAQ:LITE",
                "trigger": "30M PIVOT",
                "price": 910.00,
                "bar_t": 1790689800,
                "pivot_alert_n": 2,
                "pivot_high": 893.45,
                "pivot_low": 883.43,
                "pivot_kind": "break",
            },
            {
                "symbol": "NASDAQ:MRVL",
                "trigger": "30M PIVOT",
                "price": 260.50,
                "bar_t": 1790689800,
                "pivot_alert_n": 1,
                "pivot_high": 259.29,
                "pivot_low": 257.42,
                "pivot_kind": "cross",
            },
            {
                "symbol": "NASDAQ:STX",
                "trigger": "30M PIVOT",
                "price": 906.89,
                "bar_t": 1790689800,
                "pivot_alert_n": 3,
                "pivot_high": 906.17,
                "pivot_low": 900.96,
                "pivot_kind": "break + cross",
            },
        ]
        embeds = build_discord_embeds(sample)
        print(json.dumps({"embeds": embeds}, indent=2, ensure_ascii=False))
        sys.exit(0)
    ap.print_help()
