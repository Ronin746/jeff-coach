"""Grafico di METS per Sydney [ANDREA 29/10: Jeff torna alla versione di prima (main @36a11c0) con "la parte di charting
e supporti" di METS]. Copia di martincoach/chart.py (Martin-coach, istanza multi-edge, regole 2026-10-28b-meta):
daily in scala logaritmica con EMA 9/21/50/150, livello dell'alert, trendline e canali paralleli (trendlines.py),
supporti e resistenze orizzontali come linee o aree (orizzontali.py); niente pannello intraday sotto (METS dal 28/10).

Testo originale di Martin:
Grafico degli alert di Dua, nello stile degli alert di Sydney [RONIN 13/10].

Sopra: daily degli ultimi ~6 mesi (candele, scala logaritmica come i grafici di Martin) con EMA 9/21/50/150 [ML], il
livello di confluenza, la trendline rialzista e quella ribassista con i loro canali paralleli (trendlines.py, le stesse
del multi-edge: calcolate sulle barre fino a ieri e prolungate a oggi) [RONIN 22/10].
Sotto: intraday di oggi a candele nel timeframe del trigger (1m nei primi 15 minuti, 5m fino a 60, poi 15m),
con livello, entrata, stop, eventuale uscita e VWAP del giorno.
Ritorna i byte di un PNG, oppure None (l'alert parte comunque, senza immagine).
"""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from . import config as C
from .. import data as D
from . import indicators as I
from . import orizzontali as HZ
from . import trendlines as TL
from ..calendar_us import open_et

log = logging.getLogger("jeffcoach.mets.chart")

BG, FG, GRID = "#1e1f22", "#dcddde", "#3a3c40"
UP, DN = "#2fae60", "#d9534f"
EMA_COLORS = {9: "#5aa9ff", 21: "#f0ad4e", 50: "#b07cff", 150: "#8a8d93"}
LEVEL_C, ENTRY_C, STOP_C, EXIT_C, VWAP_C = "#f39c12", "#ffffff", "#e74c3c", "#f1c40f", "#c39bd3"
TL_COLORS = {"up": "#ffffff", "down": "#ffffff"}     # trendline e canali tutti bianchi [RONIN 22/10, Andrea]
HZ_COLOR, HZ_ALPHA = "#ffffff", 0.06                  # orizzontali bianche, aree semitrasparenti [RONIN 23/10, Andrea]
HZ_W_ALPHA, HZ_D_ALPHA = 0.6, 0.4                     # linee discrete: weekly un po' più marcati dei daily [23/10]


def _log_axis(ax) -> None:
    """Scala logaritmica con etichette in prezzo (niente notazione 10^n)."""
    from matplotlib import ticker
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=7))
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v:,.2f}" if v < 10 else f"{v:,.0f}"))
    ax.yaxis.set_minor_formatter(ticker.NullFormatter())


def draw_horizontals(ax, base: pd.DataFrame, ylim: tuple) -> None:
    """Supporti e resistenze orizzontali di `base` (barre fino a ieri; daily e weekly) come nei grafici TradingView di
    Andrea [RONIN 23/10]: linee bianche sottili e semitrasparenti; le aree come rettangolo bianco leggero con i bordi
    marcati come linee normali; il prezzo di ogni linea e bordo in un'etichetta sull'asse destro. Al massimo
    HZ_CHART_MAX livelli nella scala del grafico, anche di mesi e anni prima: prima il più vicino sopra e sotto il prezzo,
    poi i più forti, ad almeno HZ_CHART_GAP_ADR ADR l'uno dall'altro. I weekly un po' più marcati dei daily."""
    adr = I.adr_pct(base, C.ADR_LEN)
    close = float(base.Close.iloc[-1])
    y0, y1 = ylim
    ax.set_ylim(ylim)
    vis = [x for x in HZ.find_levels(base, adr) if x["hi"] >= y0 and x["lo"] <= y1]
    gap = 1 + C.HZ_CHART_GAP_ADR * adr / 100
    near = [min((x for x in vis if x["lo"] > close), key=lambda x: x["lo"], default=None),
            max((x for x in vis if x["hi"] < close), key=lambda x: x["hi"], default=None),
            next((x for x in vis if x["lo"] <= close <= x["hi"]), None)]
    show = []
    for x in [y for y in near if y] + sorted(vis, key=lambda x: -x["score"]):
        if len(show) >= C.HZ_CHART_MAX:
            break
        if all(x is not y and (x["lo"] > y["hi"] * gap or x["hi"] * gap < y["lo"]) for y in show):
            show.append(x)
    tags = []
    for x in show:
        a_line, lw = (HZ_W_ALPHA, 0.9) if x.get("tf") == "W" else (HZ_D_ALPHA, 0.7)
        vals = (x["lo"], x["hi"]) if x["kind"] == "zone" else (x["price"],)
        if x["kind"] == "zone":
            ax.axhspan(x["lo"], x["hi"], color=HZ_COLOR, alpha=HZ_ALPHA, lw=0, zorder=0.5)
        for v in vals:
            ax.axhline(v, color=HZ_COLOR, lw=lw, alpha=a_line, zorder=1)
            tags.append(v)
    # etichette sull'asse destro senza sovrapporsi: dal basso, almeno 10 pixel l'una dall'altra
    tags = sorted(v for v in tags if y0 <= v <= y1)
    px = [ax.transData.transform((0, v))[1] for v in tags]
    pos, last = [], -1e9
    for p in px:
        q = max(p, last + 10)
        pos.append(q)
        last = q
    k = 72.0 / ax.figure.dpi
    for v, p, q in zip(tags, px, pos):
        ax.annotate(f"{v:.2f}", xy=(1, v), xycoords=("axes fraction", "data"), xytext=(2, (q - p) * k),
                    textcoords="offset points", va="center", ha="left", fontsize=6, color="#000000",
                    annotation_clip=False, zorder=6,
                    bbox=dict(boxstyle="square,pad=0.12", fc=HZ_COLOR, alpha=0.7, ec="none"))


def draw_trendlines(ax, df: pd.DataFrame, base: pd.DataFrame, n_plot: int, side: str) -> None:
    """Trendline e canali di `base` (barre fino a ieri) sul pannello daily che mostra le ultime `n_plot` barre di `df`
    (base più, eventualmente, la barra di oggi). La linea nel verso del trade è più spessa; i pallini sono gli swing che
    la toccano."""
    adr = I.adr_pct(base, C.ADR_LEN)
    lines = TL.find_lines(base, adr)
    off = len(df) - n_plot                       # posizione in df della prima barra disegnata
    last = len(df) - 1
    for kind in ("up", "down"):
        L = lines.get(kind)
        if not L:
            continue
        col = TL_COLORS[kind]
        main = (kind == "up") == (side == "long")
        p0 = max(L["i0"], off)
        xs = [p0 - off, last - off]
        ax.plot(xs, [TL.value_at(L, p0), TL.value_at(L, last)], color=col, lw=1.1 if main else 0.7,
                alpha=0.8 if main else 0.5, label=f"TL {kind} · {L['touches']} touches")
        pos = [p for p in df.index.get_indexer(pd.to_datetime(L["touch_dates"])) if p >= off]
        if pos:
            ys = [float(df.Low.iloc[p] if kind == "up" else df.High.iloc[p]) for p in pos]
            ax.scatter([p - off for p in pos], ys, s=7, color=col, alpha=0.8 if main else 0.5, zorder=5, lw=0)
        ch = L.get("channel")
        if ch:
            ax.plot(xs, [TL.value_at(L, p0, True), TL.value_at(L, last, True)], color=col, lw=0.7,
                    ls="--", alpha=0.55 if main else 0.35, label=f"channel · {ch['touches']} touches")


def _candles(ax, d: pd.DataFrame, width: float = 3.2) -> None:
    for i, (_, r) in enumerate(d.iterrows()):
        col = UP if r.Close >= r.Open else DN
        ax.vlines(i, r.Low, r.High, color=col, lw=0.8)
        ax.vlines(i, min(r.Open, r.Close), max(r.Open, r.Close), color=col, lw=width)


def _style(axes) -> None:
    for a in axes:
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=7)
        a.grid(color=GRID, lw=0.5)
        for sp in a.spines.values():
            sp.set_color(GRID)
        a.yaxis.tick_right()


def _resample(b: pd.DataFrame, tf: int, today: date) -> pd.DataFrame:
    if tf <= 1:
        return b
    return b.resample(f"{tf}min", origin=open_et(today), label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna(subset=["Close"])


def alert_chart(ticker: str, side: str, intraday: Optional[pd.DataFrame], tf: int, today: date,
                level: Optional[float] = None, entry: Optional[float] = None, stop: Optional[float] = None,
                exit_px: Optional[float] = None, title: str = "", daily: Optional[pd.DataFrame] = None,
                bars: int = 130, panel: bool = True, areas: Optional[list] = None) -> Optional[bytes]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        log.info("matplotlib non installato: alert senza grafico")
        return None
    try:
        if daily is None:
            daily = D.download_daily([ticker], (today - timedelta(days=C.CHART_DAILY_DAYS)).isoformat(), today).get(ticker)
        if daily is None or len(daily) < 30:
            return None
        df = daily.copy()
        if intraday is not None and len(intraday):            # la barra di oggi aggiornata con l'intraday
            o, h, lo, c = float(intraday.Open.iloc[0]), float(intraday.High.max()), float(intraday.Low.min()), float(intraday.Close.iloc[-1])
            df.loc[pd.Timestamp(today)] = dict(Open=o, High=h, Low=lo, Close=c, Volume=float(intraday.Volume.sum()))
            df = df[~df.index.duplicated(keep="last")].sort_index()
        emas = {n: I.ema(df.Close, n) for n in EMA_COLORS}
        d = df.iloc[-bars:]
        x = range(len(d))
        two = panel and intraday is not None and len(intraday) >= 2      # pannello intraday sotto [tolto 28/10, Andrea]
        fig = plt.figure(figsize=(9, 6.6 if two else 4.6), dpi=110, facecolor=BG)
        gs = fig.add_gridspec(2 if two else 1, 1, height_ratios=[3, 1.9] if two else [1], hspace=0.3)
        ax = fig.add_subplot(gs[0])
        _candles(ax, d)
        for n, e in emas.items():
            ax.plot(x, e.iloc[-bars:].values, color=EMA_COLORS[n], lw=1, label=f"EMA{n}")
        if level is not None:
            ax.axhline(level, color=LEVEL_C, lw=1, ls="--", label=f"level {level:.2f}")
        for lo_a, hi_a in areas or []:              # aree dell'ETF del gruppo [RONIN 28/10]
            ax.axhspan(lo_a, hi_a, color=LEVEL_C, alpha=0.12, lw=0)
        if C.TL_CHART or C.HZ_CHART:   # istanza multi-edge: scala log, trendline, canali e orizzontali [RONIN 22-23/10]
            _log_axis(ax)
            ylim = ax.get_ylim()
            base = daily[daily.index < pd.Timestamp(today)]         # barre fino a ieri: le stesse della lista
            if C.HZ_CHART and len(base) >= 60:
                try:
                    draw_horizontals(ax, base, ylim)
                except Exception as e:
                    log.warning("orizzontali %s: %s", ticker, e)
            if C.TL_CHART and len(base) >= 60:
                try:
                    draw_trendlines(ax, df, base, len(d), side)
                except Exception as e:
                    log.warning("trendline %s: %s", ticker, e)
            ax.set_ylim(ylim)                                 # le linee non schiacciano le candele
            ax.set_xlim(-1, len(d))
        ax.set_title(f"{ticker} · daily{' (log)' if (C.TL_CHART or C.HZ_CHART) else ''} · {title}".rstrip(" ·"), color=FG, fontsize=10,
                     loc="left")
        ticks = list(range(0, len(d), max(len(d) // 6, 1)))
        ax.set_xticks(ticks, [d.index[i].strftime("%d/%m") for i in ticks])
        if C.TL_CHART or C.HZ_CHART:
            ax.legend(loc="upper left", fontsize=6.5, facecolor=BG, labelcolor=FG, framealpha=0.6, ncol=3)
        else:
            ax.legend(loc="upper left", fontsize=7, facecolor=BG, labelcolor=FG, framealpha=0.6)
        axes = [ax]
        if two:
            bx = fig.add_subplot(gs[1])
            rb = _resample(intraday, tf, today)
            if len(rb) < 4 and tf > 1:
                rb, tf = intraday, 1
            _candles(bx, rb, width=min(10.0, max(1.4, 200.0 / max(len(rb), 1))))
            xi = range(len(rb))
            tp = (intraday.High + intraday.Low + intraday.Close) / 3
            vw = (tp * intraday.Volume).cumsum() / intraday.Volume.cumsum().replace(0, float("nan"))
            vw = vw.reindex(rb.index, method="ffill") if tf > 1 else vw
            bx.plot(xi, vw.values, color=VWAP_C, lw=0.9, label="VWAP")
            for v, c, ls, lab in ((level, LEVEL_C, "--", "level"), (entry, ENTRY_C, "-", "entry"),
                                  (stop, STOP_C, "--", "stop"), (exit_px, EXIT_C, ":", "exit")):
                if v is not None:
                    bx.axhline(v, color=c, lw=1, ls=ls, label=f"{lab} {v:.2f}")
            lo_y = min([float(rb.Low.min())] + [v for v in (stop, entry, exit_px) if v is not None])
            hi_y = max([float(rb.High.max())] + [v for v in (stop, entry, exit_px) if v is not None])
            if level is not None and abs(level / float(rb.Close.iloc[-1]) - 1) < 0.04:
                lo_y, hi_y = min(lo_y, level), max(hi_y, level)
            pad = (hi_y - lo_y) * 0.08 or hi_y * 0.002
            bx.set_ylim(lo_y - pad, hi_y + pad)
            step = max(len(rb) // 7, 1)
            bx.set_xticks(list(range(0, len(rb), step)), [rb.index[i].strftime("%H:%M") for i in range(0, len(rb), step)])
            bx.legend(loc="upper left", fontsize=7, facecolor=BG, labelcolor=FG, framealpha=0.6, ncol=3)
            bx.set_title(f"{tf}m · today (New York time)", color=FG, fontsize=9, loc="left")
            axes.append(bx)
        _style(axes)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as e:
        log.warning("grafico %s: %s", ticker, e)
        return None


def focus_charts(rows: list[dict], session: date, as_of: date, work) -> dict[str, str]:
    """Grafici daily dei Focus per la card del multi-edge [ANDREA 28/10]: solo il titolo (niente ETF del gruppo), con
    il livello del Focus, trendline e orizzontali come negli alert. Scrive focus_<TICKER>.png in `work` e restituisce
    {ticker: nome del file}; un grafico che non riesce manca e basta."""
    for p in work.glob("focus_*.png"):              # niente grafici di Focus usciti dalla lista
        p.unlink()
    tick = sorted({r["ticker"] for r in rows})
    if not tick:
        return {}
    try:
        daily = D.download_daily(tick, (as_of - timedelta(days=C.CHART_DAILY_DAYS)).isoformat(), as_of)
    except Exception as e:
        log.warning("grafici dei Focus: %s", e)
        return {}
    out = {}
    for r in rows:
        t = r["ticker"]
        if t in out or daily.get(t) is None:
            continue
        lv = r.get("level")
        title = f"focus {r['side']}" + (f" · level {lv:.2f}" if lv else "")
        png = alert_chart(t, r["side"], None, 5, session, level=lv, title=title, daily=daily[t], panel=False)
        if png:
            fn = f"focus_{t.replace('.', '-').replace('/', '-')}.png"
            (work / fn).write_bytes(png)
            out[t] = fn
    return out


def gallery(embed: dict, tickers: list[str], charts: dict[str, str]) -> list[dict]:
    """Grafici dei Focus sotto il loro riquadro della card, come METS (output.with_focus_charts): gallerie di Discord
    da 4 immagini (riquadri con lo stesso url uniti in uno; aprendo un'immagine si scorre con le frecce). Il primo
    grafico va nel riquadro del testo se non ha già un'immagine. Restituisce i riquadri da mettere SUBITO DOPO `embed`
    (che può essere modificato)."""
    out = []
    fns = [(t, charts[t]) for t in tickers if t in charts]
    for k in range(0, len(fns), 4):
        grp = fns[k:k + 4]
        url = f"https://www.tradingview.com/symbols/{grp[0][0]}/"
        first = embed if k == 0 and "image" not in embed else None
        for j, (t, fn) in enumerate(grp):
            if j == 0 and first is not None:
                first["url"], first["image"] = url, {"url": f"attachment://{fn}"}
            else:
                out.append({"url": url, "color": embed.get("color"), "image": {"url": f"attachment://{fn}"}})
    return out


def jeff_alert_chart(ticker: str, side: str, intraday: Optional[pd.DataFrame], today: date,
                     level: Optional[float] = None, title: str = "") -> Optional[bytes]:
    """Grafico degli alert di Sydney nello stile di METS: daily (con la barra di oggi aggiornata dall'intraday), livello
    dell'alert, trendline, canali e orizzontali; niente pannello intraday."""
    return alert_chart(ticker, side, intraday, 5, today, level=level, title=title, panel=False)
