"""Jeff Sun (@jfsrev) sulla base multi-edge di Martin [ANDREA 28/10].

Del JeffCoach di prima (jeff-coach main @36a11c0, regole chiuse da Ronin) restano solo le parti scelte da Andrea:
  1. universo e filtri delle idee di trade: market cap > 1 mld, adv$ a 50 sedute >= 50M$, ATR% >= 2,8, borse USA,
     fuori Biotechnology (e ADPT), fuori chi ha gli utili nelle prossime 5 sedute (compresa quella della lista);
  2. gli 8 gate del Focus: RS >= 80, sopra la SMA200 non in calo, Atr Ext <= 4, entro il 5% dalla SMA5, close daily
     sopra la EMA50 a 1 ora, 0-1,5 ATR sopra la EMA9, VCP <= 25, almeno 2 sedute di compressione nelle ultime 3;
  3. la lista PEG delayed reaction (peg.py).
Liste, temi, regime, livelli, edge, alert e giornale sono la base di Martin multi-edge.

Le formule sono quelle di prima (jeffcoach/indicators.py e data.py di jeff-coach, allineate agli script Pine di Ronin):
ATR di Wilder con seme SMA (ta.rma), adv$ = sma(volume[1]*close[1], 50), Atr Ext di Ronin, VCP Tightness, RS Rating
Fred6724 (pine_replay) contro l'S&P 500, barre da 1 ora costruite dai 5 minuti. Le chiavi delle metriche hanno il
prefisso j_ per non toccare quelle di Martin (che ha un suo ATR, un suo ADR e una sua RS).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from . import config as C
from .calendar_us import ET, last_sessions, sessions_from

log = logging.getLogger("jeffcoach.jeff")

GATE_CODES = ("rs", "sma200", "ext", "sma5", "ma1h", "ema9", "vcp", "comp")
GATE_LABEL = {"rs": "RS", "sma200": "SMA200", "ext": "Atr Ext", "sma5": "SMA5", "ma1h": "EMA50 1h", "ema9": "EMA9",
              "vcp": "VCP", "comp": "compression"}


# ------------------------------------------------------------------ indicatori (identici a jeff-coach)
def rma(s: pd.Series, length: int) -> pd.Series:
    """ta.rma (Wilder): seme = SMA dei primi `length` valori."""
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    if len(v) < length:
        return pd.Series(out, index=s.index)
    a = 1.0 / length
    out[length - 1] = np.nanmean(v[:length])
    for i in range(length, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df.Close.shift(1)
    return pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return rma(true_range(df), length)


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.astype(float).rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.astype(float).ewm(span=n, adjust=False).mean()


def avg_vol_adv(df: pd.DataFrame, n: int = 50) -> tuple[Optional[float], Optional[float]]:
    """Pine: sma(volume[1],50), sma(volume[1]*close[1],50) sull'ultima barra."""
    if len(df) < n + 1:
        return None, None
    v = df.Volume.astype(float).shift(1)
    c = df.Close.astype(float).shift(1)
    av = v.rolling(n, min_periods=n).mean().iloc[-1]
    adv = (v * c).rolling(n, min_periods=n).mean().iloc[-1]
    return (float(av) if pd.notna(av) else None, float(adv) if pd.notna(adv) else None)


def atr_ext(close: float, ma: Optional[float], atr_abs: Optional[float]) -> Optional[float]:
    """Atr Ext di Ronin = ((close-MA)/MA*100)/ATR%  (NON (close-MA)/ATR)."""
    if not ma or not atr_abs or ma <= 0 or atr_abs <= 0:
        return None
    return (close - ma) * close / (ma * atr_abs)


def range_pct(df: pd.DataFrame) -> pd.Series:
    """Range della barra come nello script VCP: (H-L)/L*100."""
    return (df.High - df.Low) / df.Low * 100.0


def adr_pct(df: pd.DataFrame, n: int = C.JEFF_VCP_ADR_LEN) -> pd.Series:
    return range_pct(df).rolling(n, min_periods=n).mean()


def vcp_series(df: pd.DataFrame, length=C.JEFF_VCP_LEN, adr_len=C.JEFF_VCP_ADR_LEN, baseline=C.JEFF_VCP_BASELINE) -> pd.Series:
    """VCP Tightness Score 0-100 per ogni barra (identico a score.py / vcp_tightness.pine).
    NaN se lo storico non riempie la baseline: la finestra non si accorcia mai."""
    adr = adr_pct(df, adr_len).replace(0, 0.0001)
    hc, lc = df.Close.rolling(length).max(), df.Close.rolling(length).min()
    hp, lp = df.High.rolling(length).max(), df.Low.rolling(length).min()
    cs = (hc - lc) / lc * 100.0
    ps = (hp - lp) / lp * 100.0
    comb = (cs / adr + ps / adr) / 2.0
    hi = comb.rolling(baseline, min_periods=baseline).max()
    lo = comb.rolling(baseline, min_periods=baseline).min()
    span = hi - lo
    sc = (comb - lo) / span * 100.0
    sc = sc.where(span != 0, 0.0)
    return sc.where(hi.notna())


def compression_days(df: pd.DataFrame, window: int = C.JEFF_COMPRESSION_WINDOW) -> int:
    """Quante delle ultime `window` barre hanno range% < ADR20% dello stesso giorno."""
    r = range_pct(df)
    a = adr_pct(df)
    ok = (r < a).iloc[-window:]
    return int(ok.sum())


_PERIODS = (63, 126, 189, 252)
_WEIGHTS = (0.4, 0.2, 0.2, 0.2)


def _strength(closes: Sequence[float]) -> Optional[float]:
    """0.4*C/C[n63] + 0.2*C/C[n126] + ... con n = min(bar_index, N) come nello script (IPO)."""
    n = len(closes)
    if n < 2:
        return None
    last = float(closes[-1])
    s = 0.0
    for p, w in zip(_PERIODS, _WEIGHTS):
        k = min(n - 1, p)
        base = float(closes[-1 - k])
        if base <= 0:
            return None
        s += w * (last / base)
    return s


def rs_raw(stock_closes: Sequence[float], spx_closes: Sequence[float]) -> Optional[float]:
    a, b = _strength(stock_closes), _strength(spx_closes)
    if a is None or b is None or b == 0:
        return None
    return a / b * 100.0


def _attr(score, taller, smaller, up, dn, weight):
    s = score + (score - smaller) * weight
    if s > taller - 1:
        s = taller - 1
    k1 = smaller / dn
    k2 = (taller - 1) / up
    k3 = (k1 - k2) / (taller - 1 - smaller)
    r = s / (k1 - k3 * (score - smaller))
    return min(max(r, dn), up)


def rs_rating(raw: Optional[float], th: Sequence[float] = C.JEFF_RS_PINE_REPLAY) -> Optional[int]:
    """RS Rating 1-99 di Fred6724 (pine_replay) dal rapporto di forza contro l'S&P 500."""
    if raw is None:
        return None
    f1, f2, f3, f4, f5, f6, f7 = th
    if raw >= f1:
        return 99
    if raw <= f7:
        return 1
    if raw >= f2:
        r = _attr(raw, f1, f2, 98, 90, 0.33)
    elif raw >= f3:
        r = _attr(raw, f2, f3, 89, 70, 2.1)
    elif raw >= f4:
        r = _attr(raw, f3, f4, 69, 50, 0)
    elif raw >= f5:
        r = _attr(raw, f4, f5, 49, 30, 0)
    elif raw >= f6:
        r = _attr(raw, f5, f6, 29, 10, 0)
    else:
        r = _attr(raw, f6, f7, 9, 2, 0)
    return int(round(r))


def _f(x) -> Optional[float]:
    return float(x) if x is not None and pd.notna(x) else None


# ------------------------------------------------------------------ metriche per titolo
def metrics(df: pd.DataFrame, spx_close: Optional[pd.Series]) -> dict:
    """Misure di Jeff sull'ultima barra completata (chiavi j_*). Vuoto se lo storico è troppo corto."""
    if df is None or len(df) < 60:
        return {}
    c = df.Close.astype(float)
    close = float(c.iloc[-1])
    a = _f(atr(df).iloc[-1])
    _av, adv = avg_vol_adv(df)
    s5, s50, s200 = (sma(c, n) for n in (5, 50, 200))
    e9 = float(ema(c, 9).iloc[-1])
    k = C.JEFF_SMA200_SLOPE_BARS
    s200_now = _f(s200.iloc[-1])
    s200_then = _f(s200.iloc[-1 - k]) if len(s200) > k else None
    vcp = _f(vcp_series(df).iloc[-1])
    raw = None
    if spx_close is not None:
        ref = spx_close.reindex(df.index).ffill()
        if ref.notna().all():
            raw = rs_raw(list(c.values), list(ref.values))
    sma5 = _f(s5.iloc[-1])
    sma50 = _f(s50.iloc[-1])
    return dict(
        j_close=close, j_atr=a, j_atr_pct=(a / close * 100) if a else None, j_adv=adv,
        j_sma5=sma5, j_sma5_dist_pct=((close / sma5 - 1) * 100) if sma5 else None,
        j_sma50=sma50, j_sma200=s200_now,
        j_above_sma200=bool(s200_now is not None and close > s200_now),
        j_sma200_slope_ok=(bool(s200_now >= s200_then) if (s200_now is not None and s200_then is not None) else None),
        j_ema9=e9, j_ema9_dist_atr=((close - e9) / a) if a else None,
        j_vcp=vcp, j_compression=compression_days(df), j_rs=rs_rating(raw),
        j_ext=atr_ext(close, sma50, a),
    )


def liquid(m: dict) -> bool:
    """Liquidità e volatilità del gate di universo (servono anche a decidere chi riceve gli edge)."""
    return bool((m.get("j_adv") or 0) >= C.JEFF_ADV_MIN and (m.get("j_atr_pct") or 0) >= C.JEFF_ATR_PCT_MIN)


def universe_reason(t: str, m: dict, info: Optional[dict], industry: Optional[str]) -> Optional[str]:
    """Motivo di esclusione dall'universo di Jeff, o None se passa. `info` = riga dello screener (tipo, borsa, mcap)."""
    info = info or {}
    if t in C.JEFF_EXCLUDED_TICKERS:
        return "biotech (manual list)"
    qt = info.get("quote_type")
    if qt and qt != "EQUITY":
        return f"not a stock ({qt})"
    if industry in C.JEFF_EXCLUDED_INDUSTRIES:
        return f"single-name {industry}"
    ex = info.get("exchange")
    if ex and ex not in C.EXCHANGES:
        return f"exchange {ex}"
    mc = info.get("mcap")
    if mc is not None and mc <= C.JEFF_MCAP_MIN:
        return f"market cap {mc / 1e6:.0f}M"
    adv = m.get("j_adv")
    if adv is None or adv < C.JEFF_ADV_MIN:
        return f"adv$ {0 if adv is None else adv / 1e6:.1f}M"
    ap = m.get("j_atr_pct")
    if ap is None or ap < C.JEFF_ATR_PCT_MIN:
        return "ATR% n/a" if ap is None else f"ATR% {ap:.2f}"
    return None


# ------------------------------------------------------------------ gate del Focus
def focus_gates(m: dict, ma1h: Optional[float]) -> list[tuple[str, bool, str]]:
    """Gli 8 gate del Focus di Jeff: [(codice, chiuso, motivo breve in inglese se aperto)]."""
    g: list[tuple[str, bool, str]] = []
    rs = m.get("j_rs")
    g.append(("rs", rs is not None and rs >= C.JEFF_RS_MIN, f"RS {rs}"))
    ok200 = bool(m.get("j_above_sma200")) and m.get("j_sma200_slope_ok") is True
    g.append(("sma200", ok200, "SMA200 declining" if m.get("j_above_sma200") else "under the SMA200"))
    ext = m.get("j_ext")
    g.append(("ext", ext is not None and ext <= C.JEFF_EXT_MAX, f"Atr Ext {ext:.1f}x" if ext is not None else "ext n/a"))
    d5 = m.get("j_sma5_dist_pct")
    g.append(("sma5", d5 is not None and abs(d5) <= C.JEFF_SMA5_MAX_DIST_PCT,
              f"{d5:+.1f}% from SMA5" if d5 is not None else "SMA5 n/a"))
    close = m.get("j_close")
    if ma1h is None:
        g.append(("ma1h", False, f"1h {C.JEFF_MA1H_KIND.upper()}{C.JEFF_MA1H_LEN} n/a"))
    else:
        g.append(("ma1h", close is not None and close > ma1h,
                  f"under 1h {C.JEFF_MA1H_KIND.upper()}{C.JEFF_MA1H_LEN} ({(close / ma1h - 1) * 100:+.1f}%)"))
    e = m.get("j_ema9_dist_atr")
    g.append(("ema9", e is not None and 0 < e <= C.JEFF_EMA9_MAX_ATR,
              "EMA9 n/a" if e is None else ("under 9 EMA" if e <= 0 else f"{e:.1f} ATR over 9 EMA")))
    v = m.get("j_vcp")
    g.append(("vcp", v is not None and v <= C.JEFF_VCP_MAX, "VCP n/a" if v is None else f"VCP {v:.0f}"))
    cd = m.get("j_compression") or 0
    g.append(("comp", cd >= C.JEFF_COMPRESSION_DAYS_MIN, f"{cd} tight day{'s' if cd != 1 else ''} of {C.JEFF_COMPRESSION_WINDOW}"))
    return g


def gate_fields(m: dict, ma1h: Optional[float]) -> dict:
    """Campi da mettere sulla riga del candidato: esito dei gate e misure per card, alert e giornale."""
    g = focus_gates(m, ma1h)
    return dict(jeff_ok=all(ok for _, ok, _ in g), jeff_open=[c for c, ok, _ in g if not ok],
                jeff_why="; ".join(w for _, ok, w in g if not ok), jeff_rs=m.get("j_rs"),
                jeff_vcp=None if m.get("j_vcp") is None else round(m["j_vcp"], 1), jeff_comp=m.get("j_compression"),
                jeff_ext=None if m.get("j_ext") is None else round(m["j_ext"], 2),
                jeff_ema9_atr=None if m.get("j_ema9_dist_atr") is None else round(m["j_ema9_dist_atr"], 2),
                jeff_ma1h=None if ma1h is None else round(ma1h, 4),
                adv50=None if m.get("j_adv") is None else round(m["j_adv"], 0))


def tag(r: dict) -> str:
    """'Jeff RS 92 · VCP 12' per card e alert."""
    parts = []
    if r.get("jeff_rs") is not None:
        parts.append(f"Jeff RS {r['jeff_rs']}")
    if r.get("jeff_vcp") is not None:
        parts.append(f"VCP {r['jeff_vcp']:.0f}")
    return " · ".join(parts)


# ------------------------------------------------------------------ EMA50 a 1 ora (barre dai 5 minuti)
def buckets(sub: pd.DataFrame, days: Optional[set] = None) -> list[tuple]:
    """Barre 5m RTH -> barre da JEFF_BUCKET_MIN minuti (giorno, n. barra, close, n. barre 5m). La barra in corso usa
    l'ultima 5m (come TradingView)."""
    sub = sub.dropna(subset=["Close"]).copy()
    sub.index = sub.index.tz_convert(ET)
    mins = sub.index.hour * 60 + sub.index.minute - (9 * 60 + 30)
    keep = (mins >= 0) & (mins < 390)
    if days is not None:
        keep &= pd.Index([d.isoformat() in days for d in sub.index.date])
    sub = sub[keep]
    mins = sub.index.hour * 60 + sub.index.minute - (9 * 60 + 30)
    sub["d"] = [d.isoformat() for d in sub.index.date]
    sub["b"] = (mins // C.JEFF_BUCKET_MIN).astype(int)
    return [(d, b, float(g.Close.iloc[-1]), len(g)) for (d, b), g in sub.groupby(["d", "b"], sort=True)]


def ma_of(closes) -> Optional[float]:
    """Ultimo valore della media sui close delle barre da 1 ora (EMA50 dal 20/10)."""
    s = pd.Series([float(x) for x in closes])
    if len(s) < C.JEFF_MA1H_LEN:
        return None
    m = ema(s, C.JEFF_MA1H_LEN) if C.JEFF_MA1H_KIND == "ema" else s.rolling(C.JEFF_MA1H_LEN).mean()
    v = float(m.iloc[-1])
    return v if v == v else None


def ma_1h(symbols: Iterable[str], as_of: date, chunk: int = 60, download=None) -> dict[str, dict]:
    """EMA50 sulle barre da 1 ora RTH costruite dai 5 minuti delle ultime JEFF_MA1H_SESSIONS sedute fino ad as_of
    compresa (prepost=False). {ticker: {"ma1h": valore, "n_buckets": n} | {"err": motivo}}."""
    syms = sorted(set(symbols))
    if not syms:
        return {}
    sessions = last_sessions(as_of, C.JEFF_MA1H_SESSIONS)
    want = {d.isoformat() for d in sessions}
    start = (sessions[0] - timedelta(days=1)).isoformat()
    end = (sessions[-1] + timedelta(days=1)).isoformat()
    if download is None:
        import yfinance as yf

        def download(ch):
            return yf.download(ch, start=start, end=end, interval="5m", prepost=False, auto_adjust=False,
                               group_by="ticker", threads=True, progress=False)
    out: dict[str, dict] = {}
    for i in range(0, len(syms), chunk):
        ch = syms[i:i + chunk]
        df = None
        for attempt in range(3):
            try:
                df = download(ch)
                break
            except Exception as e:
                log.warning("5m %s: %s", i, e)
                time.sleep(5)
        for s in ch:
            try:
                sub = (df[s] if isinstance(df.columns, pd.MultiIndex) else df).dropna(subset=["Close"]) if df is not None else None
            except KeyError:
                sub = None
            if sub is None or sub.empty:
                out[s] = {"err": "no 5m data"}
                continue
            bk = buckets(sub, want)
            if len(bk) < C.JEFF_MA1H_LEN:
                out[s] = {"err": f"solo {len(bk)} barre da 1 ora"}
                continue
            out[s] = {"ma1h": ma_of([x[2] for x in bk]), "n_buckets": len(bk), "last_bucket": f"{bk[-1][0]}#{bk[-1][1]}"}
        log.info("barre 1h dai 5m %d/%d", min(i + chunk, len(syms)), len(syms))
    return out


# ------------------------------------------------------------------ utili
def earnings_dates(t: str, raw: Optional[dict], uni_info: Optional[dict]) -> set[str]:
    """Tutte le date utili note di un titolo: calendar e earnings_dates di yfinance più quella dello screener.
    Una fonte nella finestra basta per toglierlo (come prima)."""
    r = raw or {}
    ds = set(r.get("calendar") or []) | set(r.get("earnings_dates") or [])
    if (uni_info or {}).get("earnings"):
        ds.add(uni_info["earnings"])
    return {d for d in ds if d}


def earnings_window(session: date) -> tuple[str, str]:
    w = sessions_from(session, C.JEFF_EARNINGS_SESSIONS)
    return w[0].isoformat(), w[-1].isoformat()


def earnings_check(names: Iterable[str], raw: dict, uni: dict, session: date) -> dict:
    """{"out": {t: data nella finestra}, "next": {t: prossima data >= seduta}, "missing": [senza date future]}."""
    lo, hi = earnings_window(session)
    out, nxt, missing = {}, {}, []
    for t in names:
        ds = earnings_dates(t, raw.get(t), uni.get(t))
        fut = sorted(d for d in ds if d >= lo)
        nxt[t] = fut[0] if fut else None
        inside = [d for d in ds if lo <= d <= hi]
        if inside:
            out[t] = min(inside)
        if not fut:
            missing.append(t)
    return {"out": out, "next": nxt, "missing": sorted(missing), "window": [lo, hi]}
