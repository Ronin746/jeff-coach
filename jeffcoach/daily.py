"""Lista Focus/Stalk del mattino (una sola, deterministica).

Uso:
  python -m jeffcoach.daily                 # seduta di oggi (ora di Roma), close RTH precedente
  python -m jeffcoach.daily --session 2026-10-08 --dry-run
  python -m jeffcoach.daily --from-cache    # riusa i dati già scaricati e riapplica review.json

Scrive (se non --dry-run):
  watchlists/focus_<SEDUTA>.json + focus_today.json        dettaglio completo, ogni gate di ogni nome
  /workspace/coach-agreed/today.json + <SEDUTA>.json        lista pubblica letta dagli alert
  /workspace/coach-agreed/watchlist_<SEDUTA>.txt + _today   import TradingView
  /workspace/tv-scanner/pivot30_list.txt                    Focus+Stalk con RS>=80 per Remy
  state/daily_<SEDUTA>/card.json, summary_it.md, rows.pkl
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from datetime import date, datetime, timedelta

from . import config as C
from . import data as D
from . import engine as E
from .calendar_us import ROME, is_session, prev_session, sessions_from, today_rome, last_sessions
from .output import card_description, tv_txt, write_atomic

log = logging.getLogger("jeffcoach.daily")


def _r(x, n=2):
    return E._r(x, n)


def compute(session: date, workdir, use_cache: bool) -> dict:
    """Scarica e calcola tutto. Ritorna un dizionario serializzabile (rows + contesto)."""
    as_of = prev_session(session)
    cache = workdir / "compute.pkl"
    if use_cache and cache.exists():
        return pickle.loads(cache.read_bytes())

    meta = D.build_universe()
    syms = set(meta) | D.extra_symbols()
    start = (as_of - timedelta(days=800)).isoformat()
    daily = D.download_daily(list(syms) + ["^GSPC"], start, as_of)
    spx = daily.get("^GSPC")
    if spx is None or spx.index[-1].date() != as_of:
        raise SystemExit(f"S&P 500 senza la barra del {as_of}: dati non pronti, non invento la lista")

    metrics, stale = {}, []
    for s, df in daily.items():
        if s == "^GSPC":
            continue
        if df.index[-1].date() != as_of:
            stale.append(s)
            continue
        try:
            m = E.compute_metrics(df, spx.Close)
        except Exception as e:  # dati sporchi su un titolo: non blocca la lista
            log.warning("metriche %s: %s", s, e)
            continue
        if m:
            metrics[s] = m

    # pre-universo numerico (mcap e settore si verificano dopo con info fresche)
    num_ok = {s for s, m in metrics.items()
              if m["adv"] and m["adv"] >= C.ADV_MIN and m["atr_pct"] >= C.ATR_PCT_MIN
              and (meta.get(s, {}).get("mcap") or C.MCAP_MIN + 1) > C.MCAP_MIN}
    cand = {s for s in num_ok if metrics[s]["above_sma200"] and (metrics[s]["rs"] or 0) >= C.STALK_RS_THEME_MIN}
    info: dict = {}          # mcap/settore freschi: si scaricano in build() solo per i nomi che entrano in lista
    s65 = D.sma30_65m(cand, last_sessions(as_of, 6))
    doc = dict(session=session, as_of=as_of, meta=meta, metrics=metrics, info=info, sma65=s65,
               n_downloaded=len(daily) - 1, stale=stale, num_ok=sorted(num_ok), cand=sorted(cand))
    cache.write_bytes(pickle.dumps(doc))
    return doc


def build(doc: dict, review: dict, prev: dict | None, earn: dict | None) -> dict:
    session, as_of, metrics, info, s65, meta = (doc[k] for k in ("session", "as_of", "metrics", "info", "sma65", "meta"))
    rows: dict[str, E.Row] = {}
    out_universe = {}
    prev_listed = set((prev or {}).get("focus", [])) | set((prev or {}).get("stalk", []))
    for s in doc["cand"]:
        m = dict(metrics[s])
        gates = E.focus_gates(m, s65.get(s))
        rows[s] = E.Row(s, E.classify(m, gates, s in prev_listed), m, gates)

    # universo con info fresche (tipo, market cap, industria) sui soli nomi che entrerebbero in lista
    def _near(r):   # numeri tutti ok ma nessun pattern: si mostrano a Ronin, non entrano in lista
        return (r.list == "Out" and r.m["above_sma200"] and (r.m["rs"] or 0) >= C.RS_FOCUS_MIN
                and not [g for g in r.fails if g.code != "pattern"])
    pre = [s for s, r in rows.items() if r.list != "Out" or _near(r)]
    need = [s for s in pre if s not in info or "err" in info[s]]
    if need:
        info.update(D.fetch_info(need))
    info_missing = []
    for s in pre:
        if "err" in info.get(s, {}):
            info_missing.append(s)
        why = E.universe_check(rows[s].m, info.get(s, {}), s)
        if why:
            out_universe[s] = why
            rows[s].list = "Out"
            rows[s].out_reason = why

    # utili: tutti i nomi che finirebbero in lista
    listed = [s for s, r in rows.items() if r.list != "Out"]
    window = sessions_from(session, C.EARNINGS_SESSIONS)
    lo, hi = window[0].isoformat(), window[-1].isoformat()
    earn = dict(earn or {})
    missing = [s for s in listed if s not in earn]
    if missing:
        earn.update(D.fetch_earnings(missing, since=as_of))
    earn_out, earn_next, earn_missing, earn_on_ref = {}, {}, [], []
    for s in listed:
        e = earn.get(s, {})
        dates = set(e.get("calendar", [])) | set(e.get("earnings_dates", []))
        if meta.get(s, {}).get("earnings"):
            dates.add(meta[s]["earnings"])
        fut = sorted(d for d in dates if d >= lo)
        earn_next[s] = fut[0] if fut else None
        inside = [d for d in dates if lo <= d <= hi]
        if inside:
            earn_out[s] = min(inside)                 # una fonte nella finestra basta per toglierlo [METODOLOGIA §1]
        if not fut:
            earn_missing.append(s)
        if as_of.isoformat() in dates:
            earn_on_ref.append(s)
    for s in earn_out:
        rows[s].list = "Out"
        rows[s].out_reason = f"earnings {earn_out[s]}"

    # revisione a occhio del bot: può solo DECLASSARE (Focus -> Stalk) o cambiare il testo, mai promuovere
    review_applied = {}
    for s, rv in (review or {}).items():
        r = rows.get(s)
        if not r or r.list == "Out":
            continue
        if rv.get("demote") and r.list == "Focus":
            r.list = "Stalk"
            r.gates.append(E.Gate("review", False, "pattern review: " + rv["demote"]))
            review_applied[s] = "demoted: " + rv["demote"]
        if rv.get("pattern"):
            r.m["pattern"] = rv["pattern"]
        if rv.get("reason_en"):
            r.m["reason_override"] = rv["reason_en"]

    def pub(r: E.Row) -> dict:
        m = r.m
        return dict(
            ticker=r.ticker, list=r.list, rs=m["rs"], vcp=_r(m["vcp"]), sma5=_r(m["sma5_dist_pct"]),
            atr_ext=_r(m["ext"]), reason_en=m.get("reason_override") or E.reason_en(r, s65.get(r.ticker)),
            pattern_a=("tight" if m["pattern_a_ok"] else "wide"), pattern_b=("tight" if m["pattern_b_ok"] else "wide"),
            open_gates=[g.code for g in r.fails], extreme_rvol_ok=False, prior_day_high=_r(m["high"]),
        )

    focus = sorted([r for r in rows.values() if r.list == "Focus"], key=lambda r: (-(r.m["rs"] or 0), r.ticker))
    stalk = sorted([r for r in rows.values() if r.list == "Stalk"], key=lambda r: (-(r.m["rs"] or 0), r.ticker))
    fpub, spub = [pub(r) for r in focus], [pub(r) for r in stalk]

    prev_f = set((prev or {}).get("focus", []))
    prev_all = prev_f | set((prev or {}).get("stalk", []))
    fset, sset = {r.ticker for r in focus}, {r.ticker for r in stalk}
    changes = dict(focus_before=sorted(prev_f), focus_after=[r.ticker for r in focus],
                   left_focus=sorted(prev_f - fset), joined_focus=sorted(fset - prev_f),
                   left_list=sorted(prev_all - fset - sset), joined_list=sorted((fset | sset) - prev_all))
    left_why = {}
    for t in changes["left_focus"] + changes["left_list"]:
        if t in rows:
            r = rows[t]
            left_why[t] = r.out_reason or E.reason_en(E.Row(r.ticker, "Stalk", r.m, r.gates)) or r.list
        elif t in out_universe:
            left_why[t] = out_universe[t]
        elif t in metrics and not metrics[t]["above_sma200"]:
            left_why[t] = "under the SMA200"
        elif t in metrics and (metrics[t]["rs"] or 0) < C.STALK_RS_THEME_MIN:
            left_why[t] = f"RS {metrics[t]['rs']}"
        else:
            left_why[t] = "outside the universe gates (ATR%/adv$/mcap) or no data"
    changes["why_left"] = left_why

    disagree = {r.ticker: dict(a=("tight" if r.m["pattern_a_ok"] else "; ".join(r.m["pattern_a_why"])),
                               b=("tight" if r.m["pattern_b_ok"] else "; ".join(r.m["pattern_b_why"])))
                for r in stalk if r.m["pattern_a_ok"] != r.m["pattern_b_ok"]
                and [g.code for g in r.fails] == ["pattern"]}

    now = datetime.now(ROME).strftime("%Y-%m-%d %H:%M %Z")
    agreed = dict(
        session_date=session.isoformat(), as_of_close=as_of.isoformat(), ranking_bar=as_of.isoformat(),
        ranking_bar_status="completed_rth_daily", timezone="Europe/Rome", asof_rome=now,
        focus=[r.ticker for r in focus], stalk=[r.ticker for r in stalk], tickers=fpub + spub,
        notes=("Single deterministic engine. Focus = every closed gate passes and BOTH pattern readings call it tight; "
               "Stalk = universe + earnings + RS>=80, above the SMA200, new names with at most "
               f"{C.STALK_NEW_MAX_NUMERIC_OPEN} numeric gate open and a tight pattern on at least one reading, names already listed "
               f"while at most {C.STALK_CARRY_MAX_NUMERIC_OPEN} numeric gates are open (or RS 70-79 with everything else closed). "
               "Alerts: entries on Focus only."),
        earnings_check=dict(window=f"{lo}..{hi}", excluded=earn_out, missing_dates=sorted(earn_missing),
                            reported_on_reference_day=sorted(earn_on_ref)),
        info_not_verified=sorted(info_missing),
        pattern_disagreements=disagree, review=review_applied, changes_vs_previous=changes,
    )
    detail = dict(agreed, funnel=dict(downloaded=doc["n_downloaded"], stale_last_bar=len(doc["stale"]),
                                      universe_numeric=len(doc["num_ok"]), candidates=len(doc["cand"]),
                                      out_universe=len(out_universe), focus=len(focus), stalk=len(stalk),
                                      out_earnings=len(earn_out)),
                  out_universe=out_universe,
                  near_misses={r.ticker: "; ".join(g.text for g in r.fails) for r in rows.values()
                               if not r.out_reason and _near(r)},
                  rows={r.ticker: dict(list=r.list, out_reason=r.out_reason,
                                       gates={g.code: dict(ok=g.ok, why=(None if g.ok else g.text)) for g in r.gates},
                                       metrics={k: (_r(v, 4) if isinstance(v, float) else v) for k, v in r.m.items()},
                                       sma30_65m=s65.get(r.ticker), next_earnings=earn_next.get(r.ticker))
                        for r in rows.values() if r.list != "Out" or r.out_reason})
    return dict(agreed=agreed, detail=detail, focus=focus, stalk=stalk, fpub=fpub, spub=spub, earn=earn)


def exch_of(s: str, doc: dict) -> str | None:
    return (doc["meta"].get(s) or {}).get("exchange") or (doc["info"].get(s) or {}).get("exchange")


def summary_it(res: dict, doc: dict) -> str:
    a = res["agreed"]
    ch = a["changes_vs_previous"]
    d = date.fromisoformat(a["as_of_close"]).strftime("%d/%m")
    L = [f"**Watchlist {a['session_date']}** (close {d})",
         f"Focus ({len(a['focus'])}): {', '.join(a['focus']) or 'nessuno'}",
         f"Stalk ({len(a['stalk'])}): {', '.join(a['stalk']) or 'nessuno'}", ""]
    if ch["joined_focus"] or ch["left_focus"]:
        L.append("Entrano in Focus: " + (", ".join(ch["joined_focus"]) or "nessuno") +
                 " · Escono: " + (", ".join(f"{t} ({ch['why_left'].get(t, 'Stalk')})" for t in ch["left_focus"]) or "nessuno"))
    if a["pattern_disagreements"]:
        L.append("Pattern: le due letture non concordano (restano in Stalk, da guardare): " +
                 "; ".join(f"{t} (A {v['a']} / B {v['b']})" for t, v in a["pattern_disagreements"].items()))
    nm = res["detail"].get("near_misses") or {}
    if nm:
        L.append(f"Numeri ok ma senza pattern di continuation (fuori lista): {', '.join(sorted(nm))}")
    e = a["earnings_check"]
    L.append(f"Utili {e['window']}: " + (", ".join(f"{t} {d}" for t, d in sorted(e["excluded"].items())) or "nessun nome escluso") +
             (f" · senza data: {', '.join(e['missing_dates'])}" if e["missing_dates"] else ""))
    piv = [r["ticker"] for r in res["fpub"] + res["spub"] if (r["rs"] or 0) >= C.RS_FOCUS_MIN]
    low = [f"{r['ticker']} RS {r['rs']}" for r in res["fpub"] + res["spub"] if (r["rs"] or 0) < C.RS_FOCUS_MIN]
    L.append(f"Remy: {len(piv)} nomi" + (f" (fuori per RS<80: {', '.join(low)})" if low else ""))
    if a.get("info_not_verified"):
        L.append("Settore/market cap non verificati (Yahoo non ha risposto): " + ", ".join(a["info_not_verified"]))
    if a["review"]:
        L.append("Revisione: " + "; ".join(f"{t} {v}" for t, v in a["review"].items()))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="YYYY-MM-DD (default: oggi, ora di Roma)")
    ap.add_argument("--dry-run", action="store_true", help="scrive solo in state/, non tocca coach-agreed né Remy")
    ap.add_argument("--from-cache", action="store_true", help="riusa compute.pkl ed earnings.json del giorno")
    ap.add_argument("--no-remy", action="store_true")
    ap.add_argument("--skip-if-done", action="store_true", help="esce se la lista della seduta esiste già (cron doppi per l'ora legale)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    session = date.fromisoformat(args.session) if args.session else today_rome()
    if not is_session(session):
        print(json.dumps({"skipped": True, "reason": f"{session} non è una seduta NYSE"}))
        return 0
    if args.skip_if_done and (C.AGREED / f"{session}.json").exists():
        print(json.dumps({"skipped": True, "reason": f"lista {session} già fatta"}))
        return 0
    work = C.STATE / f"daily_{session}"
    work.mkdir(parents=True, exist_ok=True)
    doc = compute(session, work, args.from_cache)

    review_p = work / "review.json"
    review = json.loads(review_p.read_text(encoding="utf-8")) if review_p.exists() else {}
    earn_p = work / "earnings.json"
    earn = json.loads(earn_p.read_text(encoding="utf-8")) if (args.from_cache and earn_p.exists()) else None
    prev = None
    for p in (C.AGREED / f"{prev_session(session)}.json", C.AGREED / "today.json"):
        if p.exists():
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("session_date") != session.isoformat():
                prev = j
                break
    res = build(doc, review, prev, earn)
    write_atomic(earn_p, res["earn"])
    work.joinpath("compute.pkl").write_bytes(pickle.dumps(doc))      # salva anche le info scaricate

    a = res["agreed"]
    txt = tv_txt([(t, exch_of(t, doc)) for t in a["focus"]], [(t, exch_of(t, doc)) for t in a["stalk"]])
    desc = card_description(session.isoformat(), res["fpub"], res["spub"])
    card = {"embeds": [{"description": desc, "color": C.CARD_COLOR}], "allowed_mentions": {"parse": []}}
    summ = summary_it(res, doc)
    write_atomic(work / "card.json", card)
    write_atomic(work / "summary_it.md", summ, as_json=False)
    write_atomic(work / f"watchlist_{session}.txt", txt, as_json=False)
    for fn in (f"focus_{session}.json", "focus_today.json"):
        write_atomic((work if args.dry_run else C.WATCHLISTS) / fn, res["detail"])

    if not args.dry_run:
        for fn in ("today.json", f"{session}.json"):
            write_atomic(C.AGREED / fn, a)
        for fn in (f"watchlist_{session}.txt", "watchlist_today.txt"):
            write_atomic(C.AGREED / fn, txt, as_json=False)
        if not args.no_remy:
            piv = [r["ticker"] for r in res["fpub"] + res["spub"] if (r["rs"] or 0) >= C.RS_FOCUS_MIN]
            write_atomic(C.REMY_PIVOT_FILE, f"date: {session}\n" + "\n".join(piv) + "\n", as_json=False)
    print(summ)
    print(f"\ncard: {len(desc)} caratteri · dettaglio: {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
