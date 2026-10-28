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
UP, DN, LINE, MID = "#2fae60", "#d9534f", "#5aa9ff", "#e3b341"


def mm_history(stockbee_rows: list[dict], own_rows: list[dict], as_of, n: int = 130) -> list[dict]:
    """Ultime `n` sedute fino ad `as_of` (dalla più vecchia): date, up4, down4, t2108 (Stockbee se c'è, altrimenti
    nostro calibrato), up20w, down20w (nostri), source."""
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
    by: dict[str, dict] = {}
    for r in own_rows or []:
        if r.get("date") and r["date"] <= day:
            by[r["date"]] = dict(date=r["date"], up4=r.get("up4"), down4=r.get("down4"), t2108=r.get("t2108"),
                                 up20w=r.get("up20w"), down20w=r.get("down20w"), nh=r.get("nh"), nl=r.get("nl"),
                                 source="own")
    for r in stockbee_rows or []:
        d = r.get("date")
        if not d or d > day or r.get("up4") is None:
            continue
        x = by.setdefault(d, dict(date=d, up20w=None, down20w=None, nh=None, nl=None))
        x.update(up4=r["up4"], down4=r["down4"], t2108=r.get("t2108", x.get("t2108")), source="Stockbee")
    return [by[d] for d in sorted(by)][-n:]


def lists_panel(a, x: list[int], rows: list[Optional[dict]], universe: bool = True) -> None:
    """Liste di Martin in % [RONIN 27/10, Andrea: "una linea con l'andamento in % dei titoli nei tre gruppi"]: Leading
    (verde), Mediocre (giallo), Lagging (rosso) del pool, linee piene; dell'universo liquido tratteggiate e più tenui."""
    from matplotlib.lines import Line2D
    keys = (("L", UP, "Leading"), ("M", MID, "Mediocre"), ("G", DN, "Lagging"))
    for k, col, _ in keys:
        xs = [i for i, r in zip(x, rows) if r and r.get(k) is not None]
        a.plot(xs, [rows[i][k] for i in xs], color=col, lw=1.4)
        if universe:
            xu = [i for i, r in zip(x, rows) if r and r.get("u" + k) is not None]
            a.plot(xu, [rows[i]["u" + k] for i in xu], color=col, lw=0.8, ls="--", alpha=0.5)
    a.set_ylim(0, 100)
    a.set_yticks([0, 25, 50, 75, 100])
    last = next((r for r in reversed(rows) if r and r.get("L") is not None), None)
    title = "Martin lists, % of stocks"
    if last:
        title += (f"  ·  pool {last['n']}: Leading {last['L']:.0f}% · Mediocre {last['M']:.0f}% · Lagging {last['G']:.0f}%")
        if universe and last.get("uL") is not None:
            title += f"  ·  dashed: liquid universe {last['un']} ({last['uL']:.0f} / {last['uM']:.0f} / {last['uG']:.0f})"
    a.set_title(title, color=FG, fontsize=8, loc="left")
    hd = [Line2D([], [], color=col, lw=1.4, label=lab) for _, col, lab in keys]
    a.legend(handles=hd, loc="upper left", fontsize=6, ncol=3, frameon=True, facecolor=BG, edgecolor=GRID,
             labelcolor=FG, framealpha=0.85, borderpad=0.3, handlelength=1.6)


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
           t2108_levels: tuple = (10, 20, 65), lists_hist: Optional[list[dict]] = None,
           universe: bool = True) -> Optional[bytes]:
    """Un'immagine per la parte del regime [RONIN 16/10, Andrea]: studio 20% (+20% e -20% in 5 sedute, stesso
    filtro), T2108, liste di Martin in % (pool.pool_breadth 'lists_hist': Leading / Mediocre / Lagging del pool, linee
    piene, e dell'universo liquido, tratteggiate se `universe`) [RONIN 27/10], nuovi massimi e minimi a 52 settimane
    (massimi sopra lo zero, minimi sotto) e il loro delta. None se mancano i dati."""
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
    d4 = [(r["up4"] - r["down4"]) if r.get("up4") is not None and r.get("down4") is not None else None for r in h]
    nh = [r.get("nh") for r in h]
    nl = [r.get("nl") for r in h]
    by = {r["date"]: r for r in (lists_hist or []) if r.get("date")}
    lrows = [by.get(r["date"]) for r in h]
    has_lists = sum(1 for r in lrows if r and r.get("L") is not None) >= 10
    # [RONIN 19/10, Andrea] tolta la riga del delta ±4%; [RONIN 27/10] liste di Martin in % sotto il T2108
    ratios = [1.1, 0.9, 1.0] + ([1.2] if has_lists else []) + [1.1, 1.0]
    fig, ax = plt.subplots(len(ratios), 1, figsize=(9, 8.6 + (1.7 if has_lists else 0)), sharex=True,
                           gridspec_kw=dict(height_ratios=ratios))
    a1, a2, a3 = ax[:3]
    a4 = ax[3] if has_lists else None
    a5, a6 = ax[-2:]
    fig.patch.set_facecolor(BG)
    for a in ax:
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=7)
        a.grid(color=GRID, lw=0.5)
        for sp in a.spines.values():
            sp.set_color(GRID)
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
    if a4 is not None:
        lists_panel(a4, x, lrows, universe)

    def delta(a, vals, title):
        xi = [i for i, v in zip(x, vals) if v is not None]
        vv = [v for v in vals if v is not None]
        a.bar(xi, vv, color=[UP if v >= 0 else DN for v in vv], width=0.8)
        a.axhline(0, color=FG, lw=0.7)
        last = vv[-1] if vv else None
        a.set_title(title + (f"  {last:+.0f}" if last is not None else "  n/a"), color=FG, fontsize=8, loc="left")
    xi = [i for i, v in zip(x, nh) if v is not None]
    a5.bar(xi, [v for v in nh if v is not None], color=UP, width=0.8)
    a5.bar(xi, [-(v or 0) for v, w in zip(nl, nh) if w is not None], color=DN, width=0.8)
    a5.axhline(0, color=FG, lw=0.7)
    ln = next((i for i in range(len(h) - 1, -1, -1) if nh[i] is not None), None)
    a5.set_title("New 52w highs (up) / new lows (down)" + (f"  {nh[ln]:.0f} / {nl[ln] or 0:.0f}" if ln is not None else "  n/a"),
                 color=FG, fontsize=8, loc="left")
    delta(a6, [(a - (b or 0)) if a is not None else None for a, b in zip(nh, nl)], "Net new highs (highs − lows)")
    ticks = list(range(0, len(h), max(1, len(h) // 8)))
    a6.set_xticks(ticks)
    a6.set_xticklabels([f"{h[i]['date'][8:10]}/{h[i]['date'][5:7]}" for i in ticks], color=FG, fontsize=7)
    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def render_4pct(hist: list[dict]) -> Optional[bytes]:
    """PNG come quello dello studio 20%, per i ±4% [RONIN 16/10, Andrea]: titoli +4% (verde), titoli -4% (rosso) e
    delta (+4% meno -4%, verde sopra lo zero, rosso sotto)."""
    h = [r for r in hist if r.get("up4") is not None and r.get("down4") is not None]
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
    up = [r["up4"] for r in h]
    dn = [r["down4"] for r in h]
    dl = [u - d for u, d in zip(up, dn)]
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(9, 5.2), sharex=True, gridspec_kw=dict(height_ratios=[1, 1, 1.1]))
    fig.patch.set_facecolor(BG)
    for a in (a1, a2, a3):
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=7)
        a.grid(color=GRID, lw=0.5)
        for sp in a.spines.values():
            sp.set_color(GRID)
    a1.bar(x, up, color=UP, width=0.8)
    a1.set_title(f"Up 4% (with volume)  {up[-1]:.0f}", color=FG, fontsize=8, loc="left")
    a2.bar(x, dn, color=DN, width=0.8)
    a2.set_title(f"Down 4% (with volume)  {dn[-1]:.0f}", color=FG, fontsize=8, loc="left")
    a3.bar(x, dl, color=[UP if v >= 0 else DN for v in dl], width=0.8)
    a3.axhline(0, color=FG, lw=0.7)
    a3.set_title(f"Delta (up 4% − down 4%)  {dl[-1]:+.0f}", color=FG, fontsize=8, loc="left")
    ticks = list(range(0, len(h), max(1, len(h) // 8)))
    a3.set_xticks(ticks)
    a3.set_xticklabels([f"{h[i]['date'][8:10]}/{h[i]['date'][5:7]}" for i in ticks], color=FG, fontsize=7)
    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
