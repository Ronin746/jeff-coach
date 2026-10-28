"""Report di performance del giornale: settimanale (lunedì) e mensile con "cosa migliorare".

Uso:
  python -m jeffcoach.report weekly [--end YYYY-MM-DD]
  python -m jeffcoach.report monthly [--end YYYY-MM-DD]
Scrive data/reports/performance_<tipo>_<data>.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C
from . import journal as J
from .calendar_us import today_rome
from .output import write_atomic

DIMENSIONS = [("side", "Lato"), ("setup", "Setup"), ("theme", "Tema"), ("theme_phase", "Fase del tema"),
              ("trigger_tf", "Timeframe del trigger"), ("time_bucket", "Fascia oraria"), ("grade", "Voto revisione"),
              ("bias", "Bias del giorno"), ("stop_bucket", "Ampiezza stop"), ("dv_bucket", "Liquidità"),
              ("rules_version", "Versione regole")]
MIN_TRADES_VERDICT = 20


def _frame() -> pd.DataFrame:
    rows = J.read_csv(J.TRADES)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("r_multiple", "pnl_usd", "stop_pct", "minutes_from_open", "dv5", "mfe_r", "mae_r", "days_held"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["shadow"] = df["shadow"] == "1"
    df["date_close"] = pd.to_datetime(df["date_close"])
    m = df["minutes_from_open"]
    df["time_bucket"] = np.select([m < 15, m < 60, m < 180], ["0-15 min", "15-60 min", "1-3 ore"], "dopo 3 ore")
    df["stop_bucket"] = np.select([df.stop_pct < 1, df.stop_pct < 1.5], ["<1%", "1-1,5%"], ">=1,5%")
    df["dv_bucket"] = np.where(df.dv5 >= C.DV_TIER, ">=500M", "<500M")
    return df


def stats(g: pd.DataFrame) -> dict:
    r = g.r_multiple.dropna()
    if not len(r):
        return dict(n=0)
    eq = r.cumsum()
    streak = cur = 0
    for v in r:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    return dict(n=len(r), win=(r > 0).mean(), avg_win=r[r > 0].mean() if (r > 0).any() else 0.0,
                avg_loss=r[r <= 0].mean() if (r <= 0).any() else 0.0, exp=r.mean(), sum_r=r.sum(),
                max_dd_r=float((eq - eq.cummax()).min()), streak=streak, best=r.max(), mfe=g.mfe_r.mean())


def _line(name, s):
    if not s.get("n"):
        return f"| {name} | 0 | | | | |"
    return (f"| {name} | {s['n']} | {s['win']:.0%} | {s['exp']:+.2f} | {s['sum_r']:+.1f} | "
            f"{s['avg_win']:+.2f} / {s['avg_loss']:+.2f} | {s['streak']} | {s['best']:+.1f} |")


HEAD = "| Gruppo | Trade | Win rate | Expectancy (R) | Somma R | Media vinc./perd. | Max perdite di fila | Migliore |\n|---|---|---|---|---|---|---|---|"


def build(kind: str, end: date) -> str:
    df = _frame()
    start = end - timedelta(days=7 if kind == "weekly" else 31)
    title = f"# Performance {'settimanale' if kind == 'weekly' else 'mensile'} — {start} → {end}"
    if df.empty:
        return title + "\n\nNessun trade chiuso nel giornale.\n"
    per = df[(df.date_close > pd.Timestamp(start)) & (df.date_close <= pd.Timestamp(end))]
    real, shadow = per[~per.shadow], per[per.shadow]
    out = [title, ""]
    eq = J.read_csv(J.EQUITY)
    if eq:
        last = eq[-1]
        out.append(f"Equity simulata {float(last['equity_mtm']):,.0f} (partenza {C.START_EQUITY:,.0f}), drawdown {last['drawdown_pct']}%.")
        out.append("")
    out += ["## Sintesi", "", HEAD, _line("Trade veri", stats(real)), _line("Trade ombra (filtrati)", stats(shadow)),
            _line("Totale storico veri", stats(df[~df.shadow])), ""]
    # perché i filtri: quanto avrebbero reso i trade scartati, per motivo
    if len(shadow):
        out += ["## Filtri: cosa hanno scartato", "", HEAD]
        for k, g in shadow.groupby("shadow_reason"):
            out.append(_line(k or "?", stats(g)))
        out.append("")
    base = df[~df.shadow] if kind == "monthly" else real
    for col, name in DIMENSIONS:
        if col not in base or base[col].isna().all():
            continue
        out += [f"## Per {name.lower()}", "", HEAD]
        for k, g in base.groupby(col):
            out.append(_line(str(k) or "-", stats(g)))
        out.append("")
    if kind == "monthly":
        out += ["## Cosa migliorare (proposte, da approvare)", ""]
        props = []
        for col, name in DIMENSIONS:
            if col not in base:
                continue
            for k, g in base.groupby(col):
                s = stats(g)
                if s.get("n", 0) >= MIN_TRADES_VERDICT and s["exp"] < 0:
                    props.append(f"- {name} = **{k}**: {s['n']} trade, expectancy {s['exp']:+.2f}R → valutare di escluderlo o ridurre il rischio.")
        for k, g in df[df.shadow].groupby("shadow_reason"):
            s = stats(g)
            if s.get("n", 0) >= MIN_TRADES_VERDICT and s["exp"] > 0.3:
                props.append(f"- Filtro **{k}**: i {s['n']} trade scartati avrebbero reso {s['exp']:+.2f}R di media → il filtro forse toglie edge.")
        out += props or [f"- Nessuna proposta: servono almeno {MIN_TRADES_VERDICT} trade per gruppo."]
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["weekly", "monthly"])
    ap.add_argument("--end")
    a = ap.parse_args(argv)
    end = date.fromisoformat(a.end) if a.end else today_rome()
    md = build(a.kind, end)
    p = C.REPORTS / f"performance_{a.kind}_{end}.md"
    write_atomic(p, md, as_json=False)
    print(json.dumps({"report": str(p)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
