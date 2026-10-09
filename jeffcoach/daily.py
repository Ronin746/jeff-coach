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
from . import indicators as I
from . import channel as CH
from . import peg as PG
from . import patterns as P
from .calendar_us import ROME, is_session, prev_session, sessions_from, today_rome, last_sessions
from .output import above_sma65, by_sector, card_descriptions, tv_txt, write_atomic

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
    try:
        industry = D.build_industry_map()
    except Exception as e:                  # senza mappa la lista si fa lo stesso, solo senza forza del gruppo
        log.warning("mappa industrie non disponibile: %s", e)
        industry = {}
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
    for s in cand:           # lettura D (canale rialzista): solo sui candidati, ~0,04 s a titolo
        add_channel(metrics[s], daily[s])
    for s in num_ok:         # reazione ritardata agli utili: anche RS 60-69 (Jeff prende ACN a RS 66)
        m = metrics[s]
        if (m.get("rs") or 0) >= C.PEG["rs_min"] and m.get("sma200") and m["close"] >= m["sma200"] - C.PEG["sma200_tol_atr"] * m["atr"]:
            try:
                m.update(PG.read_peg(daily[s], m["atr"]))
            except Exception as e:
                log.warning("PEG %s: %s", s, e)
    info: dict = {}          # mcap/settore freschi: si scaricano in build() solo per i nomi che entrano in lista
    s65 = D.sma30_65m(cand, last_sessions(as_of, 6))
    doc = dict(session=session, as_of=as_of, meta=meta, metrics=metrics, info=info, sma65=s65, industry=industry,
               n_downloaded=len(daily) - 1, stale=stale, num_ok=sorted(num_ok), cand=sorted(cand))
    cache.write_bytes(pickle.dumps(doc))
    return doc


def add_channel(m: dict, df) -> None:
    try:
        m.update(CH.read_channel(df, m["atr"]))
    except Exception as e:                      # un canale illeggibile non toglie il titolo dai calcoli
        log.warning("canale: %s", e)
        m["d_ok_data"] = False
    ok, why, _ = CH.reading_d(m)
    m["pattern_d_ok"], m["pattern_d_why"] = ok, why
    ln = m.pop("d_lines", None)
    if ln:                                       # linee del canale in date, per il grafico dell'alert [RONIN 09/10]
        i0, u0, l0, i1, u1, l1 = ln
        try:
            m["d_line_pts"] = dict(start=str(df.index[i0].date()), end=str(df.index[i1].date()),
                                   up0=round(u0, 4), lo0=round(l0, 4), up1=round(u1, 4), lo1=round(l1, 4),
                                   slope=round((u1 - u0) / max(i1 - i0, 1), 6))
        except Exception:
            pass


def channel_watch(rows: dict, s65: dict) -> list[dict]:
    """Nomi nella parte bassa di un canale rialzista (lettura D) [RONIN 08/10]. Per ognuno: SMA30 65m e EMA9.
    "Recupero SMA30 65m" = close sopra la SMA30 65m anche se ancora sotto la EMA9: si segnala lo stesso.
    Chi ha chiuso SOTTO la SMA30 65m resta in osservazione: Sydney avvisa durante la seduta se la recupera."""
    out = []
    for t, r in rows.items():
        m = r.m
        hard_out = r.out_reason and not r.out_reason.startswith("stale")     # utili / universo: fuori anche qui
        if not m.get("pattern_d_ok") or hard_out or (m.get("rs") or 0) < C.CHANNEL_RS_MIN:
            continue
        s30 = (s65.get(t) or {}).get("sma30_65m")
        above = None if s30 is None else m["close"] > s30
        out.append(dict(ticker=t, list=r.list, state=m["d_state"], rs=m["rs"], close=_r(m["close"]),
                        lower_line_next=_r(m["d_lower_next"]), upper_line_next=_r(m["d_upper_next"]),
                        pos=_r(m["d_pos"]), width_atr=_r(m["d_width_atr"], 1), sma30_65m=_r(s30),
                        above_sma30_65m=above, ema9=_r(m["ema9"]), under_ema9=m["close"] <= m["ema9"],
                        atr=_r(m["atr"]), industry=m.get("industry"), group_pctl=m.get("group_pctl"),
                        lines=m.get("d_line_pts")))
    return sorted(out, key=lambda x: (-(x["rs"] or 0), x["ticker"]))


def dtl_watch(names, metrics, rows, earn_out, out_universe, grp) -> list[dict]:
    """Trendline discendente [RONIN 09/10]. kind:
      break    = rotta in chiusura con volume >= 1,5x la media (va nella card del giorno dopo);
      near     = close sotto la linea entro 1,5 ATR (Sydney avvisa se la rompe in seduta con RVOL alto);
      pullback = rotta nelle ultime 15 sedute (Sydney avvisa sul crossback: recupero della SMA30 65m sopra la EMA9).
    Rotture in chiusura senza volume non vanno nella card ma restano seguite come pullback dal giorno dopo."""
    from . import dtl as DT
    out = []
    for s in names:
        if s in earn_out or s in out_universe:
            continue
        m = metrics[s]
        kind = DT.state(m)
        bv = m.get("dt_confirm_vol") if m.get("dt_confirm_ago") == 0 else m.get("dt_break_vol")
        if kind == "break" and (bv or 0) < C.DTL["break_vol_min"]:
            continue
        r = rows.get(s)
        out.append(dict(
            ticker=s, kind=kind, list=(r.list if r else "Out"), rs=m.get("rs"), close=_r(m["close"]),
            line_next=_r(m["dt_line_next"]), dist_atr=_r(m["dt_dist_atr"]), touches=m["dt_touches"],
            start=m["dt_start"], start_high=_r(m["dt_start_high"]), slope=round(m["dt_slope"], 6),
            break_date=m.get("dt_break_date"), break_vol=_r(m.get("dt_break_vol")), break_ago=m.get("dt_break_ago"),
            confirm_date=m.get("dt_confirm_date"), confirm_vol=_r(m.get("dt_confirm_vol")),
            ema9=_r(m["ema9"]), ema21=_r(m["ema21"]), atr=_r(m["atr"]), vcp=_r(m.get("vcp"), 1),
            on_emas=bool(min(m["low"] - m["ema9"], m["low"] - m["ema21"]) <= C.DTL["ema_touch_atr"] * m["atr"]),
            sma5=_r(m.get("sma5_dist_pct")), atr_ext=_r(m.get("ext")), above_sma200=m.get("above_sma200"),
            sector=(grp.get(s) or {}).get("sector"), industry=(grp.get(s) or {}).get("industry"),
            lines=dict(start=m["dt_start"], end=m["dt_start"], up0=m["dt_start_high"], up1=m["dt_start_high"],
                       slope=m["dt_slope"]),
        ))
    order = {"break": 0, "pullback": 1, "near": 2}
    return sorted(out, key=lambda x: (order.get(x["kind"], 9), -(x["rs"] or 0), x["ticker"]))


def peg_watch(names, metrics, rows, earn, earn_out, out_universe, grp) -> list[dict]:
    """Reazione ritardata agli utili [RONIN 08/10]: gap confermato dalla data degli utili, prezzo tornato nel range
    del PEG, base stretta, sopra la SMA200. Fuori chi ha gli utili nella finestra o non passa l'universo."""
    out = []
    for s in names:
        if s in earn_out or s in out_universe:
            continue
        m = metrics[s]
        e = earn.get(s, {})
        conf = PG.confirm_earnings(m, (e.get("past_dates") or []) + (e.get("calendar") or []))
        if not conf:
            continue
        m["peg_earnings"] = True
        r = rows.get(s)
        out.append(dict(ticker=s, list=r.list if r else "Out", rs=m.get("rs"), close=_r(m["close"]),
                        peg_date=m["peg_date"], gap_pct=_r(m["peg_gap_pct"], 1), pre_gap_close=_r(m["peg_day_low"]),
                        gap_day_high=_r(m["peg_day_high"]), pivot=_r(m["peg_pivot"]), pos=_r(m.get("peg_pos")),
                        higher_low=m.get("peg_higher_low"), range5_atr=_r(m["peg_range5_atr"], 1),
                        industry=(grp.get(s) or {}).get("industry"), group_pctl=(grp.get(s) or {}).get("group_pctl"),
                        text=PG.describe_peg(m)))
    return sorted(out, key=lambda x: (x["peg_date"], x["rs"] or 0), reverse=True)     # i più recenti prima


def group_strength(doc: dict) -> tuple[dict, dict]:
    """Forza di ogni industria (e settore): mediana dell'RS dei titoli dell'universo, in percentile tra i gruppi.
    Ritorna (per titolo: industria, settore, percentile, n, leader) e la classifica dei gruppi."""
    import numpy as np
    ind = doc.get("industry") or {}
    metrics, meta = doc["metrics"], doc["meta"]
    uni = [s for s in metrics if s in meta and metrics[s].get("rs") is not None and s in ind]
    by_ind, by_sec = {}, {}
    for s in uni:
        by_ind.setdefault(ind[s]["industry"], []).append(s)
        by_sec.setdefault(ind[s]["sector"], []).append(s)

    def pctl(groups: dict) -> dict:
        med = {g: float(np.median([metrics[s]["rs"] for s in v])) for g, v in groups.items() if len(v) >= C.GROUP_MIN_MEMBERS}
        order = sorted(med, key=lambda g: med[g])
        k = max(1, len(order) - 1)
        return {g: dict(pctl=round(i / k * 100), median_rs=round(med[g]), n=len(groups[g]),
                        strong=sum(1 for s in groups[g] if metrics[s]["rs"] >= 90)) for i, g in enumerate(order)}
    gi, gs = pctl(by_ind), pctl(by_sec)
    lead = {}
    for key, lab in (("ret21_pct", "1m"), ("ret63_pct", "3m"), ("ret126_pct", "6m")):
        vals = sorted((metrics[s][key] for s in uni if metrics[s].get(key) is not None), reverse=True)
        if vals:
            cut = vals[max(0, int(len(vals) * C.LEADER_TOP_PCT / 100) - 1)]
            for s in uni:
                if (metrics[s].get(key) or -1e9) >= cut:
                    lead.setdefault(s, []).append(lab)
    per = {}
    for s in metrics:
        if s not in ind:
            continue
        i_, se = ind[s]["industry"], ind[s]["sector"]
        g = gi.get(i_) or gs.get(se)
        per[s] = dict(industry=i_, sector=se, group_pctl=(g or {}).get("pctl"), group_n=len(by_ind.get(i_, [])),
                      group_level="industry" if i_ in gi else "sector", leader=lead.get(s, []))
    return per, dict(industries=gi, sectors=gs)


def rs_week_ago(doc: dict) -> dict:
    """RS di ogni titolo dell'universo alla chiusura della settimana precedente. Dai metrics se c'è (liste nuove),
    altrimenti si scarica una volta e resta nel compute.pkl (doc["rs_wk"]) [RONIN 09/10]."""
    metrics = doc["metrics"]
    if all("rs_w1" in m for m in metrics.values()):
        return {s: m["rs_w1"] for s, m in metrics.items()}
    if doc.get("rs_wk") is None:
        out = {}
        try:
            syms = [s for s, m in metrics.items() if m.get("rs") is not None]
            daily = D.download_daily(syms + ["^GSPC"], (doc["as_of"] - timedelta(days=420)).isoformat(), doc["as_of"])
            spx = daily.get("^GSPC")
            for s in syms:
                df = daily.get(s)
                if df is None or spx is None or len(df) < 262:
                    continue
                ref = spx.Close.reindex(df.index).ffill()
                k = E.prev_week_cut(df.index)
                if k and ref.notna().all():
                    out[s] = I.rs_rating(I.rs_raw(list(df.Close.values[:k]), list(ref.values[:k])))
        except Exception as e:
            log.warning("RS di una settimana fa non disponibile: %s", e)
        doc["rs_wk"] = out
    return doc["rs_wk"]


def sector_strong_w1(doc: dict) -> dict:
    """Per settore: quanti titoli dell'universo avevano RS >= 90 alla chiusura della settimana precedente."""
    ind, metrics, meta = doc.get("industry") or {}, doc["metrics"], doc["meta"]
    w1 = rs_week_ago(doc)
    out: dict = {}
    for s, m in metrics.items():
        if s in meta and m.get("rs") is not None and s in ind and w1.get(s) is not None:
            sec = ind[s]["sector"]
            out[sec] = out.get(sec, 0) + (1 if w1[s] >= 90 else 0)
    return out


def sector_etf_stats(doc: dict) -> dict:
    """Per la card: RS, VCP, SMA5 e Atr Ext dell'ETF di ogni settore, con le stesse formule dei titoli [RONIN 09/10].
    I dati si scaricano una volta e restano nel compute.pkl del giorno (doc["sector_etf"])."""
    if doc.get("sector_etf") is None:
        out = {}
        try:
            etfs = list(C.SECTOR_ETF.values())
            daily = D.download_daily(etfs + ["^GSPC"], (doc["as_of"] - timedelta(days=800)).isoformat(), doc["as_of"])
            spx = daily.get("^GSPC")
            for sec, etf in C.SECTOR_ETF.items():
                df = daily.get(etf)
                m = E.compute_metrics(df, spx.Close) if df is not None and spx is not None else None
                if m:
                    out[sec] = dict(etf=etf, rs=m.get("rs"), vcp=_r(m.get("vcp"), 1), sma5=_r(m.get("sma5_dist_pct")),
                                    atr_ext=_r(m.get("ext")))
        except Exception as e:
            log.warning("ETF di settore non disponibili: %s", e)
        doc["sector_etf"] = out
    return doc["sector_etf"]


def build(doc: dict, review: dict, prev: dict | None, earn: dict | None) -> dict:
    session, as_of, metrics, info, s65, meta = (doc[k] for k in ("session", "as_of", "metrics", "info", "sma65", "meta"))
    rows: dict[str, E.Row] = {}
    out_universe = {}
    prev_listed = set((prev or {}).get("focus", [])) | set((prev or {}).get("stalk", []))
    prev_carry = {t["ticker"]: int(t.get("carry_days") or 0) for t in (prev or {}).get("tickers", [])}
    if not doc.get("industry"):
        try:
            doc["industry"] = D.build_industry_map()
        except Exception as e:
            log.warning("mappa industrie non disponibile: %s", e)
    grp, groups = group_strength(doc)
    stale_stalk = {}
    for s in doc["cand"]:
        m = dict(metrics[s])
        m.update(grp.get(s, {}))
        gates = E.focus_gates(m, s65.get(s))
        lst = E.classify(m, gates, s in prev_listed)
        # scadenza: Stalk tenuto solo dalla regola "già in lista" (non passerebbe come nuovo ingresso)
        m["carry_days"] = 0
        if lst == "Stalk" and E.classify(m, gates, False) == "Out":
            m["carry_days"] = prev_carry.get(s, 0) + 1
            if m["carry_days"] > C.STALK_CARRY_MAX_SESSIONS:
                lst = "Out"
                stale_stalk[s] = m["carry_days"] - 1
        rows[s] = E.Row(s, lst, m, gates)
        if s in stale_stalk:
            rows[s].out_reason = f"stale Stalk: {stale_stalk[s]} sessions without tightening"

    # universo con info fresche (tipo, market cap, industria) sui soli nomi che entrerebbero in lista
    def _near(r):   # numeri tutti ok ma nessun pattern: si mostrano a Ronin, non entrano in lista
        return (r.list == "Out" and r.m["above_sma200"] and (r.m["rs"] or 0) >= C.RS_FOCUS_MIN
                and not [g for g in r.fails if g.code not in E.SOFT_GATES])
    def _chan(r):   # lettura D: nome nella parte bassa di un canale (lista a parte, controllata come le altre)
        return r.m.get("pattern_d_ok") and (r.m.get("rs") or 0) >= C.CHANNEL_RS_MIN
    peg_names = [s for s in doc["num_ok"] if metrics[s].get("peg_ok") and (metrics[s].get("rs") or 0) >= C.PEG["rs_min"]]
    pre = [s for s, r in rows.items() if r.list != "Out" or _near(r) or _chan(r)]
    pre += [s for s in peg_names if s not in pre]
    from . import dtl as DT                      # trendline discendente / wedge pop [RONIN 09/10]
    dtl_names = [s for s in doc["num_ok"] if DT.state(metrics[s]) and (metrics[s].get("rs") or 0) >= C.DTL["rs_min"]]
    pre += [s for s in dtl_names if s not in pre]
    need = [s for s in pre if s not in info or "err" in info[s]]
    if need:
        info.update(D.fetch_info(need))
    info_missing = []
    for s in pre:
        if "err" in info.get(s, {}):
            info_missing.append(s)
        inf = dict(info.get(s, {}))
        if not inf.get("industry") and (doc.get("industry") or {}).get(s):
            # Yahoo non ha risposto (es. "Invalid Crumb"): l'industria viene dalla mappa settimanale salvata,
            # così un biotech non passa per un errore di rete [09/10: CORT, EXEL, KOD]
            inf["industry"] = doc["industry"][s].get("industry")
        why = E.universe_check(rows[s].m if s in rows else metrics[s], inf, s)
        if why:
            out_universe[s] = why
            if s in rows:
                rows[s].list = "Out"
                rows[s].out_reason = why

    # utili: tutti i nomi che finirebbero in lista
    listed = [s for s, r in rows.items() if r.list != "Out" or (_chan(r) and s not in out_universe)]
    listed += [s for s in peg_names if s not in listed and s not in out_universe]
    listed += [s for s in dtl_names if s not in listed and s not in out_universe]
    window = sessions_from(session, C.EARNINGS_SESSIONS)
    lo, hi = window[0].isoformat(), window[-1].isoformat()
    earn = dict(earn or {})
    missing = [s for s in listed if s not in earn or (s in peg_names and "past_dates" not in earn[s])]
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
        if s in rows:
            rows[s].list = "Out"
            rows[s].out_reason = f"earnings {earn_out[s]}"
    pegw = peg_watch(peg_names, metrics, rows, earn, earn_out, out_universe, grp)
    chan = channel_watch(rows, s65)
    dtlw = dtl_watch(dtl_names, metrics, rows, earn_out, out_universe, grp)

    # revisione a occhio del bot [RONIN 09/10]: DECLASSA un Focus a Stalk, oppure PROMUOVE a Focus uno Stalk il cui
    # unico gate aperto è il pattern (le letture A/B non lo vedono ma il grafico sì). Mai sopra un gate numerico.
    review_applied = {}
    for s, rv in (review or {}).items():
        r = rows.get(s)
        if not r or r.list == "Out":
            continue
        if rv.get("demote") and r.list == "Focus":
            r.list = "Stalk"
            r.gates.append(E.Gate("review", False, "pattern review: " + rv["demote"]))
            review_applied[s] = "demoted: " + rv["demote"]
        elif rv.get("promote") and r.list == "Stalk":
            numeric = [g.code for g in r.fails if g.code not in E.SOFT_GATES]
            if not numeric and [g.code for g in r.fails] and all(g.code == "pattern" for g in r.fails):
                r.list = "Focus"
                r.gates = [g for g in r.gates if g.code != "pattern"]
                review_applied[s] = "promoted: " + rv["promote"]
            else:
                review_applied[s] = "promote refused (open gates: " + ", ".join(g.code for g in r.fails) + ")"
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
            pattern_c=("tight" if m.get("pattern_c_ok") else "wide"), pattern_c_shape=m.get("c_shape"),
            trendline_next=_r(m.get("c_upper_next")), industry=m.get("industry"), sector=m.get("sector"),
            group_pctl=m.get("group_pctl"),
            leader=m.get("leader") or [], carry_days=m.get("carry_days", 0),
            channel=m.get("d_state") if m.get("d_found") else None, channel_buy_zone=bool(m.get("pattern_d_ok")),
            channel_lower_next=_r(m.get("d_lower_next")),
            gap_to_fill=_r(m.get("gap_top")) if C.GAP_GATE_ON and m.get("gap_open") else None,
            triangle_top=_r(m.get("t_top")) if m.get("t_ok") else None,
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
        pattern_mode=C.PATTERN_MODE, stale_stalk=stale_stalk,
        pattern_c_vs_decision=pattern_c_compare(rows),
        top_groups=top_groups(groups, rows),
        channel_watch=chan,
        peg_watch=pegw,
        dtl_watch=dtlw,
        triangles=[dict(ticker=t, list=r.list, top=_r(r.m["t_top"]), support_next=_r(r.m["t_support_next"]),
                        touches_top=r.m["t_touch_top"], length=r.m["t_len"], rs=r.m.get("rs"))
                   for t, r in sorted(rows.items()) if r.m.get("t_ok") and not r.out_reason
                   and (r.m.get("rs") or 0) >= C.RS_FOCUS_MIN],
        gap_to_fill={t: _r(r.m["gap_top"]) for t, r in rows.items()
                     if r.list != "Out" and any(g.code == "gap" and not g.ok for g in r.gates)},
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
    sw1 = sector_strong_w1(doc)
    return dict(agreed=agreed, detail=detail, focus=focus, stalk=stalk, fpub=fpub, spub=spub, earn=earn,
                sectors={sec: {**(groups.get("sectors") or {}).get(sec, {}), **st, "strong_w1": sw1.get(sec)}
                         for sec, st in sector_etf_stats(doc).items()})


def pattern_c_compare(rows: dict) -> dict:
    """Dove la lettura C (trendline) non è d'accordo con la decisione di oggi: serve a Ronin per scegliere il modo."""
    out = {"c_tight_not_focus": {}, "focus_c_wide": {}}
    for t, r in rows.items():
        m = r.m
        if r.out_reason:
            continue
        numeric_ok = not [g for g in r.fails if g.code not in E.SOFT_GATES]
        if r.list == "Focus" and not m.get("pattern_c_ok"):
            out["focus_c_wide"][t] = "; ".join(m.get("pattern_c_why") or [])
        elif r.list != "Focus" and m.get("pattern_c_ok") and numeric_ok and m["above_sma200"] and (m["rs"] or 0) >= C.RS_FOCUS_MIN:
            out["c_tight_not_focus"][t] = P.describe(m)
    return out


def top_groups(groups: dict, rows: dict, n: int = 8) -> list[dict]:
    gi = groups.get("industries") or {}
    listed = {}
    for t, r in rows.items():
        if r.list in ("Focus", "Stalk") and r.m.get("industry"):
            listed.setdefault(r.m["industry"], []).append(t)
    best = sorted(gi.items(), key=lambda kv: -kv[1]["pctl"])[:n]
    return [dict(industry=k, pctl=v["pctl"], median_rs=v["median_rs"], n=v["n"], strong=v["strong"],
                 in_list=sorted(listed.get(k, []))) for k, v in best]


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
    if a.get("stale_stalk"):
        L.append("Stalk scaduti (troppe sedute senza stringere): " +
                 ", ".join(f"{t} ({d})" for t, d in sorted(a["stale_stalk"].items())))
    tg = a.get("top_groups") or []
    if tg:
        L.append("Gruppi più forti: " + "; ".join(
            f"{g['industry']} ({g['pctl']}" + (f": {', '.join(g['in_list'])}" if g["in_list"] else "") + ")" for g in tg[:6]))
    fg = [f"{r['ticker']} {r['group_pctl']}" for r in res["fpub"] if r.get("group_pctl") is not None]
    if fg:
        L.append("Forza del gruppo dei Focus (percentile): " + ", ".join(fg))
    cc = a.get("pattern_c_vs_decision") or {}
    if cc.get("c_tight_not_focus") or cc.get("focus_c_wide"):
        parts = []
        if cc.get("c_tight_not_focus"):
            parts.append("stretti per le trendline ma non Focus: " + "; ".join(f"{t} ({v})" for t, v in sorted(cc["c_tight_not_focus"].items())))
        if cc.get("focus_c_wide"):
            parts.append("Focus che le trendline non vedono stretti: " + "; ".join(f"{t} ({v})" for t, v in sorted(cc["focus_c_wide"].items())))
        L.append(f"Lettura C (modo {a.get('pattern_mode')}): " + " · ".join(parts))
    cw = a.get("channel_watch") or []
    if cw:
        rec = [c for c in cw if c["above_sma30_65m"] and c["under_ema9"]]
        ok = [c for c in cw if c["above_sma30_65m"] and not c["under_ema9"]]
        wait = [c for c in cw if c["above_sma30_65m"] is False]
        def f(c):
            if c["state"] == "backtest of the broken line":
                return f"{c['ticker']} (backtest della linea rotta {c['upper_line_next']})"
            where = "bordo basso" if c["state"] == "lower part of the channel" else "sulla EMA21"
            return f"{c['ticker']} ({where}, linea bassa {c['lower_line_next']})"
        L.append(f"Canale rialzista, parte bassa ({len(cw)}):")
        if rec:
            L.append("  recuperata la SMA30 65m, ancora sotto la EMA9: " + "; ".join(f(c) for c in rec))
        if ok:
            L.append("  sopra SMA30 65m ed EMA9: " + "; ".join(f(c) for c in ok))
        if wait:
            L.append("  sotto la SMA30 65m (alert se la recupera): " + "; ".join(f(c) for c in wait))
    dw = a.get("dtl_watch") or []
    if dw:
        L.append(f"Trendline discendente (wedge pop) ({len(dw)}):")
        b = [d for d in dw if d["kind"] == "break"]
        pb = [d for d in dw if d["kind"] == "pullback"]
        nr = [d for d in dw if d["kind"] == "near"]
        if b:
            L.append("  rotta in chiusura con volume: " + "; ".join(
                f"{d['ticker']} (vol {d['break_vol']}x, linea dal picco {d['start'][5:]} a {d['start_high']})" for d in b))
        if pb:
            L.append("  rotta da poco, si segue il pullback (alert sul crossback: tocco di EMA9/21 e recupero della SMA30 65m sopra la EMA9): " + "; ".join(
                f"{d['ticker']} (rotta il {d['break_date'][5:]}, vol {d['break_vol']}x)" for d in pb))
        if nr:
            L.append("  sotto la linea e vicina, entro 1 ATR (alert se la rompe con RVOL >= 1,5): " + "; ".join(
                f"{d['ticker']} (linea {d['line_next']}, {abs(d['dist_atr'])} ATR)" for d in nr))
    pw = a.get("peg_watch") or []
    if pw:
        L.append(f"Reazione ritardata agli utili ({len(pw)}): " + "; ".join(
            f"{p['ticker']} (utili {p['peg_date'][5:]} +{p['gap_pct']:.0f}%, pivot {p['pivot']}"
            + (", minimo crescente" if p["higher_low"] else "") + ")" for p in pw))
    tri = a.get("triangles") or []
    if tri:
        L.append(f"Triangoli ascendenti ({len(tri)}): " + "; ".join(
            f"{t['ticker']} (tetto {t['top']}, {t['touches_top']} tocchi, {t['list']})" for t in tri))
    gp = a.get("gap_to_fill") or {}
    if gp:
        L.append("Gap al ribasso da riempire (restano Stalk finché non lo riempiono): " +
                 "; ".join(f"{t} {v}" for t, v in sorted(gp.items())))
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
    up = {r["ticker"] for r in res["spub"] if above_sma65(r)}
    # nel txt i nomi di ogni sezione seguono lo stesso ordine per settore della card [RONIN 09/10]
    fo = [r["ticker"] for r in by_sector(res["fpub"])]
    so = [r["ticker"] for r in by_sector([r for r in res["spub"] if r["ticker"] in up])]
    sb = [r["ticker"] for r in by_sector([r for r in res["spub"] if r["ticker"] not in up])]
    txt = tv_txt([(t, exch_of(t, doc)) for t in fo], [(t, exch_of(t, doc)) for t in so],
                 [(t, exch_of(t, doc)) for t in sb])
    descs = card_descriptions(session.isoformat(), res["fpub"], res["spub"], res.get("sectors"),
                              dtl_breaks=[d for d in (res["agreed"].get("dtl_watch") or []) if d["kind"] == "break"])
    card = {"embeds": [{"description": d, "color": C.CARD_COLOR} for d in descs], "allowed_mentions": {"parse": []}}
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
    print(f"\ncard: {sum(len(d) for d in descs)} caratteri in {len(descs)} embed · dettaglio: {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
