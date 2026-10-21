"""Grafico RS settimanale / RS mensile dei basket [RONIN 21/10, Andrea: "nella card inseriscine una come questa ...
all'inizio della sezione temi"], sul modello "Market Metrics - Industries": X = RS a 1 settimana, Y = RS a 1 mese
(percentili 0-100 tra i basket), quattro quadranti (Weakening in alto a sinistra, Strong in alto a destra, Weak in
basso a sinistra, Improving in basso a destra), un punto per basket colorato per quadrante, etichetta col nome."""
from __future__ import annotations

import io
import logging
from typing import Optional

log = logging.getLogger(__name__)

BG, FG, GRID = "#0d1117", "#c9d1d9", "#30363d"
QUAD = {"Strong": ("#1f6f43", "#2fae60"), "Weakening": ("#5c4a1a", "#e3b341"),
        "Improving": ("#1c3a5e", "#5aa9ff"), "Weak": ("#5e1f24", "#f0605d")}


def quadrant(rs_w: float, rs_m: float) -> str:
    """Quadrante: Strong (settimana e mese >= 50), Weakening (mese >= 50, settimana < 50), Improving, Weak."""
    if rs_m >= 50:
        return "Strong" if rs_w >= 50 else "Weakening"
    return "Improving" if rs_w >= 50 else "Weak"


def add_rs(rows: list[dict], key_w: str = "ret1w", key_m: str = "ret1m") -> list[dict]:
    """RS settimanale e mensile: rendimento equal-weight del basket a 5 e 21 sedute in percentile 0-100 tra i basket."""
    ok = [r for r in rows if r.get(key_w) is not None and r.get(key_m) is not None]
    n = len(ok)
    if not n:
        return rows

    def pct(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:                                  # pari merito: rango medio (come pandas rank(pct=True))
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = ((i + j) / 2 + 1) / n * 100
            i = j + 1
        return out
    w, m = pct([r[key_w] for r in ok]), pct([r[key_m] for r in ok])
    for r, a, b in zip(ok, w, m):
        r["rs_w"], r["rs_m"] = round(a, 1), round(b, 1)
        r["quadrant"] = quadrant(r["rs_w"], r["rs_m"])
    return rows


def render(points: list[dict], title: str = "Baskets — Week RS vs Month RS", subtitle: str = "") -> Optional[bytes]:
    """points: [{theme, rs_w, rs_m, score?}] -> PNG (None se matplotlib manca o non ci sono punti)."""
    pts = [p for p in points if p.get("rs_w") is not None and p.get("rs_m") is not None]
    if not pts:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:                      # il grafico non deve mai fermare la card
        log.warning("grafico RS: matplotlib non disponibile (%s)", e)
        return None
    fig, ax = plt.subplots(figsize=(16, 9.5), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for (x0, y0), q in (((0, 50), "Weakening"), ((50, 50), "Strong"), ((0, 0), "Weak"), ((50, 0), "Improving")):
        ax.add_patch(plt.Rectangle((x0, y0), 50, 50, color=QUAD[q][0], alpha=0.28, zorder=0, lw=0))
    for (x, y), q in (((25, 103), "Weakening"), ((75, 103), "Strong"), ((25, -3), "Weak"), ((75, -3), "Improving")):
        ax.text(x, y, q.upper(), color=QUAD[q][1], fontsize=12, fontweight="bold", alpha=0.85, ha="center", va="center", zorder=1)
    ax.axhline(50, color=GRID, lw=1, ls="--", zorder=1)
    ax.axvline(50, color=GRID, lw=1, ls="--", zorder=1)
    try:                                        # etichette che non si sovrappongono, se c'è adjustText
        from adjustText import adjust_text      # type: ignore
    except Exception:
        adjust_text = None
    texts = []
    for p in pts:
        q = quadrant(p["rs_w"], p["rs_m"])
        ax.scatter(p["rs_w"], p["rs_m"], s=46, color=QUAD[q][1], edgecolor="#000000", lw=0.6, zorder=3)
        texts.append(ax.text(p["rs_w"] + 0.6, p["rs_m"] + 0.9, p["theme"], color=FG, fontsize=7.6, zorder=4))
    if adjust_text:
        try:
            adjust_text(texts, ax=ax, expand=(1.05, 1.2), arrowprops=dict(arrowstyle="-", color=GRID, lw=0.5))
        except Exception:
            pass
    ax.set_xlim(-2, 102)
    ax.set_ylim(-6, 106)
    ax.set_xticks(range(0, 101, 20))
    ax.set_yticks(range(0, 101, 20))
    ax.tick_params(colors=FG, labelsize=10)
    for sp in ax.spines.values():
        sp.set_color(GRID)
    ax.set_xlabel("Week RS (percentile among baskets)", color=FG, fontsize=11)
    ax.set_ylabel("Month RS (percentile among baskets)", color=FG, fontsize=11)
    ax.set_title(title + (f"\n{subtitle}" if subtitle else ""), color=FG, fontsize=15, loc="left", pad=12)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
