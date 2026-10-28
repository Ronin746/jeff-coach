"""Lista del mattino (deterministica): liste, scan, temi, regime, Focus long/short con i livelli.

Uso:
  python -m jeffcoach.daily                       # seduta di oggi (ora di Roma), close della seduta precedente
  python -m jeffcoach.daily --session 2026-10-13 --dry-run
  python -m jeffcoach.daily --from-cache          # riusa i dati scaricati e riapplica review.json (card)
  python -m jeffcoach.daily --skip-if-done        # esce se la lista di oggi esiste già (doppi cron)

Scrive (non con --dry-run):
  data/lists/today.json + <SEDUTA>.json         lista pubblica (la leggono alert e revisione)
  data/lists/watchlist_<SEDUTA>.txt              import TradingView (###FOCUS LONG/SHORT, ###TRACKING LONG/SHORT)
  data/lists/work_<SEDUTA>/                      detail.json, card.json, summary_it.md, review.json, compute.pkl
  data/history/lists_|potent_|themes_<CLOSE>.json  storico per breadth, scan e temi
  data/reports/temi_<SEDUTA>.md                  classifica dei temi
"""
from __future__ import annotations

import argparse
import json
import logging
import pickle
import re
import sys
from datetime import date, timedelta

import pandas as pd

from . import config as C
from . import data as D
from . import edges as EDG
from . import engine as E
from . import orizzontali as HZM
from . import jeff as JF          # [JEFF]
from . import peg as PG          # [JEFF]
from . import journal as J
from . import themes as T
from . import themes_map as TM
from . import breadth as B
from . import basket_score as BS
from . import breadth_chart as BC
from .calendar_us import is_session, prev_session, sessions_from, today_rome
from .output import card_embeds, themes_embeds, tv_txt, write_atomic

log = logging.getLogger("jeffcoach.daily")
NON_STOCK = set(C.INDICES) | set(C.SECTOR_ETFS)


# ------------------------------------------------------------------ download e metriche
def compute(session: date, work, use_cache: bool) -> dict:
    cache = work / "compute.pkl"
    if use_cache and cache.exists():
        return pickle.loads(cache.read_bytes())
    as_of = prev_session(session)
    uni = D.build_universe()
    try:
        ind = D.build_industry_map()
    except Exception as e:                      # le industrie servono ai temi, non bloccano la lista
        log.warning("mappa industrie: %s", e)
        ind = {}
    syms = [s for s, v in uni.items() if (v.get("quote_type") or "EQUITY") == "EQUITY"
            and (ind.get(s, {}).get("industry") not in C.EXCLUDED_INDUSTRIES)]
    # [JEFF] syms resta l'universo di Martin (regime, breadth, pool, Market Monitor nostro); jsyms è quello di Jeff per le
    # idee di trade; jeff_only = titoli che Martin non scarica (prefiltro 30-50M$, utility e staples)
    jsyms, jeff_only = [], []
    if C.JEFF:
        syms = [s for s in syms if (uni[s].get("dv3m") or C.SCREEN_DV_PREFILTER) >= C.SCREEN_DV_PREFILTER]
        jsyms = [s for s, v in uni.items() if (v.get("quote_type") or "EQUITY") == "EQUITY" and s not in C.JEFF_EXCLUDED_TICKERS
                 and ind.get(s, {}).get("industry") not in C.JEFF_EXCLUDED_INDUSTRIES]
        jeff_only = sorted(set(jsyms) - set(syms))
        NON_STOCK.add(C.JEFF_SPX)
    try:
        tmap = TM.refresh()
    except Exception as e:
        log.warning("mappa temi: %s", e)
        tmap = {}
    theme_etf_syms = sorted({e for v in (tmap.get("theme_etfs") or {}).values() for e in v})
    NON_STOCK.update(theme_etf_syms)             # gli ETF dei temi servono solo come contesto (blocco settore forte)
    lst = C.THEME_SOURCE == "lst"
    basket_syms = sorted({t for v in (tmap.get("baskets") or {}).values() for t in v}) if lst else []
    sset = set(syms) | set(jeff_only)                # [JEFF] (Martin: set(syms))
    basket_extra = [t for t in basket_syms if t not in sset and t not in NON_STOCK]   # fuori universo: solo per i basket
    NON_STOCK.update(basket_extra)
    start = (as_of - timedelta(days=C.DAILY_HISTORY_DAYS)).isoformat()
    daily = D.download_daily(syms + jeff_only + sorted(NON_STOCK), start, as_of)      # [JEFF] + jeff_only
    q = daily.get("QQQ")
    if q is None or q.index[-1].date() != as_of:
        from collections import Counter
        last = Counter(str(df.index[-1].date()) for df in daily.values())
        raise SystemExit(f"QQQ senza la barra del {as_of} (QQQ: {None if q is None else q.index[-1].date()}; "
                         f"ultime date dell'universo: {last.most_common(3)}): dati non pronti, non invento la lista")
    spx = None
    if C.JEFF:                                   # [JEFF] riferimento dell'RS Rating di Jeff
        spx = daily.get(C.JEFF_SPX)
        if spx is None or spx.index[-1].date() != as_of:
            raise SystemExit(f"{C.JEFF_SPX} senza la barra del {as_of}: dati non pronti, non invento la lista")
    jset = set(jsyms)
    metrics, stale = {}, []
    for s, df in daily.items():
        if df.index[-1].date() != as_of:
            stale.append(s)
            continue
        try:
            jm = JF.metrics(df, spx.Close) if s in jset else {}          # [JEFF] misure di Jeff (chiavi j_*)
            m = E.compute_metrics(df, q, extra_edges=JF.liquid(jm)) if jm else E.compute_metrics(df, q)
        except Exception as e:
            log.warning("metriche %s: %s", s, e)
            continue
        if m:
            m.update(jm)
            metrics[s] = m
    jo = set(jeff_only)                          # [JEFF] fuori dalle misure di mercato di Martin
    liquid = sorted((s for s, m in metrics.items() if s not in NON_STOCK and s not in jo and m["dv5"] >= C.DV_MIN), key=lambda s: -metrics[s]["dv5"])
    tliq = sorted((s for s, m in metrics.items() if s not in NON_STOCK and s not in jo and m["dv5"] >= C.THEME_DV_MIN), key=lambda s: -metrics[s]["dv5"])
    proxies = [e for v in (tmap.get("proxy_etfs") or {}).values() for e in v if e in metrics]   # ETF senza azioni
    tetfs = [e for e in theme_etf_syms if e in metrics and (metrics[e].get("dv20") or 0) >= C.THEME_ETF_DV_MIN]
    extra = [e for e in dict.fromkeys(proxies + tetfs)]
    closes = pd.DataFrame({s: daily[s].Close for s in tliq[:C.THEME_CLOSES_MAX] + extra}).iloc[-max(C.CORR_WINDOWS) - 2:]
    doc = dict(session=session, as_of=as_of, uni=uni, ind=ind, metrics=metrics, stale=stale, closes=closes,
               qqq_close=q.Close, earnings={}, basket_extra=basket_extra, jeff_only=jeff_only)     # [JEFF] jeff_only
    if lst:                    # basket LST: 7 fattori su TUTTI i titoli dei basket, oggi e 5 sedute fa [RONIN 21/10]
        try:
            bsyms = [t for t in basket_syms if t in metrics]
            bench = daily.get(C.BASKET_BENCHMARK)
            doc["basket_scores"] = BS.universe_scores(daily, bsyms, bench)
            cut = {t: daily[t].iloc[:-5] for t in bsyms + [C.BASKET_BENCHMARK] if t in daily}
            doc["basket_scores_prev"] = BS.universe_scores(cut, bsyms, cut.get(C.BASKET_BENCHMARK))
            log.info("basket LST: %d titoli con punteggio su %d", len(doc["basket_scores"]), len(basket_syms))
        except Exception as e:
            log.warning("punteggi a 7 fattori dei basket: %s", e)
    tsyms = [s for s in tliq if metrics[s]["close"] >= C.PRICE_MIN] + proxies
    if not lst:
        try:                   # classifica dei temi come i basket di Ratatouille: 7 fattori per titolo [RONIN 16/10]
            doc["basket_scores"] = BS.universe_scores(daily, tsyms, daily.get(C.BASKET_BENCHMARK))
        except Exception as e:
            log.warning("punteggi a 7 fattori: %s", e)
        try:                   # titoli dei temi con lo stesso metodo degli ETF (performance vs SPY + livelli) [RONIN 17/10]
            doc["stock_perf_scores"] = BS.etf_perf_scores(daily, tsyms, daily.get(C.BASKET_BENCHMARK))
        except Exception as e:
            log.warning("punteggi a 7 fattori: %s", e)
        try:                   # gli stessi 7 fattori sugli ETF dei temi: il tema si misura sul suo ETF [RONIN 16/10]
            fn = BS.etf_perf_scores if C.THEME_RANKING == "etf_perf" else BS.universe_scores   # [RONIN 17/10]
            doc["etf_scores"] = fn(daily, tetfs, daily.get(C.BASKET_BENCHMARK))
            # stessi punteggi 5 sedute fa: variazione d5 e stadio del tema come Ratatouille [RONIN 16/10]
            cut = {e: daily[e].iloc[:-5] for e in tetfs + [C.BASKET_BENCHMARK] if e in daily}
            doc["etf_scores_prev"] = fn(cut, tetfs, cut.get(C.BASKET_BENCHMARK))
        except Exception as e:
            log.warning("punteggi a 7 fattori ETF: %s", e)
    if C.JEFF:                 # [JEFF] universo, candidati, PEG, utili e EMA50 a 1 ora di Jeff
        doc["jeff"] = jeff_compute(daily, metrics, uni, ind, jsyms, session, as_of)
        doc["earnings"] = doc["jeff"]["earnings"]["next"]
    else:
        cand = [s for s in liquid if E.long_candidate(s, metrics[s])[0] or E.short_candidate(s, metrics[s])[0]]
        try:
            doc["earnings"] = D.next_earnings(cand, session)
        except Exception as e:
            log.warning("utili: %s", e)
    doc["mm"] = D.fetch_market_monitor()[:60]          # 60: la lettura di Pradeep guarda 30 sedute indietro
    try:                                            # backup: Market Monitor calcolato sui nostri titoli [RONIN 15/10]
        own = B.own_rows({s: daily[s] for s in syms if s in daily})
        doc["mm_own"] = B.update(own, B.nel_archive())[:30]
    except Exception as e:
        log.warning("Market Monitor nostro: %s", e)
        doc["mm_own"] = []
    try:                       # pool di Martin: le sue liste ricostruite [RONIN 17/10o]
        from . import pool as PL
        doc["pool"] = PL.pool_breadth(daily, [s for s in syms if s in daily and s not in NON_STOCK], q.index)
    except Exception as e:
        log.warning("pool di Martin: %s", e)
        doc["pool"] = None
    if C.GROUP_ETF:              # gruppo del titolo e grafico del suo ETF [RONIN 28/10a]
        try:
            from . import gruppo as GR
            gsyms = [s for s, m in metrics.items() if s not in NON_STOCK and m["dv5"] >= min(C.LONG_DV_MIN, C.SHORT_DV_MIN)]
            if C.JEFF:         # [JEFF] anche i titoli dell'universo di Jeff
                gsyms = sorted(set(gsyms) | set(doc["jeff"]["universe"]))
            doc["gruppo"] = GR.morning(daily, gsyms, as_of)
        except Exception as e:
            log.warning("gruppi ETF: %s", e)
            doc["gruppo"] = {}
    doc["theme_map"] = tmap        # nella cache: lista e card usano la stessa lettura
    work.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(doc))
    return doc


def jeff_compute(daily: dict, metrics: dict, uni: dict, ind: dict, jsyms: list[str], session: date, as_of: date) -> dict:
    """[JEFF 28/10] Universo di Jeff, candidati long (regole di Martin senza quelle che Jeff sostituisce), PEG, utili da
    tutte le fonti e EMA50 a 1 ora dei candidati (gate 5). Gira con compute(), quindi finisce nella cache della card."""
    universe, out_universe = [], {}
    for s in jsyms:
        m = metrics.get(s)
        if not m or "j_close" not in m:
            continue
        why = JF.universe_reason(s, m, uni.get(s), (ind.get(s) or {}).get("industry"))
        if why:
            out_universe[s] = why
        else:
            universe.append(s)
    cand, near = [], []
    for s in universe:
        ok, info = E.long_candidate(s, metrics[s])
        if ok:
            cand.append(s)
        elif E.open_checks(info) == ["confluence"]:          # "a un passo" (come in build): servono anche le sue date
            near.append(s)
    peg = []
    for s in universe:
        m = metrics[s]
        if PG.candidate(m):
            try:
                m.update(PG.read_peg(daily[s], m["j_atr"]))
            except Exception as e:
                log.warning("PEG %s: %s", s, e)
            if m.get("peg_ok"):
                peg.append(s)
    names = sorted(set(cand + near + peg))
    try:
        raw = D.fetch_earnings(names, since=as_of) if names else {}
    except Exception as e:
        log.warning("utili: %s", e)
        raw = {}
    ec = JF.earnings_check(names, raw, uni, session)
    try:
        ma = JF.ma_1h([s for s in cand if s not in ec["out"]], as_of)
    except Exception as e:
        log.warning("EMA50 a 1 ora: %s", e)
        ma = {}
    log.info("Jeff: universo %d (fuori %d), candidati long %d, a un passo %d, PEG %d, fuori per utili %d",
             len(universe), len(out_universe), len(cand), len(near), len(peg), len(ec["out"]))
    return dict(universe=universe, out_universe=out_universe, cand=cand, near=near, peg=peg, earnings_raw=raw,
                earnings=ec, ma1h={s: v.get("ma1h") for s, v in ma.items()},
                ma1h_err={s: v["err"] for s, v in ma.items() if "err" in v})


# ------------------------------------------------------------------ lista
def _hist(prefix: str, before: date, n: int) -> dict[str, object]:
    files = sorted(p for p in C.HISTORY.glob(f"{prefix}_*.json") if p.stem.split("_", 1)[1] < before.isoformat())
    return {p.stem.split("_", 1)[1]: json.loads(p.read_text(encoding="utf-8")) for p in files[-n:]}


def build(doc: dict, review: dict) -> dict:
    session, as_of, M = doc["session"], doc["as_of"], doc["metrics"]
    uni, ind = doc["uni"], doc["ind"]
    NON_STOCK.update(e for v in ((doc.get("theme_map") or {}).get("theme_etfs") or {}).values() for e in v)
    NON_STOCK.update(doc.get("basket_extra") or [])     # titoli dei basket fuori universo: solo per i temi [21/10]
    jo = set(doc.get("jeff_only") or [])                 # [JEFF] titoli solo di Jeff: fuori dalle misure di mercato
    jd = doc.get("jeff") if C.JEFF else None             # [JEFF] universo, candidati, PEG, utili e EMA50 1h di Jeff
    liquid = {s: m for s, m in M.items() if s not in NON_STOCK and s not in jo and m["dv5"] >= C.DV_MIN and m["close"] >= C.PRICE_MIN}
    lists = {s: m["list"] for s, m in liquid.items()}
    nL = sum(v == "Leading" for v in lists.values())
    nG = sum(v == "Lagging" for v in lists.values())
    share = nL / (nL + nG) if (nL + nG) else None
    prev_lists = _hist("lists", as_of, 5)
    share_prev = None
    if prev_lists:
        old = next(iter(prev_lists.values()))
        oL = sum(v == "Leading" for v in old.values())
        oG = sum(v == "Lagging" for v in old.values())
        share_prev = oL / (oL + oG) if (oL + oG) else None
    last_lists = list(prev_lists.values())[-1] if prev_lists else {}
    upgrades = sorted(s for s, v in lists.items() if v == "Leading" and last_lists.get(s) in ("Mediocre", "Lagging"))
    downgrades = sorted(s for s, v in lists.items() if v == "Lagging" and last_lists.get(s) in ("Mediocre", "Leading"))

    # scan
    potent = sorted((s for s, m in liquid.items() if m["close"] > m["e50"] and (m["ret1"] or 0) >= C.POTENT_MIN_RET),
                    key=lambda s: -(liquid[s]["ret1"] or 0))[:C.POTENT_TOP]
    leader = []
    if session.weekday() == 0:
        leader = sorted(liquid, key=lambda s: -(liquid[s]["ret21"] or -999))[:C.LEADER_TOP]
    potent_hist = {k: v for k, v in _hist("potent", as_of, 4).items()}
    potent_hist[as_of.isoformat()] = potent

    # temi: solo ETF tematici (gruppi della lista di Andrea + partecipazioni) e modifiche a mano, sui titoli >= 75M$;
    # niente industria Yahoo né cluster di correlazione: chi non è in un ETF resta senza tema [RONIN 15/10]
    tliquid = {s: m for s, m in M.items() if s not in NON_STOCK and s not in jo and m["dv5"] >= C.THEME_DV_MIN and m["close"] >= C.PRICE_MIN}   # [JEFF] jo
    tmap = doc.get("theme_map") or TM.refresh()          # cache di prima della mappa: si usa quella salvata
    if "theme_etfs" not in tmap:                         # cache con la vecchia mappa a basket: si rilegge
        tmap = TM.refresh()
    mapped = TM.groups_from_map(tmap, set(tliquid))
    map_groups = {k: v for k, v in mapped.items() if len(v) >= C.MAP_THEME_MIN_MEMBERS}
    in_map = {s for v in mapped.values() for s in v}
    groups: dict[str, list[str]] = dict(map_groups)
    # ETF senza azioni (GLD, IBIT, USO, TLT...): l'ETF stesso è membro del tema; un tema fatto solo di questi ETF
    # entra in classifica anche con un solo ETF [RONIN 15/10, Andrea]
    tmetrics = dict(tliquid)
    for th, es in (tmap.get("proxy_etfs") or {}).items():
        px = [e for e in es if e in M and M[e]["dv5"] >= C.THEME_DV_MIN]
        if not px:
            continue
        tmetrics.update({e: M[e] for e in px})
        groups[th] = mapped.get(th, []) + px
    theme_etfs = tmap.get("theme_etfs") or {}
    esc = doc.get("etf_scores")
    if C.THEME_SOURCE == "lst" and tmap.get("baskets"):
        # basket LST [RONIN 21/10, Andrea]: classifica = media equal-weight del Final_Score a 7 fattori di tutti i
        # titoli del basket (nessun filtro di liquidità), d5 sul punteggio di 5 sedute fa
        groups = {b: [t for t in dict.fromkeys(mem) if t in M] for b, mem in tmap["baskets"].items()}
        tmetrics = {t: M[t] for v in groups.values() for t in v}
        bsc = doc.get("basket_scores")
        rows = T.score_groups(groups, tmetrics, doc["closes"], doc["qqq_close"], potent_hist, min_members=C.LST_MIN_SCORED,
                              bscores=bsc, bscores_prev=doc.get("basket_scores_prev"))
        rows = [r for r in rows if (r.get("n_scored") or 0) >= C.LST_MIN_SCORED]
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        T.add_rs(rows)
    elif C.THEME_RANKING in ("etf", "etf_perf") and esc is not None and len(esc):
        # il tema si misura direttamente sui suoi ETF [RONIN 16/10, Andrea]; i titoli restano membri (tema del titolo)
        emet = dict(tmetrics)
        emet.update({e: M[e] for es in theme_etfs.values() for e in es if e in M})
        rows = T.score_groups(groups, emet, doc["closes"], doc["qqq_close"], potent_hist, bscores=esc,
                              etfs={th: es for th, es in theme_etfs.items()}, bscores_prev=doc.get("etf_scores_prev"))
    else:                      # cache senza punteggi ETF, o altro metodo scelto in config
        bsc = doc.get("basket_scores") if C.THEME_RANKING in ("basket", "etf") else None
        rows = T.score_groups(groups, tmetrics, doc["closes"], doc["qqq_close"], potent_hist, min_members=1, bscores=bsc)
    rows = T.add_phase(rows, T.load_prev_ranks(C.HISTORY, as_of))
    origin = tmap.get("themes") or {}
    for r in rows:
        r["source"] = origin.get(r["theme"], "etf")
    t_of = T.ticker_theme(rows, exclude=frozenset(TM.GENERIC_GROUPS))   # i generici non sono mai il tema di un titolo
    ranked = {r["theme"] for r in rows}
    for s, info in (tmap.get("tickers") or {}).items():         # tema principale della mappa, se è in classifica
        if s in M and s not in NON_STOCK and info["primary"] in ranked:     # anche sotto i 75M$ dei temi [16/10]
            t_of[s] = info["primary"]
    try:                                                         # pari merito tra temi: decide l'andamento
        ties = {s: [th for th in info["tied"] if th in ranked] for s, info in (tmap.get("tickers") or {}).items()
                if s in tliquid and info.get("tied")}
        t_of.update(T.break_ties(doc["closes"], map_groups, {s: v for s, v in ties.items() if len(v) > 1},
                                 min_members=C.MAP_THEME_MIN_MEMBERS))
    except Exception as e:
        log.warning("pari merito temi: %s", e)
    try:
        theme_props = T.proposals(doc["closes"], map_groups, [s for s in tliquid if s not in in_map],
                                  min_corr=C.THEME_PROPOSAL_CORR, min_members=C.MAP_THEME_MIN_MEMBERS)[:40]
    except Exception as e:
        log.warning("proposte temi: %s", e)
        theme_props = []
    try:                       # breadth alla Martin per la card [RONIN 17/10]
        potent_raw = [x for x, m in liquid.items() if m["close"] > m["e50"] and (m["ret1"] or 0) >= C.POTENT_MIN_RET]
        mbreadth = E.martin_breadth(M, liquid, lists, next(iter(prev_lists.values())) if prev_lists else None,
                                    potent_raw, t_of, list(prev_lists.values()))
    except Exception as e:
        log.warning("breadth alla Martin: %s", e)
        mbreadth = None
    t_pct = T.theme_rank_pct(rows)
    t_phase = {r["theme"]: r["phase"] for r in rows}
    t_stage = {r["theme"]: r["stage"] for r in rows if r.get("stage")}

    # regime
    idx = {k: E.index_state(M.get(k)) for k in C.INDICES}
    fb = J.feedback()
    mm_rows = doc.get("mm")
    if mm_rows is None:                             # cache di prima del Market Monitor
        mm_rows = D.fetch_market_monitor()[:60]
    full_rows = B.full_backup()                     # replica nostra: qui c'è lo studio 20% (Stockbee non lo pubblica)
    up20 = {r["date"]: {"up20w": r.get("up20w"), "down20w": r.get("down20w")} for r in full_rows if r.get("up20w") is not None}
    mm = E.market_monitor(mm_rows, as_of, up20)
    if mm is None:      # Stockbee/NEL senza la riga del giorno: replica nostra (universo completo, calcolata la
        #                 sera prima), poi il calcolo sui titoli della lista; entrambi calibrati su Stockbee [RONIN 15/10]
        for mrows in (full_rows, doc.get("mm_own") or []):     # mrows: "rows" sono i temi [fix 19/10]
            mm = E.market_monitor(mrows, as_of, up20)
            if mm:
                mm["source"] = "own"
                break
    else:
        mm["source"] = "Stockbee"
    reg = E.regime(idx, share, share_prev, fb, mm)
    if C.BIAS_SOURCE == "pool" and doc.get("pool"):  # liste del pool di Martin + feedback [RONIN 17/10o]
        reg = E.regime_pool(doc["pool"], J.signal_feedback())
    elif C.BIAS_SOURCE in ("martin", "pool"):        # liste dell'universo + feedback [RONIN 17/10j]
        reg = E.regime_martin(mbreadth, J.signal_feedback())
    try:                                            # parte del regime della card: ±4% a 20 giorni, grafico 20% e T2108
        mm_hist = BC.mm_history(list(mm_rows) + B.nel_archive(), full_rows, as_of)
    except Exception as e:
        log.warning("storico Market Monitor per la card: %s", e)
        mm_hist = []
    rev = E.flow_reversal(mm_hist) if (mm_hist and C.STOCKBEE_IN_CARD) else None   # potential trend reversal [16/10; tolto 19/10a]
    if rev:
        reg["why"].insert(0, f"potential trend reversal: ±4% flow turned to {rev['direction']} on {rev['date']} "
                             f"(day {rev['day']} of {C.REVERSAL_DAYS})")
    if mm and mm.get("source") == "own":
        if C.STOCKBEE_IN_CARD:
            reg["why"].insert(0, "Market Monitor: own calculation (Stockbee unavailable)")

    # candidati
    earn = doc.get("earnings") or {}
    block_days = {d.isoformat() for d in sessions_from(session, C.EARNINGS_BLOCK_SESSIONS)}
    win = sorted(d for d in up20 if d <= as_of.isoformat())[-C.PB_UP20_WINDOW:]
    up20_hi = max([up20[d].get("up20w") or 0 for d in win] or [0])
    down20_hi = max([up20[d].get("down20w") or 0 for d in win] or [0])
    ok_stage = {"long": set(C.STAGE_LONG) | ({"FADING"} if down20_hi >= C.STAGE_FADING_LONG_DOWN20 else set()),
                "short": set(C.STAGE_SHORT)}            # FADING sempre aperto agli short [RONIN 16/10]

    def stage_ok(side: str, th: Optional[str]) -> bool:
        """Stadio del tema adatto al lato [RONIN 16/10, Andrea]: long LEADING/BUILDING, short SLIPPING/WEAK, FADING
        agli short con +20% >= 200 e ai long con -20% >= 200. Senza tema o senza stadio: nessun filtro."""
        st = t_stage.get(th) if th else None
        if st is None:
            return not C.STAGE_REQUIRE_THEME
        return st in ok_stage[side]

    def strong_sector(s: str) -> Optional[str]:
        """Mai shortare il settore forte né il suo titolo più debole [ML; RONIN 14/10]: stadio del tema non adatto
        agli short (dal 16/10; prima: tema nella metà alta della classifica), o ETF di settore del tema sopra la EMA9
        weekly in salita."""
        th = t_of.get(s)
        if t_stage:
            if not stage_ok("short", th):
                return "theme_stage"
        elif C.SHORT_BLOCK_STRONG_THEME and th in t_pct and t_pct[th] >= C.SHORT_BLOCK_THEME_PCT:   # tolto 19/10e
            return "strong_theme"
        etf = next((e for e in theme_etfs.get(th, []) if e in M), None) if th else None   # ETF del tema (lista di Andrea)
        em = M.get(etf) if etf else None
        if C.SHORT_BLOCK_ETF_W9_RISING and em and em["w_close"] > em["ew9"] and em["ew9_slope"] > 0:
            return "strong_sector_etf"
        return None

    cands, near = [], []
    pool = {s: m for s, m in M.items() if s not in NON_STOCK and m["close"] >= C.PRICE_MIN
            and m["dv5"] >= min(C.LONG_DV_MIN, C.SHORT_DV_MIN)}          # 50M$ per i due lati [RONIN 16/10]
    jeff_earn_out: dict[str, str] = {}
    if jd is not None:         # [JEFF] idee di trade solo dall'universo di Jeff (liquidità, ATR%, esclusioni, mcap)
        pool = {s: M[s] for s in jd["universe"] if s in M and s not in NON_STOCK}
    for s, m in pool.items():
        if jd is not None and s in jd["earnings"]["out"]:   # [JEFF] utili nelle prossime 5 sedute: fuori da tutto
            jeff_earn_out[s] = jd["earnings"]["out"][s]
            continue
        for side, fn in (("long", E.long_candidate), ("short", E.short_candidate)):
            if jd is not None and side == "short" and C.JEFF_LONG_ONLY:      # [JEFF] solo long
                continue
            if side == "long" and m["dv5"] < C.LONG_DV_MIN and jd is None:    # [JEFF] con Jeff vale la sua liquidità
                continue
            ok, info = fn(s, m)
            if side == "long" and t_stage:
                info["checks"]["theme_stage"] = stage_ok("long", t_of.get(s))
                ok = all(info["checks"].values())
            if side == "short":
                blocked = strong_sector(s)
                if blocked and blocked != "theme_stage" and info.get("short_type") == "top ex-leader" \
                        and C.EXLEADER_IGNORES_STRONG_SECTOR:
                    blocked = None              # SNDK, MU: ex-leader in un tema ancora forte [RONIN 14/10]; lo stadio
                    #                             del tema vale anche per loro (FADING solo con +20% >= 200) [16/10]
                info["checks"]["weak_sector"] = blocked is None
                # la sola EMA9 come ingresso secondario se gli short stanno funzionando [ML, thread "Shorting"]
                sec = (C.SHORT_EMA9_IF_FEEDBACK and (fb.get("short_r") or 0) >= C.FEEDBACK_GOOD_R
                       and not info["checks"]["strong_level"] and info["checks"]["confluence"])
                if sec:
                    info["checks"]["strong_level"] = True
                ok = all(info["checks"].values())
            lv = info["level"]
            row = dict(ticker=s, side=side, setup=f"pullback {side}", list=m["list"], level=E._r(lv["price"]) if lv else None,
                       level_members=lv["members"] if lv else [], confluence=lv["count"] if lv else 0,
                       dist_pct=E._r(lv["dist_pct"]) if lv else None, adr=E._r(m["adr"]), dv5=E._r(m["dv5"], 0),
                       e9d=E._r(m["e9"]), atr_d=E._r(m.get("atr")),
                       rs21=m.get("rs21"), rs63=m.get("rs63"), ext50_atr=E._r(m.get("ext50_atr")), theme=t_of.get(s), theme_phase=t_phase.get(t_of.get(s)),
                       theme_stage=t_stage.get(t_of.get(s)),
                       exch=uni.get(s, {}).get("exchange"), earnings=earn.get(s), open=E.open_checks(info),
                       zone_levels=info.get("zone_levels", 0))
            if side == "long" and m.get("hi_bo") and m["hi_bo"] > m["close"] \
                    and (m["hi_bo"] / m["close"] - 1) * 100 <= C.BREAKOUT_MAX_DIST_ADR * (m["adr"] or 0):
                row["breakout_level"] = E._r(m["hi_bo"])           # resistenza sopra per il breakout [RONIN 14/10]
            if side == "short":
                row.update(short_type=info.get("short_type"), weekly_healthy=info.get("weekly_healthy"),
                           ema_spread_adr=E._r(info.get("ema_spread_adr")), secondary_ema9=bool(sec))
                if sec:
                    row["setup"] = "pullback short (EMA9, ingresso secondario)"
                elif info.get("short_type") == "top ex-leader":
                    row["setup"] = "short top ex-leader (metà rischio)"
                elif info.get("short_type") == "trend che gira":
                    row["setup"] = "short trend che gira"
            if ok:
                if row["earnings"] and row["earnings"] in block_days:
                    row["open"] = ["earnings"]
                    near.append(row)
                else:
                    cands.append(row)
            elif len(row["open"]) == 1 and row["open"][0] in ("confluence", "not_extended", "below_ema9", "strong_level"):
                near.append(row)
    if jd is not None:         # [JEFF] misure di Jeff sulle righe (liquidità per l'ingresso, RS e VCP per card e giornale)
        for r in cands + near:
            r.update(adv50=E._r(M[r["ticker"]].get("j_adv"), 0), jeff_rs=M[r["ticker"]].get("j_rs"))
    peg = peg_rows(jd, M, uni, t_of, t_phase, t_stage, earn) if jd is not None else []   # [JEFF] PEG delayed reaction

    map_themes = {k: v.get("themes", []) for k, v in (tmap.get("tickers") or {}).items()}

    def in_play(r) -> bool:
        names = [r.get("theme") or ""] + list(map_themes.get(r["ticker"], []))
        for n in names:
            low = n.lower()
            if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in C.INPLAY_THEME_WORDS):
                return True
        return False

    # consonanza dei timeframe [RONIN 16/10, Andrea]: weekly dal daily già scaricato, 60m dalle barre orarie
    try:
        hb = D.download_intraday([r["ticker"] for r in cands + near[:60] + peg], period="1mo", interval="60m")   # [JEFF] + PEG
        hb = {k: v[v.index.date <= as_of] for k, v in hb.items()}       # solo barre chiuse fino ad as_of
    except Exception as e:
        log.warning("barre 60m per la consonanza: %s", e)
        hb = {}
    for r in cands + near + peg:                                       # [JEFF] + PEG
        r["tf_w"] = E.weekly_align(M[r["ticker"]], r["side"])
        r["tf_h"] = E.hourly_align(hb.get(r["ticker"]), r["side"])
        r["tf_ok"] = 1 + (r["tf_w"] == 1) + (r["tf_h"] == 1)            # timeframe concordi su 3 (il daily c'è sempre)
    # multi-edge [RONIN 22/10, Andrea; J Law METS]: M&T, S&R, PA/VOL, MTF, RS per ogni candidato (edges.py); la rotazione
    # usa il quadrante del gruppo del titolo nel grafico RS settimana/mese dei basket
    quad_of = {r["theme"]: r.get("quadrant") for r in rows if r.get("quadrant")}
    if C.META_EDGES:
        for r in cands + near + peg:                                   # [JEFF] + PEG
            m = M[r["ticker"]]
            try:
                r.update(EDG.evaluate(r, m, quad_of.get(r.get("theme")),
                                      EDG.hourly_levels(hb.get(r["ticker"]), r["side"], m["close"])))
            except Exception as e:
                log.warning("edge %s: %s", r["ticker"], e)
                continue
            L = (m.get("tl") or {}).get("up" if r["side"] == "long" else "down")
            if L:              # trendline nel verso del trade: valore di ieri, tocchi, canale
                r["tl"] = dict(value=E._r(L["value"]), touches=L["touches"], dist_pct=E._r(L["dist_pct"], 1),
                               channel=bool(L.get("channel")))
            z = HZM.near(m.get("hz") or [], r["level"], m["adr"]) if r.get("level") else None
            if z:              # orizzontale (linea o area) entro 1 ADR dal livello d'ingresso [RONIN 23/10]
                r["hz"] = dict(kind=z["kind"], price=E._r(z["price"]), lo=E._r(z["lo"]), hi=E._r(z["hi"]),
                               touches=z["touches"])

    def score(r):
        # forza relativa: 3 mesi pesa più del mese [RONIN 20/10b, Andrea]
        rs = (C.RS63_WEIGHT * max(-1.0, min(1.0, (r.get("rs63") or 0) / 40.0))
              + C.RS21_WEIGHT * max(-1.0, min(1.0, (r["rs21"] or 0) / 20.0))) * (1 if r["side"] == "long" else -1)
        if r["side"] == "long" and r.get("ext50_atr") is not None and r["ext50_atr"] <= C.LONG_EXT50_BONUS_ATR:
            rs += C.LONG_EXT50_BONUS            # entro 4 ATR dalla SMA50: meglio [RONIN 20/10b, Andrea]
        ema50 = C.SHORT_EMA50_BONUS if (r["side"] == "short" and "EMA50" in (r["level_members"] or [])) else 0  # [RONIN 14/10]
        tight = 0.0
        if r["side"] == "short" and r.get("ema_spread_adr") is not None:      # EMA strette = più rigetti [ML]
            tight = C.SHORT_TIGHT_BONUS * max(0.0, 1 - r["ema_spread_adr"] / C.SHORT_EMA_TIGHT_ADR)
        inplay = 0.0
        if r["side"] == "short" and in_play(r):                          # temi in play prima dei difensivi [RONIN 14/10]
            inplay = C.SHORT_INPLAY_BONUS
        tw = C.THEME_WEIGHT_LONG if r["side"] == "long" else C.THEME_WEIGHT_SHORT   # [RONIN 14/10]
        if not C.THEME_IN_SELECTION:       # [20/10, prova di Andrea] solo il setup: il tema non entra nel punteggio
            tw, inplay = 0.0, 0.0
        tf = (C.TF_WEEKLY_AGAINST if r.get("tf_w") == -1 else 0) + (C.TF_FULL_BONUS if r.get("tf_ok") == 3 else 0)
        zone = C.ZONE_LEVEL_WEIGHT * max(0, (r.get("zone_levels") or 0) - (r["confluence"] or 0))   # più livelli [16/10]
        return tw * t_pct.get(r["theme"], 0) + 0.5 * r["confluence"] + (1 if (r["dv5"] or 0) >= C.DV_TIER else 0) + rs + ema50 + tight + inplay + tf + zone
    for r in cands:
        r["score"] = round(score(r), 3)
        rv = review.get(r["ticker"]) or {}
        r["grade"] = rv.get("grade", "")
        r["note"] = rv.get("note", "")
        r["demoted"] = rv.get("demote")
    for r in near:                                # anche i "a un passo" hanno il punteggio: servono all'ordine
        r["score"] = round(score(r), 3)
        r["grade"] = (review.get(r["ticker"]) or {}).get("grade", "")
    for r in peg:                                 # [JEFF] PEG: stesso punteggio e stessa revisione dei candidati
        r["score"] = round(score(r), 3)
        rv = review.get(r["ticker"]) or {}
        r["grade"], r["note"], r["demoted"] = rv.get("grade", ""), rv.get("note", ""), rv.get("demote")
    # watchlist in ordine di qualità del setup [RONIN 16/10, Andrea]: punteggio del setup (tema, confluenza, liquidità,
    # forza relativa, livello forte...); il voto della revisione solo a parità (Andrea: HUM C meglio di XP)
    pool_m = (doc.get("pool") or {}).get("members") or {}
    grp = doc.get("gruppo") if C.GROUP_ETF else None
    if grp:
        from . import gruppo as GR
    for r in cands + near + peg:                                       # [JEFF] + PEG
        r["in_pool"] = r["ticker"] in pool_m
        if grp:                    # gruppo e ETF del gruppo [RONIN 28/10a]
            r.update(GR.row_fields(r["ticker"], r["side"], grp))
    if jd is not None:         # [JEFF] gli 8 gate del Focus di Jeff sui candidati long (chi non li chiude resta in tracking)
        for r in cands:
            if r["side"] == "long":
                r.update(JF.gate_fields(M[r["ticker"]], (jd.get("ma1h") or {}).get(r["ticker"])))
    jeff_ok = lambda r: (not C.JEFF) or bool(r.get("jeff_ok"))       # [JEFF] Focus solo con i gate di Jeff chiusi
    # con POOL_PRIORITY prima i titoli del pool di Martin: lui fa trade dalla sua watchlist [RONIN 17/10p]
    # multi-edge [RONIN 22/10]: con META_RANK a parità di pool prima i setup con più edge (tutti, o solo quelli del lato
    # con META_RANK_MODE "side"), poi il punteggio
    def edge_rank(r) -> int:
        if not C.META_RANK:
            return 0
        if C.META_RANK_MODE == "side":
            return -sum(k in (r.get("edges") or []) for k in C.META_SIDE_EDGES.get(r["side"], ()))
        return -(r.get("n_edges") or 0)
    # [RONIN 28/10a] a parità di pool ed edge prima i titoli più forti (long) / più deboli (short) della media del gruppo
    gfav = lambda r: -(r.get("group_fav") or 0) if (C.GROUP_ETF and C.GROUP_PREFER_RS) else 0
    quality = lambda r: (0 if (not C.POOL_PRIORITY or r.get("in_pool")) else 1, edge_rank(r), gfav(r), -r["score"],
                         {"A": 0, "B": 1, "": 2, "C": 3}.get(r.get("grade") or "", 2))
    cands.sort(key=quality)
    near.sort(key=quality)
    sides = {"LONG": ("long",), "SHORT": ("short",), "MISTO": ("long", "short")}.get(reg["bias"], ())
    # studio 20% [RONIN 20/10e, Andrea]: niente long se ieri più di U20_LONG_MAX titoli +20% in 5 giorni (mercato
    # surriscaldato), niente short se più di D20_SHORT_MAX titoli -20%
    s20 = up20.get(as_of.isoformat()) or {}
    if C.U20_FILTER and (s20.get("up20w") or 0) > C.U20_LONG_MAX:
        sides = tuple(x for x in sides if x != "long")
        reg["why"].append(f"20% study up {s20['up20w']:.0f} > {C.U20_LONG_MAX}: no longs")
    if C.U20_FILTER and (s20.get("down20w") or 0) > C.D20_SHORT_MAX:
        sides = tuple(x for x in sides if x != "short")
        reg["why"].append(f"20% study down {s20['down20w']:.0f} > {C.D20_SHORT_MAX}: no shorts")
    cap = (C.MIXED_MAX_FOCUS if reg["bias"] == "MISTO" else C.LONG_MAX_FOCUS if sides == ("long",) else C.SHORT_MAX_FOCUS)
    # [RONIN 28/10a] niente short con l'ETF del gruppo in trend su
    gblock = lambda r: bool(C.GROUP_ETF and C.GROUP_SHORT_NOT_UP and r["side"] == "short" and r.get("group_up"))
    for r in cands:
        if gblock(r):
            r["group_block"] = f"group ETF {r.get('group_etf')} in uptrend"
    elig = [r for r in cands if r["side"] in sides and not r["demoted"] and (r.get("in_pool") or not C.POOL_FOCUS_ONLY)
            and (not C.META_FILTER or (r.get("n_edges") or 0) >= C.META_MIN_EDGES) and not gblock(r)  # [RONIN 22/10, multi-edge]
            and jeff_ok(r)]                                                                           # [JEFF]
    focus = elig[:cap]                                                                # i migliori per punteggio
    if reg["bias"] == "MISTO":       # [RONIN 19/10e, Andrea] MISTO: i migliori MIXED_FOCUS_PER_SIDE per lato (prima 3 in
        #                              tutto: i long hanno punteggi più alti e prendevano tutti i posti, SNDK 8-9/10)
        focus = ([r for r in elig if r["side"] == "long"][:C.MIXED_FOCUS_PER_SIDE]
                 + [r for r in elig if r["side"] == "short"][:C.MIXED_FOCUS_PER_SIDE])
    if rev and C.REVERSAL_SKIP_DAY1 and rev.get("day") == 1:      # giorno dell'inversione: si sta fuori
        sides, focus = (), []
    elif rev:                  # potential trend reversal: Focus pieni per i due lati [RONIN 16/10, Andrea]
        sides = ("long", "short")
        elig = [r for r in cands if not r["demoted"] and (not C.META_FILTER or (r.get("n_edges") or 0) >= C.META_MIN_EDGES)
                and not gblock(r) and jeff_ok(r)]                                                     # [JEFF]
        focus = ([r for r in elig if r["side"] == "long"][:C.LONG_MAX_FOCUS]
                 + [r for r in elig if r["side"] == "short"][:C.SHORT_MAX_FOCUS])
    if reg["bias"] == "SHORT" and not rev:           # altri short ad alto punteggio oltre gli 8 [RONIN 14/10]
        focus += [r for r in elig[cap:] if r["score"] >= C.SHORT_FOCUS_EXTRA_MIN_SCORE][:C.SHORT_FOCUS_MAX - len(focus)]
    for r in focus:
        r["in_play"] = in_play(r) if r["side"] == "short" else None
    # sincronia con QQQ ed ETF del tema all'ingresso [RONIN 17/10; ML: "titolo e mercato sulla stessa resistenza",
    # 26/02; ALAB "da evitare" con l'ETF sulla sua 50, 05/08]: l'alert mostra dove stanno rispetto a 9/21 daily
    sync_levels = {}
    for k in ("QQQ",):
        if k in M:
            sync_levels[k] = {"e9": E._r(M[k]["e9"]), "e21": E._r(M[k]["e21"]), "e50": E._r(M[k]["e50"])}
    for r in cands + peg:                                              # [JEFF] + PEG
        es = [e for e in theme_etfs.get(r.get("theme") or "", []) if e in M]
        if es:
            e = max(es, key=lambda x: M[x].get("dv20") or 0)
            r["sync_etf"] = e
            sync_levels[e] = {"e9": E._r(M[e]["e9"]), "e21": E._r(M[e]["e21"]), "e50": E._r(M[e]["e50"])}
    # lato opposto al regime: sempre i migliori (qualità), max 3, tracciati come ombra [RONIN 13/10]
    counter = [dict(r, counter=True) for r in cands
               if sides and r["side"] not in sides and not r["demoted"] and r.get("grade") != "C"
               and (r.get("in_pool") or not C.POOL_FOCUS_ONLY)
               and r["confluence"] >= C.COUNTER_MIN_CONFLUENCE
               and (not C.META_FILTER or (r.get("n_edges") or 0) >= C.META_MIN_EDGES)
               and jeff_ok(r)                                                                         # [JEFF]
               and ((not C.THEME_IN_SELECTION or r["theme"] in t_pct and ((t_stage.get(r["theme"]) in ok_stage[r["side"]]) if t_stage   # stadio [16/10]
                     else t_pct[r["theme"]] >= C.COUNTER_MIN_THEME_PCT))                # long: tema nella metà alta
                    if r["side"] == "long" else
                    (not C.SHORT_BLOCK_STRONG_THEME or (r["theme"] in t_pct and t_pct[r["theme"]] < C.SHORT_BLOCK_THEME_PCT)))
               ][:C.COUNTER_MAX]        # short: niente requisito di tema debole dal 19/10e [Andrea]
    fset = {r["ticker"] for r in focus} | {r["ticker"] for r in counter}
    for r in peg:              # [JEFF] PEG: con il lato long chiuso dal regime gli alert sono solo informativi (trade ombra)
        r["also_focus"] = r["ticker"] in fset
        r["counter"] = "long" not in sides
    # fakeout: gli altri candidati dal lato del regime, sotto controllo per il solo falso breakout/breakdown [16/10]
    fake = [dict(r, fakeout=True, setup="failed breakdown long" if r["side"] == "long" else "failed breakout short") for r in cands
            if C.FAKEOUT_WATCH and r["side"] in sides and r["ticker"] not in fset and not r["demoted"]][:C.FAKEOUT_MAX]
    tracking = []
    for r in cands:
        if r["ticker"] not in fset and r["ticker"] not in tracking:
            tracking.append(r["ticker"])
    for r in near[:60]:                          # a un passo: anche loro solo nel file [RONIN 13/10]
        if r["ticker"] not in fset and r["ticker"] not in tracking:
            tracking.append(r["ticker"])
    pot = potent if jd is None else [s for s in potent if s in set(jd["universe"]) and s not in jeff_earn_out]  # [JEFF]
    for s in pot[:10]:                           # potent senza setup: in coda (qualità del setup sconosciuta)
        if s not in fset and s not in tracking:
            tracking.append(s)
    side_of = {}
    for r in cands + near[:60]:
        side_of.setdefault(r["ticker"], r["side"])
    tracking_long = [t for t in tracking if side_of.get(t, "long") == "long"]     # potent: lato long
    tracking_short = [t for t in tracking if side_of.get(t) == "short"]

    # messaggio dei temi sotto la card [RONIN 14/10]
    spy21 = (M.get("SPY") or {}).get("ret21")
    sscore = doc.get("stock_perf_scores") if C.THEME_RANKING == "etf_perf" else None   # stesso ordine degli ETF [17/10]
    if sscore is None or not len(sscore):
        sscore = doc.get("basket_scores")
    fs = sscore["Final_Score"].to_dict() if sscore is not None and len(sscore) else {}

    def etf_label(r: dict) -> Optional[str]:
        """Livelli dell'ETF più liquido del tema (EMA 9/21/50 daily, 9 weekly): ">" sopra, "<" sotto [RONIN 17/10]."""
        if esc is None or not len(esc) or "lv" not in esc.columns or not r.get("etfs"):
            return None
        e = max((x for x in r["etfs"] if x in esc.index), key=lambda x: M.get(x, {}).get("dv20") or 0, default=None)
        if e is None:
            return None
        lv = esc.loc[e, "lv"]
        return f"{e} " + " ".join((">" if lv[k] else "<") + n for k, n in (("9", "9"), ("21", "21"), ("50", "50"), ("w9", "w9")))

    def msg_tickers(r: dict, mem: list[str], src: dict) -> list[str]:
        """Tra parentesi i titoli del tema in ordine di punteggio a 7 fattori, dal più alto [RONIN 16/10, Andrea];
        senza punteggio in coda per liquidità. Tema senza titoli (oro, petrolio, bitcoin spot...): i suoi ETF."""
        st = [x for x in r.get("members", []) if x in tmetrics]
        if not st:
            return sorted(mem, key=lambda x: -src[x]["dv5"])[:C.THEME_MSG_TICKERS]
        return sorted(st, key=lambda x: (x not in fs, -fs.get(x, 0), -tmetrics[x]["dv5"]))[:C.THEME_MSG_TICKERS]
    tstats = []
    for r in rows:
        if r.get("etfs"):      # tema misurato sui suoi ETF: 1M, Leading/Lagging e nomi tra parentesi sono degli ETF
            mem, src = r["etfs"], M
        else:
            mem, src = [x for x in r.get("members", []) if x in tmetrics], tmetrics
        if not mem:
            continue
        rets = sorted(src[x]["ret21"] for x in mem if src[x].get("ret21") is not None)
        med = (rets[len(rets) // 2] if not r.get("etfs") else sum(rets) / len(rets)) if rets else None
        if C.THEME_SOURCE == "lst" and r.get("ret1m") is not None:   # basket LST: 1M = media equal-weight, come la classifica
            med = r["ret1m"]
        tstats.append(dict(theme=r["theme"], score=round(r["score"]), stage=r.get("stage"), d5=r.get("d5"), ret21=E._r(med, 1),
                           vs_spy=E._r(med - spy21, 1) if (med is not None and spy21 is not None) else None,
                           lead=r["lead"], lagging=round(sum(src[x]["list"] == "Lagging" for x in mem) / len(mem), 2),
                           tickers=msg_tickers(r, mem, src), etf_lv=etf_label(r)))
    t_lead = sorted((x for x in tstats if x["lead"] >= C.THEME_LEADING_MIN_LEAD and (x["ret21"] or 0) > 0), key=lambda x: -x["score"])
    t_brk = sorted((x for x in tstats if x["lagging"] >= C.THEME_BREAKING_MIN_LAG and (x["ret21"] or 0) < 0), key=lambda x: x["ret21"])
    themes_msg = dict(total=len(tstats), leading_n=len(t_lead), leading=t_lead[:C.THEME_MSG_ROWS],
                      breaking_n=len(t_brk), breaking=t_brk[:C.THEME_MSG_ROWS])
    if C.THEME_SOURCE == "lst" and tmap.get("baskets"):    # classifica complessiva e grafico RS dei basket LST [RONIN 21/10]
        by = {x["theme"]: x for x in tstats}
        rk = []
        for r in rows:
            if r.get("rs_w") is None:
                continue
            x = by.get(r["theme"]) or {}
            rk.append(dict(theme=r["theme"], rank=r["rank"], score=round(r["score"]), d5=r.get("d5"),
                           rs_w=r["rs_w"], rs_m=r["rs_m"], rs_q=r.get("rs_q"), quadrant=r["quadrant"], ret1w=E._r(r.get("ret1w"), 1),
                           ret1m=E._r(r.get("ret1m"), 1), n=r.get("n_scored"), tickers=(x.get("tickers") or [])[:5]))
        themes_msg.update(source="lst", ranking=rk[:C.THEME_RANK_ROWS], bottom=rk[-5:] if len(rk) > C.THEME_RANK_ROWS + 5 else [],
                          ranked_n=len(rk), points=[{k: x.get(k) for k in ("theme", "rs_w", "rs_m", "rs_q", "score")} for x in rk],
                          baskets_fetched=(tmap.get("baskets_fetched_utc") or "")[:10])

    top = [r for r in rows if r["rank"] <= 3]
    rising = [r for r in rows if r["phase"] == "preparazione"][:3]
    tl = ", ".join(f"{r['theme']} ({C.PHASE_EN.get(r['phase'], r['phase'])})" for r in top)
    if rising:
        tl += " · rising: " + ", ".join(r["theme"] for r in rising)
    return dict(mm_hist=mm_hist[-20:], mm_hist_full=mm_hist, reversal=rev, martin_breadth=mbreadth, martin_pool=doc.get("pool"), sync_levels=sync_levels,
        signal_feedback=J.signal_feedback(),
        session=session.isoformat(), as_of=as_of.isoformat(), rules_version=C.RULES_VERSION,
        bias=reg["bias"], bias_score=reg["score"], score_bias=reg.get("score_bias"), risk_pct=reg.get("risk_pct", C.RISK_PCT), bias_why="; ".join(reg["why"]), market_monitor=mm, indices=idx,
        qqq_prev_close=E._r(M["QQQ"]["close"]) if "QQQ" in M else None, feedback=fb, qqq_ctx=E.qqq_context(M.get("QQQ")),
        breadth=dict(leading=nL, lagging=nG, mediocre=len(lists) - nL - nG, share=E._r(share, 3),
                     share_prev=E._r(share_prev, 3), upgrades=upgrades[:40], downgrades=downgrades[:40]),
        theme_proposals=theme_props, theme_map_built=tmap.get("built_utc"), theme_map_changes=tmap.get("changes"),
        focus=focus, counter_focus=counter, fakeout_watch=fake, tracking=tracking, tracking_long=tracking_long, tracking_short=tracking_short, candidates=cands, near_misses=near[:60], potent=potent, leader=leader,
        themes=[{k: (E._r(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows[:40]],
        themes_line=tl, themes_msg=themes_msg, lists=lists, stale=len(doc["stale"]), stale_names=sorted(doc["stale"])[:50],
        **({"peg_watch": peg, "jeff": jeff_summary(jd, cands, focus, jeff_earn_out)} if C.JEFF else {}),   # [JEFF]
    )


def peg_rows(jd: dict, M: dict, uni: dict, t_of: dict, t_phase: dict, t_stage: dict, earn: dict) -> list[dict]:
    """[JEFF 28/10] Lista PEG delayed reaction (regole di Jeff, peg.py) con il livello del sistema: la confluenza di
    supporti di Martin entro LEVEL_MAX_DIST_ADR ADR con almeno CONFLUENCE_MIN livelli. Con il livello il PEG va negli
    alert e nel giornale come i Focus (setup "PEG delayed reaction"); senza, resta solo in card e txt. Il gap deve essere
    confermato da una data degli utili; fuori chi ha gli utili nelle prossime 5 sedute. I più recenti prima."""
    out = []
    raw = jd.get("earnings_raw") or {}
    for s in jd.get("peg") or []:
        if s in jd["earnings"]["out"] or s not in M:
            continue
        m = M[s]
        e = raw.get(s) or {}
        if not PG.confirm_earnings(m, (e.get("past_dates") or []) + (e.get("calendar") or [])):
            continue
        m["peg_earnings"] = True
        cl = E.best_cluster(m["supports"], m["close"])
        reach = bool(cl and cl["dist_pct"] <= C.LEVEL_MAX_DIST_ADR * m["adr"])
        tradable = bool(C.PEG_ALERTS and reach and cl["count"] >= C.CONFLUENCE_MIN)
        out.append(dict(
            ticker=s, side="long", setup="PEG delayed reaction", list=m["list"],
            level=E._r(cl["price"]) if tradable else None, level_members=cl["members"] if tradable else [],
            confluence=cl["count"] if cl else 0, dist_pct=E._r(cl["dist_pct"]) if cl else None, adr=E._r(m["adr"]),
            dv5=E._r(m["dv5"], 0), e9d=E._r(m["e9"]), atr_d=E._r(m.get("atr")), rs21=m.get("rs21"), rs63=m.get("rs63"),
            ext50_atr=E._r(m.get("ext50_atr")), theme=t_of.get(s), theme_phase=t_phase.get(t_of.get(s)),
            theme_stage=t_stage.get(t_of.get(s)), exch=uni.get(s, {}).get("exchange"), earnings=earn.get(s),
            open=[] if tradable else ["confluence"], zone_levels=E.zone_levels(m["supports"], cl, m["adr"]) if tradable else 0,
            peg=True, tradable=tradable,
            peg_level_note=None if tradable else (f"best support {cl['count']} level{'s' if cl['count'] != 1 else ''} "
                                                  f"{cl['dist_pct']:.1f}% away" if cl else "no support level"),
            peg_date=m["peg_date"], peg_gap_pct=E._r(m["peg_gap_pct"], 1), peg_vol_mult=E._r(m["peg_vol_mult"], 1),
            peg_low=E._r(m["peg_day_low"]), peg_high=E._r(m["peg_day_high"]), peg_pivot=E._r(m["peg_pivot"]),
            peg_pos=E._r(m.get("peg_pos")), peg_higher_low=m.get("peg_higher_low"), peg_range5_atr=E._r(m["peg_range5_atr"], 1),
            peg_text=PG.describe_peg(m), jeff_rs=m.get("j_rs"), adv50=E._r(m.get("j_adv"), 0),
        ))
    return sorted(out, key=lambda x: (x["peg_date"], x.get("jeff_rs") or 0), reverse=True)


def jeff_summary(jd: Optional[dict], cands: list[dict], focus: list[dict], earn_out: dict) -> Optional[dict]:
    """[JEFF] Numeri di Jeff per il dettaglio e il riepilogo: universo, esclusi per utili, candidati fermati dai gate."""
    if jd is None:
        return None
    held = {r["ticker"]: r.get("jeff_why") for r in cands if r["side"] == "long" and not r.get("jeff_ok")}
    from collections import Counter
    gates = Counter(c for r in cands if r["side"] == "long" for c in (r.get("jeff_open") or []))
    return dict(universe=len(jd["universe"]), out_universe=len(jd["out_universe"]),
                out_universe_why=dict(Counter(w.split(" ")[0] for w in jd["out_universe"].values())),
                earnings_window=jd["earnings"]["window"], earnings_out=earn_out,
                earnings_missing=jd["earnings"]["missing"][:40], candidates_long=sum(r["side"] == "long" for r in cands),
                gates_closed=sum(bool(r.get("jeff_ok")) for r in cands), held_by_gates=held, gates_open_count=dict(gates),
                ma1h_missing=sorted(jd.get("ma1h_err") or {}), focus=[r["ticker"] for r in focus])


# ------------------------------------------------------------------ testi
def summary_it(res: dict) -> str:
    fo = ", ".join(r["ticker"] + (f" ({r['n_edges']} edge)" if r.get("n_edges") is not None else "")
                   for r in res["focus"]) or "nessuno"
    lines = [f"**Lista {res['session']}** (close {res['as_of']})",
             f"Bias: {res['bias']} (rischio {res.get('risk_pct', C.RISK_PCT):.2f}%) — {res['bias_why']}",
             f"Focus: {fo}",
             f"Tracking long ({len(res['tracking_long'])}): " + ", ".join(res["tracking_long"][:25]),
             f"Tracking short ({len(res['tracking_short'])}): " + (", ".join(res["tracking_short"][:25]) or "-"),
             f"Temi: {res['themes_line']}",
             (f"Proposte di tema ({len(res['theme_proposals'])}, da approvare): "
              + ", ".join(f"{p['ticker']}→{p['theme']} {p['corr']:.2f}" for p in res['theme_proposals'][:8]))
             if res.get("theme_proposals") else "Proposte di tema: nessuna",
             f"Breadth: Leading {res['breadth']['leading']}, Lagging {res['breadth']['lagging']}; "
             f"saliti in Leading: {', '.join(res['breadth']['upgrades'][:10]) or '-'}"]
    dem = [r["ticker"] + f" ({r['demoted']})" for r in res["candidates"] if r.get("demoted")]
    if dem:
        lines.append("Declassati in revisione: " + ", ".join(dem))
    ex = [r["ticker"] for r in res["near_misses"] if r["open"] == ["earnings"]]
    if ex:
        lines.append("Esclusi per utili: " + ", ".join(ex))
    jf = res.get("jeff")
    if jf:                     # [JEFF] universo, gate e PEG di Jeff
        lines.append(f"Jeff: universo {jf['universe']} titoli (fuori {jf['out_universe']}); candidati long di Martin "
                     f"{jf['candidates_long']}, con gli 8 gate chiusi {jf['gates_closed']}")
        if jf.get("held_by_gates"):
            lines.append("Fermati dai gate di Jeff (in tracking): " + "; ".join(
                f"{t} ({w})" for t, w in list(jf["held_by_gates"].items())[:20]))
        if jf.get("earnings_out"):
            lo, hi = jf["earnings_window"]
            lines.append(f"Fuori per utili {lo}..{hi}: " + ", ".join(f"{t} {d}" for t, d in sorted(jf["earnings_out"].items())))
        if jf.get("ma1h_missing"):
            lines.append("EMA50 a 1 ora non calcolata (gate 5 aperto): " + ", ".join(jf["ma1h_missing"][:20]))
    pw = res.get("peg_watch") or []
    if pw:
        lines.append(f"PEG delayed reaction ({len(pw)}): " + "; ".join(
            f"{p['ticker']} (utili {p['peg_date'][5:]} +{p['peg_gap_pct']:.0f}%, pivot {p['peg_pivot']}"
            + (f", livello {p['level']}" if p.get("tradable") else ", senza livello: niente alert")
            + (", contro il regime" if p.get("counter") else "") + ")" for p in pw))
    return "\n".join(lines) + "\n"


def themes_md(res: dict) -> str:
    out = [f"# Temi {res['session']} (close {res['as_of']})", "",
           "| # | Tema | Fonte | Fase | Punteggio | Var. rango 5gg | Leading | RS21 med. | Tenuta giorni rossi | Negli scan | ETF | Membri |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["themes"]:
        out.append(f"| {r['rank']} | {r['theme']} | {r.get('source', '')} | {r['phase']} | {r['score']:.0f} | {r.get('rank_change') if r.get('rank_change') is not None else '-'} | "
                   f"{r['lead']:.0%} | {r['rs21'] if r['rs21'] is not None else '-'} | {r['red_rs'] if r['red_rs'] is not None else '-'} | "
                   f"{r['scans5']} | {', '.join(r.get('etfs') or []) or '-'} | {', '.join(r['members'][:8])} |")
    props = res.get("theme_proposals") or []
    if props:
        out += ["", "## Proposte (titoli senza tema che si muovono con un tema, 60 sedute)", "",
                "Da approvare: per accettarne una aggiungila in `data/themes/manuale.json` sotto \"aggiungi\".", "",
                "| Titolo | Tema proposto | Correlazione |", "|---|---|---|"]
        out += [f"| {p['ticker']} | {p['theme']} | {p['corr']:.2f} |" for p in props]
    ch = res.get("theme_map_changes") or {}
    if ch.get("added") or ch.get("removed"):
        out += ["", f"## Mappa aggiornata ({(res.get('theme_map_built') or '')[:10]})", "",
                f"Entrati: {', '.join(ch.get('added') or []) or '-'}", "", f"Usciti: {', '.join(ch.get('removed') or []) or '-'}"]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-cache", action="store_true")
    ap.add_argument("--skip-if-done", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = date.fromisoformat(a.session) if a.session else today_rome()
    if not is_session(session):
        print(json.dumps({"skipped": True, "reason": "borsa chiusa"}))
        return 0
    if a.skip_if_done and (C.LISTS / f"{session}.json").exists():
        print(json.dumps({"skipped": True, "reason": "lista già fatta"}))
        return 0
    work = C.LISTS / f"work_{session}"
    doc = compute(session, work, a.from_cache)
    rv_p = work / "review.json"
    review = json.loads(rv_p.read_text(encoding="utf-8")) if rv_p.exists() else {}
    res = build(doc, review)
    lh = (res.get("martin_pool") or {}).pop("lists_hist", None)     # liste in % nel grafico, non nel json [27/10]
    png = BC.render(res.pop("mm_hist_full", None) or [], C.PB_UP20_CAUTION, C.PB_DOWN20_CAUTION,
                    (C.PB_T2108_EXTREME, C.PB_T2108_OVERSOLD, C.PB_T2108_EXTENDED),
                    lists_hist=lh if C.LISTS_CHART else None, universe=C.LISTS_CHART_UNIVERSE)
    if png:                                         # allegato della card [RONIN 16/10]
        work.mkdir(parents=True, exist_ok=True)
        (work / "breadth.png").write_bytes(png)
        res["breadth_chart"] = "breadth.png"
    tm = res.get("themes_msg") or {}
    if C.THEME_RS_CHART and tm.get("points"):     # mappa dei temi: RS settimana/mese e mese/trimestre [RONIN 21/10]
        try:
            from . import rs_chart as RC
            pngs = RC.render_all(tm["points"], subtitle=f"{res['session']} · close {res['as_of']} · {len(tm['points'])} groups")
        except Exception as e:
            log.warning("grafici RS dei temi: %s", e)
            pngs = {}
        work.mkdir(parents=True, exist_ok=True)
        for fn, png in pngs.items():
            (work / fn).write_bytes(png)
        res["themes_charts"] = list(pngs)
    if C.CARD_FOCUS_CHARTS:         # grafici dei Focus nella card, solo il titolo [ANDREA 28/10, multi-edge]
        from . import chart as CH
        work.mkdir(parents=True, exist_ok=True)
        try:
            pegc = [r for r in res.get("peg_watch") or [] if r.get("tradable") and not r.get("also_focus")]   # [JEFF]
            res["focus_charts"] = CH.focus_charts(res["focus"] + (res.get("counter_focus") or []) + pegc, session,
                                                  date.fromisoformat(str(res["as_of"])), work)
        except Exception as e:
            log.warning("grafici dei Focus: %s", e)
    pm_p = work / "premarket.json"
    pm = json.loads(pm_p.read_text(encoding="utf-8")) if pm_p.exists() else None
    card = {"embeds": card_embeds(res, pm)}
    pegs = res.get("peg_watch") or []                                                                 # [JEFF]
    exch = {s: (doc["uni"].get(s) or {}).get("exchange") for s in res["tracking"] + [r["ticker"] for r in res["focus"] + res["counter_focus"] + pegs]}
    fx = lambda side: [(r["ticker"], exch.get(r["ticker"])) for r in res["focus"] if r["side"] == side]
    tx = lambda key: [(t, exch.get(t)) for t in res[key]]
    ax = lambda side: [(r["ticker"], exch.get(r["ticker"])) for r in res["counter_focus"] if r["side"] == side]
    txt = tv_txt([("FOCUS LONG", fx("long")), ("FOCUS SHORT", fx("short")),
                  ("TOP QUALITY LONG", ax("long")), ("TOP QUALITY SHORT", ax("short")),
                  ("PEG", [(r["ticker"], exch.get(r["ticker"])) for r in pegs]),                         # [JEFF]
                  ("TRACKING LONG", tx("tracking_long")), ("TRACKING SHORT", tx("tracking_short"))])
    public = {k: res[k] for k in ("session", "as_of", "rules_version", "bias", "bias_score", "score_bias", "risk_pct", "bias_why", "market_monitor", "indices",
                                  "qqq_prev_close", "qqq_ctx", "focus", "counter_focus", "fakeout_watch", "sync_levels", "tracking", "tracking_long", "tracking_short", "themes_line", "breadth")}
    public["session_date"] = res["session"]
    if C.JEFF:                 # [JEFF] i PEG con il livello li segue anche il servizio degli alert
        public["peg_watch"] = pegs
    detail = {k: v for k, v in res.items() if k != "lists"}
    out = work if a.dry_run else C.LISTS
    write_atomic(work / "detail.json", detail)
    write_atomic(work / "card.json", card)
    write_atomic(work / "themes_card.json", {"embeds": themes_embeds(res)})
    write_atomic(work / "summary_it.md", summary_it(res), as_json=False)
    write_atomic(out / f"watchlist_{session}.txt", txt, as_json=False)
    for fn in ("today.json", f"{session}.json"):
        write_atomic(out / fn, public)
    if not a.dry_run and not a.from_cache and C.WRITE_HISTORY:     # [JEFF] istanza a sé: lo storico lo scrive lei (in Martin l'istanza multi-edge legge quello di Dua)
        write_atomic(C.HISTORY / f"lists_{res['as_of']}.json", res["lists"])
        write_atomic(C.HISTORY / f"potent_{res['as_of']}.json", res["potent"])
        write_atomic(C.HISTORY / f"themes_{res['as_of']}.json", {r["theme"]: r["rank"] for r in res["themes"]})
        write_atomic(C.REPORTS / f"temi_{session}.md", themes_md(res), as_json=False)
    print(json.dumps({"session": res["session"], "bias": res["bias"], "focus": [r["ticker"] for r in res["focus"]],
                      "tracking": len(res["tracking"]), "candidates": len(res["candidates"]),
                      **({"peg": [r["ticker"] for r in pegs]} if C.JEFF else {})}))                          # [JEFF]
    return 0


if __name__ == "__main__":
    sys.exit(main())
