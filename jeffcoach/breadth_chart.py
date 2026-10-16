"""Parte del regime in cima alla card [RONIN 16/10]: grafico dello studio 20% (titoli +20% e -20% in 5 sedute, stesso
filtro di Pradeep Bonde per i due lati: c/c5 >= 1,2 oppure <= 0,8, minv3.1 >= 100.000, c >= 3) e del T2108, più la
tabella degli ultimi 20 giorni di +4% / -4%.

Fonti: righe di Stockbee (foglio / NEL / archivio) per ±4% e T2108; la replica nostra sull'universo completo per lo
studio 20% (Stockbee non lo pubblica) e per le sedute che mancano a Stockbee.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

log = logging.getLogger("jeffcoach.breadth_chart")

BG, FG, GRID = "#1e1f22", "#dcddde", "#3a3c40"
UP, DN, LINE = "#2fae60", "#d9534f", "#5aa9ff"


def mm_history(stockbee_rows: list[dict], own_rows: list[dict], as_of, n: int = 130) -> list[dict]:
    """Ultime `n` sedute fino ad `as_of` (dalla più vecchia): date, up4, down4, t2108 (Stockbee se c'è, altrimenti
    nostro calibrato), up20w, down20w (nostri), source."""
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    by: dict[str, dict] = {}
    for r in own_rows or []:
        if r.get("date") and r["date"] <= day:
            by[r["date"]] = dict(date=r["date"], up4=r.get("up4"), down4=r.get("down4"), t2108=r.get("t2108"),
                                 up20w=r.get("up20w"), down20w=r.get("down20w"), source="own")
    for r in stockbee_rows or []:
        d = r.get("date")
        if not d or d > day or r.get("up4") is None:
            continue
        x = by.setdefault(d, dict(date=d, up20w=None, down20w=None))
        x.update(up4=r["up4"], down4=r["down4"], t2108=r.get("t2108", x.get("t2108")), source="Stockbee")
    return [by[d] for d in sorted(by)][-n:]


def table_20d(hist: list[dict], n: int = 20) -> str:
    """Mini tabella degli ultimi 20 giorni di +4% / -4% (blocco di codice per Discord), dalla più recente.
    Il segno ▲/▼ indica il lato dominante del giorno (acquisti o vendite, come le legge Pradeep)."""
    rows = [r for r in hist if r.get("up4") is not None][-n:][::-1]
    if not rows:
        return ""
    cells = [f"{r['date'][8:10]}/{r['date'][5:7]} {r['up4']:4.0f} {r['down4']:4.0f}"
             + ("▲" if r["up4"] > r["down4"] else ("▼" if r["down4"] > r["up4"] else "=")) for r in rows]
    half = (len(cells) + 1) // 2               # due colonne strette (si leggono anche dal telefono)
    left, right = cells[:half], cells[half:]
    head = "date   +4%  -4% "
    out = [f"{head}  | {head}"]
    for i, c in enumerate(left):
        out.append(f"{c}  | {right[i]}" if i < len(right) else c)
    return "```\n" + "\n".join(out) + "\n```"


def render(hist: list[dict], up20_threshold: float = 200, down20_threshold: float = 200,
           t2108_levels: tuple = (10, 20, 65)) -> Optional[bytes]:
    """PNG: studio 20% (+20% verde sopra, -20% rosso sotto, stesso filtro) e T2108. None se mancano i dati."""
    h = [r for r in hist if r.get("up20w") is not None or r.get("t2108") is not None]
    if len(h) < 10:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        log.warning("matplotlib: %s", e)
        return None
    x = list(range(len(h)))
    up = [r.get("up20w") or 0 for r in h]
    dn = [r.get("down20w") or 0 for r in h]
    t = [r.get("t2108") for r in h]
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(9, 5.2), sharex=True, gridspec_kw=dict(height_ratios=[1.2, 1.0, 1.1]))
    fig.patch.set_facecolor(BG)
    for a in (a1, a2, a3):
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=7)
        a.grid(color=GRID, lw=0.5)
        for s in a.spines.values():
            s.set_color(GRID)
    a1.bar(x, up, color=UP, width=0.8)
    a1.axhline(up20_threshold, color=FG, lw=0.7, ls="--")
    a1.set_title(f"Up 20% in 5 days  {up[-1]:.0f}   (c/c5>=1.2 · minv3.1>=100k · c>=3) · threshold {up20_threshold:.0f}", color=FG, fontsize=8, loc="left")
    a2.bar(x, dn, color=DN, width=0.8)
    a2.axhline(down20_threshold, color=FG, lw=0.7, ls="--")
    a2.set_title(f"Down 20% in 5 days  {dn[-1]:.0f}   (c/c5<=0.8 · same filter) · threshold {down20_threshold:.0f}", color=FG, fontsize=8, loc="left")
    tx = [i for i, v in zip(x, t) if v is not None]
    a3.plot(tx, [v for v in t if v is not None], color=LINE, lw=1.3)
    for lv in t2108_levels:
        a3.axhline(lv, color=UP if lv <= 20 else DN, lw=0.6, ls="--")
    a3.set_ylim(0, 100)
    last_t = next((v for v in reversed(t) if v is not None), None)
    a3.set_title("T2108" + (f"  {last_t:.0f}%" if last_t is not None else "") + "   (<20 bullish · <10 very · >65 extended)",
                 color=FG, fontsize=8, loc="left")
    ticks = list(range(0, len(h), max(1, len(h) // 8)))
    a3.set_xticks(ticks)
    a3.set_xticklabels([h[i]["date"][5:] for i in ticks], color=FG, fontsize=7)
    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
