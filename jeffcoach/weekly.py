"""Weekly watchlist del lunedì, sul close del venerdì [RONIN 06/10].

Stessi gate della daily, con queste differenze:
  - pattern, VCP (5/20/50), compressione ed EMA 9 letti su barre SETTIMANALI (W-FRI);
  - close entro 1,5 ATR settimanali dalla EMA 9 settimanale (scarto 9/21 irrilevante);
  - al posto della SMA30 65m: close entro ~5% dalla SMA 25 giornaliera;
  - RS = quello daily (pine_replay, >= 80); universo, ATR%, adv$, Atr Ext (SMA50 daily), SMA200 e utili come la daily.
Uscita: riepilogo in chat, NIENTE Discord e niente alert.

Uso: python -m jeffcoach.weekly [--monday 2026-10-12] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from datetime import date, datetime, timedelta

import pandas as pd

from . import config as C
from . import data as D
from . import engine as E
from .calendar_us import ROME, is_session, next_session, prev_session, sessions_from, today_rome
from .output import write_atomic

log = logging.getLogger("jeffcoach.weekly")


def to_weekly(df: pd.DataFrame, last_day: date) -> pd.DataFrame:
    df = df[df.index.date <= last_day]
    w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    return w.dropna(subset=["Close"])


def weekly_gates(md: dict, mw: dict) -> list[E.Gate]:
    g: list[E.Gate] = []
    rs = md.get("rs")
    g.append(E.Gate("rs", rs is not None and rs >= C.RS_FOCUS_MIN, f"RS {rs} under 80", f"RS {rs}"))
    g.append(E.Gate("sma200", md["above_sma200"] and md["sma200_slope_ok"] is True,
                    "SMA200 declining" if md["above_sma200"] else "under the SMA200"))
    ext = md.get("ext")
    g.append(E.Gate("ext", ext is not None and ext <= C.EXT_MAX, f"Atr Ext {ext:.2f}× over 4×" if ext is not None else "ext n/a", "extended"))
    s25 = md.get("sma25")
    d25 = (md["close"] / s25 - 1) * 100 if s25 else None
    g.append(E.Gate("sma25", d25 is not None and abs(d25) <= C.WEEKLY_SMA25_DAILY_MAX_PCT,
                    f"{d25:+.1f}% from the daily 25 SMA" if d25 is not None else "SMA25 n/a", "over 5% from SMA25"))
    e = mw["ema9_dist_atr"]
    g.append(E.Gate("ema9w", 0 < e <= C.WEEKLY_EMA9_MAX_ATR,
                    "under the weekly 9 EMA" if e <= 0 else f"{e:.1f} weekly ATR above the weekly 9 EMA",
                    "under weekly 9 EMA" if e <= 0 else f"{e:.1f} wATR over weekly 9 EMA"))
    v = mw.get("vcp")
    g.append(E.Gate("vcpw", v is not None and v <= C.VCP_FOCUS_MAX, f"weekly VCP {v:.1f}, loose" if v is not None else "weekly VCP n/a",
                    "loose weekly VCP" if v is not None else "weekly VCP n/a"))
    cd = mw["compression_days"]
    g.append(E.Gate("compw", cd >= C.COMPRESSION_DAYS_MIN, f"{cd} tight weeks in the last {C.COMPRESSION_WINDOW}", f"{cd} tight weeks"))
    a_ok, a_why, a_sh = E.reading_a(mw)
    b_ok, b_why, b_sh = E.reading_b(mw)
    mw.update(pattern_a_ok=a_ok, pattern_a_why=a_why, pattern_b_ok=b_ok, pattern_b_why=b_why)
    p_ok = (a_ok and b_ok) if C.WEEKLY_PATTERN_REQUIRE_BOTH else (a_ok or b_ok)
    g.append(E.Gate("pattern", p_ok, "weekly pattern: " + "; ".join(a_why[:1] + b_why[:1]),
                    "weekly pattern " + ", ".join(a_sh[:1] + b_sh[:1])))
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--monday", help="data del lunedì (default: oggi)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-cache", action="store_true")
    ap.add_argument("--skip-if-done", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    monday = date.fromisoformat(a.monday) if a.monday else today_rome()
    session = monday if is_session(monday) else next_session(monday)
    as_of = prev_session(session)                     # ultimo giorno della settimana chiusa (venerdì)
    if a.skip_if_done and (C.AGREED / f"weekly_{monday}.json").exists():
        print(json.dumps({"skipped": True, "reason": f"weekly {monday} già fatta"}))
        return 0
    work = C.STATE / f"weekly_{monday}"
    work.mkdir(parents=True, exist_ok=True)
    cache = work / "compute.pkl"
    if a.from_cache and cache.exists():
        doc = pickle.loads(cache.read_bytes())
    else:
        meta = D.build_universe()
        syms = set(meta) | D.extra_symbols()
        daily = D.download_daily(list(syms) + ["^GSPC"], (as_of - timedelta(days=1100)).isoformat(), as_of)
        spx = daily["^GSPC"]
        if spx.index[-1].date() != as_of:
            raise SystemExit(f"S&P 500 senza la barra del {as_of}")
        md, mw = {}, {}
        for s, df in daily.items():
            if s == "^GSPC" or df.index[-1].date() != as_of:
                continue
            try:
                m = E.compute_metrics(df, spx.Close)
                if not m or not (m["adv"] and m["adv"] >= C.ADV_MIN and m["atr_pct"] >= C.ATR_PCT_MIN):
                    continue
                if not m["above_sma200"] or (m["rs"] or 0) < C.STALK_RS_THEME_MIN:
                    continue
                w = to_weekly(df, as_of)
                mwk = E.compute_metrics(w, to_weekly(spx, as_of).Close)
                if mwk:
                    md[s], mw[s] = m, mwk
            except Exception as e:
                log.warning("%s: %s", s, e)
        info = D.fetch_info(md)
        doc = dict(meta=meta, md=md, mw=mw, info=info)
        cache.write_bytes(pickle.dumps(doc))

    prev = {}
    for p in sorted(C.AGREED.glob("weekly_*.json"), reverse=True):
        if p.stem != f"weekly_{monday}":
            prev = json.loads(p.read_text(encoding="utf-8"))
            break
    prev_listed = set(prev.get("focus", [])) | set(prev.get("stalk", []))
    rows = {}
    for s in doc["md"]:
        md, mw = dict(doc["md"][s]), dict(doc["mw"][s])
        if E.universe_check(md, doc["info"].get(s, {}), s):
            continue
        gates = weekly_gates(md, mw)
        m = {**md, **{k: mw[k] for k in ("pattern_a_ok", "pattern_b_ok", "pattern_a_why", "pattern_b_why")}}
        lst = E.classify(m, gates, s in prev_listed)
        if lst != "Out":
            rows[s] = (lst, md, mw, gates)
    window = sessions_from(session, C.EARNINGS_SESSIONS)
    lo, hi = window[0].isoformat(), window[-1].isoformat()
    earn = D.fetch_earnings(list(rows), since=as_of)
    excluded = {}
    for s in list(rows):
        dates = set(earn.get(s, {}).get("calendar", [])) | set(earn.get(s, {}).get("earnings_dates", []))
        inside = sorted(d for d in dates if lo <= d <= hi)
        if inside:
            excluded[s] = inside[0]
            del rows[s]

    def pub(s):
        lst, md, mw, gates = rows[s]
        fails = [g for g in gates if not g.ok]
        reason = "; ".join(g.short for g in fails if g.code != "pattern") or "; ".join(g.short for g in fails) or \
            f"{E.pattern_label(mw)} on the weekly, {mw['compression_days']} tight weeks"
        return dict(ticker=s, list=lst, rs=md["rs"], vcp_weekly=E._r(mw["vcp"]), sma25_dist=E._r((md["close"] / md["sma25"] - 1) * 100),
                    atr_ext=E._r(md["ext"]), ema9w_dist_atr=E._r(mw["ema9_dist_atr"]), reason_en=reason,
                    pattern_a=("tight" if mw["pattern_a_ok"] else "wide"), pattern_b=("tight" if mw["pattern_b_ok"] else "wide"),
                    open_gates=[g.code for g in fails])
    key = lambda s: (-(rows[s][1]["rs"] or 0), s)
    focus = sorted([s for s in rows if rows[s][0] == "Focus"], key=key)
    stalk = sorted([s for s in rows if rows[s][0] == "Stalk"], key=key)
    out = dict(week_of=monday.isoformat(), session_date=session.isoformat(), as_of_close=as_of.isoformat(),
               asof_rome=datetime.now(ROME).strftime("%Y-%m-%d %H:%M %Z"), focus=focus, stalk=stalk,
               tickers=[pub(s) for s in focus + stalk], earnings_check=dict(window=f"{lo}..{hi}", excluded=excluded),
               notes="Weekly: no Discord, no alerts. Same engine as the daily; weekly bars W-FRI.")
    write_atomic(work / f"weekly_{monday}.json", out)
    if not a.dry_run:
        write_atomic(C.WATCHLISTS / f"weekly_{monday}.json", out)
        write_atomic(C.AGREED / f"weekly_{monday}.json", out)
    dis = [f"{t['ticker']} (A {t['pattern_a']} / B {t['pattern_b']})" for t in out["tickers"]
           if t["list"] == "Stalk" and t["pattern_a"] != t["pattern_b"] and t["open_gates"] == ["pattern"]]
    summ = (f"**Weekly {monday}** (close {as_of.strftime('%d/%m')})\nFocus ({len(focus)}): {', '.join(focus) or 'nessuno'}\n"
            f"Stalk ({len(stalk)}): {', '.join(stalk) or 'nessuno'}\n"
            + (f"Pattern settimanale, letture discordanti: {'; '.join(dis)}\n" if dis else "")
            + f"Utili {lo}..{hi}: " + (", ".join(f"{t} {d}" for t, d in excluded.items()) or "nessun nome escluso"))
    write_atomic(work / "summary_it.md", summ, as_json=False)
    print(summ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
