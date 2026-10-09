"""Grafico per gli alert di Sydney "· Channel" [RONIN 09/10].

Sopra: daily degli ultimi ~6 mesi (candele), EMA9, EMA21, SMA50 e le due linee del canale rialzista (lettura D),
prolungate fino a oggi. Sotto: close delle barre a 65 minuti degli ultimi giorni con la SMA30 65m.
Ritorna i byte di un PNG, oppure None se manca matplotlib o i dati: l'alert parte comunque, senza immagine.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Optional

import pandas as pd

from . import config as C
from . import indicators as I

log = logging.getLogger("jeffcoach.chart")

BG, FG, GRID = "#1e1f22", "#dcddde", "#3a3c40"
UP, DN = "#2fae60", "#d9534f"


def _daily(ticker: str) -> Optional[pd.DataFrame]:
    import yfinance as yf
    df = yf.download(ticker, period="1y", interval="1d", auto_adjust=False, prepost=False, progress=False)
    if df is None or not len(df):
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def channel_chart(c: dict, buckets: Optional[list] = None, price: Optional[float] = None,
                  sma65: Optional[float] = None, bars: int = 130) -> Optional[bytes]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        log.info("matplotlib non installato: alert senza grafico")
        return None
    try:
        df = _daily(c["ticker"])
        if df is None or len(df) < 60:
            return None
        if price is not None:                     # la barra di oggi con il prezzo dell'alert
            today = pd.Timestamp(date.today())
            if df.index[-1].normalize() < today:
                df.loc[today] = dict(Open=price, High=price, Low=price, Close=price, Volume=0)
        e9, e21, s50 = I.ema(df.Close, 9), I.ema(df.Close, 21), I.sma(df.Close, 50)
        d = df.iloc[-bars:]
        x = range(len(d))
        pos = {ts.date().isoformat(): i for i, ts in enumerate(d.index)}

        if not buckets or len(buckets) < 60:      # per vedere la SMA30 65m su tutto il riquadro servono ~15 giorni
            try:
                import yfinance as yf
                from .data import buckets_65m
                f = yf.download(c["ticker"], period="15d", interval="5m", prepost=False, auto_adjust=False, progress=False)
                if isinstance(f.columns, pd.MultiIndex):
                    f.columns = f.columns.get_level_values(0)
                buckets = buckets_65m(f) or buckets
            except Exception:
                pass
        two = bool(buckets)
        fig = plt.figure(figsize=(9, 6.2 if two else 4.6), dpi=110, facecolor=BG)
        gs = fig.add_gridspec(2 if two else 1, 1, height_ratios=[3, 1.3] if two else [1], hspace=0.28)
        ax = fig.add_subplot(gs[0])
        ax.set_facecolor(BG)
        for i, (_, r) in enumerate(d.iterrows()):
            col = UP if r.Close >= r.Open else DN
            ax.vlines(i, r.Low, r.High, color=col, lw=0.8)
            ax.vlines(i, min(r.Open, r.Close), max(r.Open, r.Close), color=col, lw=3.2)
        ax.plot(x, e9.iloc[-bars:].values, color="#5aa9ff", lw=1, label="EMA9")
        ax.plot(x, e21.iloc[-bars:].values, color="#f0ad4e", lw=1, label="EMA21")
        ax.plot(x, s50.iloc[-bars:].values, color="#b07cff", lw=1, label="SMA50")

        ln = c.get("lines")
        if ln:
            # linee prolungate fino all'ultima barra: valore = valore all'ancora + pendenza × barre trascorse
            idx = [ts.date().isoformat() for ts in df.index]
            if ln["end"] in idx:
                e_i = idx.index(ln["end"])
                s_i = idx.index(ln["start"]) if ln["start"] in idx else 0
                off = len(df) - len(d)
                xs = [max(s_i - off, 0), len(d) - 1]
                for v1 in [v for v in (ln.get("up1"), ln.get("lo1")) if v is not None]:
                    ys = [v1 + ln["slope"] * ((xx + off) - e_i) for xx in xs]
                    ax.plot(xs, ys, color="#e0e0e0", lw=1.2, ls="--")
        if price is not None:
            ax.axhline(price, color="#f39c12", lw=0.8, ls=":")
        ax.set_title(f"{c['ticker']} · daily · {c.get('chart_title') or 'channel: ' + str(c.get('state', ''))}",
                     color=FG, fontsize=10, loc="left")
        ticks = list(range(0, len(d), max(len(d) // 6, 1)))
        ax.set_xticks(ticks, [d.index[i].strftime("%d/%m") for i in ticks])
        ax.legend(loc="upper left", fontsize=7, facecolor=BG, labelcolor=FG, framealpha=0.6)

        if two:
            bx = fig.add_subplot(gs[1])
            bx.set_facecolor(BG)
            b = buckets[-60:]
            closes = [q[2] for q in buckets]
            sma = pd.Series(closes).rolling(C.SMA65_LEN).mean().iloc[-len(b):].values
            bx.plot(range(len(b)), [q[2] for q in b], color=FG, lw=1, label="65m close")
            bx.plot(range(len(b)), sma, color="#f39c12", lw=1.2, label="SMA30 65m")
            day_starts = [i for i in range(len(b)) if i == 0 or b[i][0] != b[i - 1][0]]
            bx.set_xticks(day_starts, [b[i][0][8:10] + "/" + b[i][0][5:7] for i in day_starts])
            bx.legend(loc="upper left", fontsize=7, facecolor=BG, labelcolor=FG, framealpha=0.6)
            bx.set_title("65 min", color=FG, fontsize=9, loc="left")
            axes = [ax, bx]
        else:
            axes = [ax]
        for a in axes:
            a.tick_params(colors=FG, labelsize=7)
            a.grid(color=GRID, lw=0.5)
            for sp in a.spines.values():
                sp.set_color(GRID)
            a.yaxis.tick_right()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as e:
        log.warning("grafico %s: %s", c.get("ticker"), e)
        return None
