#!/usr/bin/env python3
"""Fred6724 / Fred6725 IBD-style RS Rating (TradingView Pine parity).

Score (daily closes vs SPX /^GSPC):
  nN = min(bar_index, N) for N in {63,126,189,252}
  perf_N = close / close[nN]
  rs = 0.4*p63 + 0.2*p126 + 0.2*p189 + 0.2*p252
  totalRsScore = rs_stock / rs_ref * 100

Rating maps totalRsScore through 7 percentile thresholds (98,89,69,49,29,9,1)
from the Pine script replay defaults (local only — never download rs_stocks.csv
or RSRATING.csv; Ronin 2026-10-05).
"""
from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

BASE_DIR = Path(__import__("os").environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)  # locale o box
CACHE_DIR = BASE_DIR / "cache"
DAILY_CACHE_DIR = CACHE_DIR / "daily"
THRESHOLDS_PATH = CACHE_DIR / "rs_thresholds.json"

# Pine replay defaults (allowReplay inputs on Fred6724 RS Rating)
PINE_REPLAY_DEFAULTS = (195.93, 117.11, 99.04, 91.66, 80.96, 53.64, 24.86)
PERCENTILE_KEYS = (98, 89, 69, 49, 29, 9, 1)

RSRATING_URL = (
    "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/RSRATING.csv"
)
RS_STOCKS_URL = (
    "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_stocks.csv"
)

SPX_SYMBOL = "^GSPC"  # Yahoo; Pine comparativeTickerId = SP:SPX
SPX_CACHE_SYMBOL = "^GSPC"

# Lookback periods (trading days)
RS_PERIODS = (63, 126, 189, 252)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def attribute_percentile(
    score: float,
    taller: float,
    smaller: float,
    up: float,
    dn: float,
    weight: float,
) -> float:
    """Pine ``f_attributePercentile`` / ``f(score, taller, smaller, up, dn, weight)``."""
    total = float(score)
    s = total + (total - smaller) * weight
    if s > taller - 1:
        s = taller - 1
    k1 = smaller / dn
    k2 = (taller - 1) / up
    denom_span = (taller - 1) - smaller
    if denom_span == 0:
        return float(dn)
    k3 = (k1 - k2) / denom_span
    denom = k1 - k3 * (total - smaller)
    if denom == 0:
        r = float(dn)
    else:
        r = s / denom
    if r > up:
        r = float(up)
    if r < dn:
        r = float(dn)
    return float(r)


def score_to_rating(
    score: float,
    thresholds: Sequence[float],
) -> int:
    """Map totalRsScore → 1..99 using the 7 Fred thresholds (first..svth)."""
    if len(thresholds) != 7:
        raise ValueError(f"expected 7 thresholds, got {len(thresholds)}")
    first, scnd, thrd, frth, ffth, sxth, svth = (float(x) for x in thresholds)
    if score >= first:
        return 99
    if score <= svth:
        return 1
    if scnd <= score < first:
        r = attribute_percentile(score, first, scnd, 98, 90, 0.33)
    elif thrd <= score < scnd:
        r = attribute_percentile(score, scnd, thrd, 89, 70, 2.1)
    elif frth <= score < thrd:
        r = attribute_percentile(score, thrd, frth, 69, 50, 0)
    elif ffth <= score < frth:
        r = attribute_percentile(score, frth, ffth, 49, 30, 0)
    elif sxth <= score < ffth:
        r = attribute_percentile(score, ffth, sxth, 29, 10, 0)
    elif svth <= score < sxth:
        r = attribute_percentile(score, sxth, svth, 9, 2, 0)
    else:
        return 1
    return int(round(r))


def weighted_rs_perf(closes: Sequence[float]) -> Optional[float]:
    """``0.4*p63 + 0.2*p126 + 0.2*p189 + 0.2*p252`` with IPO ``min(bar_index, N)``."""
    n = len(closes)
    if n < 2:
        return None
    bi = n - 1  # bar_index of last bar
    last = float(closes[bi])
    if last <= 0 or math.isnan(last):
        return None
    perfs: list[float] = []
    weights = (0.4, 0.2, 0.2, 0.2)
    for N, w in zip(RS_PERIODS, weights):
        nN = min(bi, N)
        if nN <= 0:
            return None
        prev = float(closes[bi - nN])
        if prev <= 0 or math.isnan(prev):
            return None
        perfs.append(last / prev)
    return (
        weights[0] * perfs[0]
        + weights[1] * perfs[1]
        + weights[2] * perfs[2]
        + weights[3] * perfs[3]
    )


def total_rs_score(
    stock_closes: Sequence[float],
    ref_closes: Sequence[float],
) -> Optional[float]:
    """``rs_stock / rs_ref * 100`` (Pine totalRsScore)."""
    rs_stock = weighted_rs_perf(stock_closes)
    rs_ref = weighted_rs_perf(ref_closes)
    if rs_stock is None or rs_ref is None or rs_ref == 0:
        return None
    return float(rs_stock) / float(rs_ref) * 100.0


def _parse_rsrating_csv(text: str) -> list[float]:
    """Unique close values in first-appearance order (= first..svth)."""
    values: list[float] = []
    seen: set[float] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            v = float(parts[4])
        except ValueError:
            continue
        if v == 0 or v in seen:
            continue
        seen.add(v)
        values.append(v)
        if len(values) >= 7:
            break
    return values


def _thresholds_from_rs_stocks_csv(text: str) -> list[float]:
    """Derive score at percentiles 98,89,69,49,29,9,1 (max RS in each band)."""
    reader = csv.DictReader(io.StringIO(text))
    by_pct: dict[int, list[float]] = {p: [] for p in PERCENTILE_KEYS}
    for row in reader:
        try:
            pct = int(float(row["Percentile"]))
            rs = float(row["Relative Strength"])
        except (KeyError, TypeError, ValueError):
            continue
        if pct in by_pct:
            by_pct[pct].append(rs)
    out: list[float] = []
    for p in PERCENTILE_KEYS:
        vals = by_pct.get(p) or []
        if not vals:
            return []
        # rs_ranking.py: df sorted desc, matching.iloc[0] → max RS in band
        out.append(max(vals))
    return out


def _http_get(url: str, timeout: float = 60.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "tv-scanner-rs-rating/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_thresholds_from_network() -> tuple[list[float], str]:
    """Disabled 2026-10-05: Ronin — never download RSRATING.csv / rs_stocks.csv.

    Thresholds come from the Pine script replay defaults only.
    """
    return list(PINE_REPLAY_DEFAULTS), "pine_replay_defaults"


def load_or_refresh_thresholds(
    path: Path = THRESHOLDS_PATH,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Write Pine replay-default thresholds locally. No network precalc files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    today = _today_utc()
    payload = {
        "date": today,
        "source": "pine_replay_defaults",
        "source_label": "pine_replay_defaults",
        "percentiles": list(PERCENTILE_KEYS),
        "thresholds": list(PINE_REPLAY_DEFAULTS),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Ronin 2026-10-05: local formula only; no Fred6725 csv download",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def get_thresholds() -> tuple[list[float], dict[str, Any]]:
    """Return (thresholds, meta dict from cache)."""
    meta = load_or_refresh_thresholds()
    return [float(x) for x in meta["thresholds"]], meta


def _daily_cache_path(symbol: str, cache_dir: Optional[Path] = None) -> Path:
    cdir = cache_dir or DAILY_CACHE_DIR
    return cdir / f"{symbol.replace(':', '_')}.json"


def load_daily_closes(
    symbol: str,
    bars: Optional[list] = None,
    cache_dir: Optional[Path] = None,
) -> list[float]:
    """Load daily close series (raw, unsorted → sorted by t)."""
    if bars is None:
        path = _daily_cache_path(symbol, cache_dir)
        if not path.exists():
            raise FileNotFoundError(f"no daily cache for {symbol} at {path}")
        data = json.loads(path.read_text())
        if isinstance(data, list):
            bars = data
        else:
            bars = data.get("bars") or data.get("data") or []
    ordered = sorted(bars, key=lambda b: int(b["t"]))
    return [float(b["c"]) for b in ordered]


def drop_forming_daily_bars(
    bars: list[dict],
    now: Optional[int] = None,
) -> list[dict]:
    """Exclude today's forming daily while RTH is open (before 16:00 ET).

    RS Rating is a daily measure — do not use the in-progress session bar.
    """
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
    UTC = timezone.utc
    n = int(now if now is not None else datetime.now(tz=UTC).timestamp())
    dt = datetime.fromtimestamp(n, tz=UTC).astimezone(ET)
    today = dt.date()
    minutes = dt.hour * 60 + dt.minute
    market_closed_today = dt.weekday() >= 5 or minutes >= 16 * 60
    out: list[dict] = []
    for b in bars:
        # yfinance 1d: midnight UTC = session calendar date
        bday = datetime.fromtimestamp(int(b["t"]), tz=UTC).date()
        if bday == today and not market_closed_today:
            continue
        out.append(b)
    return out


def compute_rs_rating_from_closes(
    stock_closes: Sequence[float],
    ref_closes: Sequence[float],
    thresholds: Optional[Sequence[float]] = None,
) -> Optional[tuple[int, float]]:
    """Return (rating 1..99, totalRsScore) or None if insufficient data."""
    score = total_rs_score(stock_closes, ref_closes)
    if score is None:
        return None
    th = list(thresholds) if thresholds is not None else get_thresholds()[0]
    return score_to_rating(score, th), float(score)


def compute_rs_rating(
    symbol: str,
    *,
    daily_bars: Optional[list] = None,
    spx_bars: Optional[list] = None,
    now: Optional[int] = None,
    thresholds: Optional[Sequence[float]] = None,
    cache_dir: Optional[Path] = None,
) -> Optional[int]:
    """Compute RS Rating for ``symbol`` from daily cache (vs ^GSPC).

    Uses last completed daily close (drops today's forming bar during RTH).
    Returns None if data missing / insufficient.
    """
    try:
        if daily_bars is not None:
            stock_bars = list(daily_bars)
        else:
            path = _daily_cache_path(symbol, cache_dir)
            if not path.exists():
                return None
            data = json.loads(path.read_text())
            stock_bars = data.get("bars") or []
        if spx_bars is not None:
            ref_bars = list(spx_bars)
        else:
            spx_path = _daily_cache_path(SPX_CACHE_SYMBOL, cache_dir)
            if not spx_path.exists():
                return None
            ref_bars = json.loads(spx_path.read_text()).get("bars") or []
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None

    stock_bars = drop_forming_daily_bars(stock_bars, now=now)
    ref_bars = drop_forming_daily_bars(ref_bars, now=now)
    stock_closes = [float(b["c"]) for b in sorted(stock_bars, key=lambda x: int(x["t"]))]
    ref_closes = [float(b["c"]) for b in sorted(ref_bars, key=lambda x: int(x["t"]))]
    # Need enough history for 252-lookback IPO handling to be meaningful
    if len(stock_closes) < 63 or len(ref_closes) < 63:
        return None
    result = compute_rs_rating_from_closes(stock_closes, ref_closes, thresholds=thresholds)
    if result is None:
        return None
    return int(result[0])


def compute_rs_rating_details(
    symbol: str,
    *,
    daily_bars: Optional[list] = None,
    spx_bars: Optional[list] = None,
    now: Optional[int] = None,
    thresholds: Optional[Sequence[float]] = None,
    cache_dir: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Like compute_rs_rating but also returns score + closes used."""
    try:
        if daily_bars is not None:
            stock_bars = list(daily_bars)
        else:
            path = _daily_cache_path(symbol, cache_dir)
            if not path.exists():
                return None
            stock_bars = json.loads(path.read_text()).get("bars") or []
        if spx_bars is not None:
            ref_bars = list(spx_bars)
        else:
            spx_path = _daily_cache_path(SPX_CACHE_SYMBOL, cache_dir)
            if not spx_path.exists():
                return None
            ref_bars = json.loads(spx_path.read_text()).get("bars") or []
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None

    stock_bars = drop_forming_daily_bars(stock_bars, now=now)
    ref_bars = drop_forming_daily_bars(ref_bars, now=now)
    stock_closes = [float(b["c"]) for b in sorted(stock_bars, key=lambda x: int(x["t"]))]
    ref_closes = [float(b["c"]) for b in sorted(ref_bars, key=lambda x: int(x["t"]))]
    if len(stock_closes) < 63 or len(ref_closes) < 63:
        return None
    th = list(thresholds) if thresholds is not None else get_thresholds()[0]
    result = compute_rs_rating_from_closes(stock_closes, ref_closes, thresholds=th)
    if result is None:
        return None
    rating, score = result
    return {
        "symbol": symbol,
        "rs_rating": rating,
        "total_rs_score": round(score, 4),
        "n_stock_bars": len(stock_closes),
        "n_ref_bars": len(ref_closes),
        "thresholds": th,
    }


if __name__ == "__main__":
    meta = load_or_refresh_thresholds(force=True)
    print(json.dumps(meta, indent=2))
    for sym in [
        "NASDAQ:CRDO",
        "NASDAQ:LITE",
        "NASDAQ:MRVL",
        "NASDAQ:STX",
        "NASDAQ:NVDA",
        "NYSE:F",  # weak-ish large name often lower RS
    ]:
        d = compute_rs_rating_details(sym)
        print(sym, d)
