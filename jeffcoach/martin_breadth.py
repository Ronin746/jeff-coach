"""Parte del regime della card come nel bot di Martin [ANDREA 21/10] (martincoach/engine.martin_breadth + output.card_embeds).

Calcolata sui dati daily gia' scaricati dal bot, sull'universo del bot:
  - liste dell'universo Leading / Mediocre / Lagging (prezzo > EMA50 > EMA150, il contrario, il resto) oggi, ieri e
    5 sedute fa; quota dell'universo sopra la EMA21;
  - IWM contro QQQ a un mese, IWM sopra/sotto 9 e 21, mega cap sopra la 9, i 20 titoli piu' forti a 3 mesi sotto 9 e 21;
  - scan +4%: titoli sopra la EMA50 saliti almeno del 4% nell'ultima seduta, e i temi che vi compaiono insieme (>= 3).
Le liste del pool (con variazioni a 1 e 5 sedute e flussi) arrivano da pool.pool_breadth.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

MEGA_CAPS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "NFLX", "ORCL")   # come Martin [ML 31/08]
LEADERS_N = 20
POTENT_MIN_RET = 4.0


def _close(df) -> Optional[pd.Series]:
    if df is None or not len(df):
        return None
    col = "Close" if "Close" in df.columns else ("close" if "close" in df.columns else None)
    return None if col is None else df[col].astype(float).dropna()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _stats(s: pd.Series) -> Optional[dict]:
    if s is None or len(s) < 30:
        return None
    e9, e21, e50 = _ema(s, 9), _ema(s, 21), _ema(s, 50)
    e150 = _ema(s, 150)
    out = dict(close=float(s.iloc[-1]), e9=float(e9.iloc[-1]), e21=float(e21.iloc[-1]),
               ret1=float((s.iloc[-1] / s.iloc[-2] - 1) * 100) if len(s) > 1 else None,
               ret21=float((s.iloc[-1] / s.iloc[-22] - 1) * 100) if len(s) > 22 else None,
               rs63=float((s.iloc[-1] / s.iloc[-64] - 1) * 100) if len(s) > 64 else None,
               e50=float(e50.iloc[-1]) if e50.iloc[-1] == e50.iloc[-1] else None)
    lab = []
    for k in (1, 2, 6):                   # oggi, ieri, 5 sedute fa
        if len(s) < 160 + k - 1:
            lab.append(None)
            continue
        c, a, b = s.iloc[-k], e50.iloc[-k], e150.iloc[-k]
        lab.append("Leading" if c > a > b else ("Lagging" if c < a < b else "Mediocre"))
    out["list"], out["list_1d"], out["list_5d"] = lab
    return out


def compute(daily: dict, tickers, theme_of: Optional[dict] = None, qqq: str = "QQQ", iwm: str = "IWM") -> Optional[dict]:
    M = {}
    for t in tickers:
        st = _stats(_close(daily.get(t)))
        if st:
            M[t] = st
    if not M:
        return None
    cnt = lambda k: {x: sum(1 for m in M.values() if m[k] == x) for x in ("Leading", "Mediocre", "Lagging")}
    lists, l1, l5 = cnt("list"), cnt("list_1d"), cnt("list_5d")
    Q, I = _stats(_close(daily.get(qqq))), _stats(_close(daily.get(iwm)))
    mega = [s for s in MEGA_CAPS if s in M or _close(daily.get(s)) is not None]
    megs = {s: M.get(s) or _stats(_close(daily.get(s))) for s in mega}
    megs = {s: m for s, m in megs.items() if m}
    lead = sorted((s for s in M if M[s]["rs63"] is not None), key=lambda s: -M[s]["rs63"])[:LEADERS_N]
    potent = [s for s, m in M.items() if m["e50"] and m["close"] > m["e50"] and (m["ret1"] or 0) >= POTENT_MIN_RET]
    th: dict[str, int] = {}
    for s in potent:
        t = (theme_of or {}).get(s)
        if t:
            th[t] = th.get(t, 0) + 1
    return dict(
        lists=lists, lists_1d=l1 if sum(l1.values()) else None, lists_5d=l5 if sum(l5.values()) else None,
        above21_pct=round(100 * sum(m["close"] > m["e21"] for m in M.values()) / len(M)),
        iwm_vs_qqq_21d=round(I["ret21"] - Q["ret21"], 1) if Q and I and Q["ret21"] is not None and I["ret21"] is not None else None,
        iwm_above9=bool(I and I["close"] > I["e9"]) if I else None, iwm_above21=bool(I and I["close"] > I["e21"]) if I else None,
        mega_above9=sum(m["close"] > m["e9"] for m in megs.values()), mega_n=len(megs),
        leaders_below9=sum(M[s]["close"] < M[s]["e9"] for s in lead), leaders_below21=sum(M[s]["close"] < M[s]["e21"] for s in lead),
        leaders_n=len(lead), scan_n=len(potent),
        scan_themes=sorted(((t, n) for t, n in th.items() if n >= 3), key=lambda x: -x[1])[:4])


def card_lines(mb: Optional[dict], pb: Optional[dict]) -> list[str]:
    """Righe "Breadth" della card, identiche nel formato a quelle di Martin."""
    if not mb and not pb:
        return []
    def delta(now, d1, d5, k):
        parts = ([f"{now[k] - d1[k]:+d} 1d"] if d1 else []) + ([f"{now[k] - d5[k]:+d} 5d"] if d5 else [])
        return f" ({', '.join(parts)})" if parts else ""
    above = f" · above EMA21 (universe) `{mb['above21_pct']:.0f}%`" if mb else ""
    if pb and pb.get("lists"):
        P, p1, p5 = pb["lists"], pb.get("lists_1d"), pb.get("lists_5d")
        lines = [f"**Breadth** · monitored pool `{pb['n']}` names{above}"]
        lines += [f"- {k} `{P[k]}`{delta(P, p1, p5, k)}" for k in ("Leading", "Mediocre", "Lagging")]
        fd = pb.get("flow_daily") or []
        if pb.get("flow5") is not None:
            lines.append(f"Pool flow 5d `{pb['flow5']:+.1f}%` ({pb.get('up_5d', 0)} up, {pb.get('down_5d', 0)} down)"
                         + (" · daily " + " ".join(f"`{x:+.1f}%`" for x in fd[-5:]) if fd else ""))
    else:
        lines = [f"**Breadth**{above}"]
    if mb:
        L, l1, l5 = mb["lists"], mb.get("lists_1d"), mb.get("lists_5d")
        lines.append(f"Universe lists L `{L['Leading']}`{delta(L, l1, l5, 'Leading')} · M `{L['Mediocre']}`{delta(L, l1, l5, 'Mediocre')}"
                     f" · G `{L['Lagging']}`{delta(L, l1, l5, 'Lagging')}")
        iq = mb.get("iwm_vs_qqq_21d")
        iw = (f"IWM {'>' if mb['iwm_above9'] else '<'}9 {'>' if mb['iwm_above21'] else '<'}21" if mb.get("iwm_above9") is not None else "")
        parts = ([f"IWM vs QQQ 1M `{iq:+.1f}` pts"] if iq is not None else []) + ([iw] if iw else []) \
            + ([f"mega caps above 9 `{mb['mega_above9']}/{mb['mega_n']}`"] if mb.get("mega_n") else []) \
            + [f"leaders below 9 `{mb['leaders_below9']}/{mb['leaders_n']}` below 21 `{mb['leaders_below21']}/{mb['leaders_n']}`"]
        lines.append(" · ".join(parts))
        st = ", ".join(f"{t} {n}" for t, n in mb.get("scan_themes") or [])
        lines.append(f"Scan +4%: `{mb['scan_n']}` names" + (f" · together: {st}" if st else ""))
    return lines


def pool_card(pb: Optional[dict]) -> Optional[dict]:
    """Solo i campi del pool che servono alla card (niente membri e serie)."""
    if not pb:
        return None
    return {k: pb.get(k) for k in ("n", "lists", "lists_1d", "lists_5d", "share", "flow5", "flow_daily", "up_5d", "down_5d")}
