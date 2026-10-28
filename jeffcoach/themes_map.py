"""Mappa dei temi: solo ETF tematici [RONIN 15/10, Andrea: "affidati agli ETF, non scegliere tu"].

Per ogni titolo:
  1. ETF tematici della lista di Andrea (Google Sheet, colonna Group = tema, tutti i gruppi) con le partecipazioni
     COMPLETE dall'N-PORT depositato alla SEC (etf_holdings.py; riserva: prime 10 dal repo pubblico di NEL); il tema è il nome del gruppo così com'è nel foglio (nessuna rinomina, nessun accorpamento);
     tema principale = il gruppo con più ETF che tengono il titolo (a parità: in daily il tema con cui il titolo si
     muove di più, correlazione a 60 sedute con la mediana del tema; riserva il peso più alto), mai un gruppo
     generico (GENERIC_GROUPS: contano solo nella classifica);
     appartenenza solo se l'ETF sovrappesa il titolo rispetto al mercato (config THEME_OVERWEIGHT_*) [RONIN 16/10]:
     le partecipazioni complete mettono le mega cap in quasi tutti i temi (MSFT in Cybersecurity, NVDA in Bitcoin,
     LLY in Genomics) con pesi pari o inferiori al loro peso di mercato; quelle non sono esposizione al tema;
  2. modifiche a mano di Andrea in data/themes/manuale.json ({"aggiungi": {"TICKER": "Tema"}, "togli": {"TICKER": "Tema"}});
  3. (in daily) correlazione: i titoli senza tema che si muovono con un tema diventano PROPOSTE, non entrano da soli.
ETF senza azioni in portafoglio (oro, argento, bitcoin, petrolio, Treasury: GLD, IBIT, USO, TLT...): l'ETF stesso è
membro del suo tema (proxy_etfs) e il tema si misura sul suo prezzo [RONIN 15/10, Andrea].
Niente basket a mano, niente industria Yahoo, niente cluster di correlazione: un titolo che non è in un ETF tematico
resta senza tema. Le fonti si riscaricano una volta a settimana (lunedì o file più vecchio di 6 giorni); se la rete
non risponde si tiene la mappa precedente.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config as C
from . import etf_holdings as EH

log = logging.getLogger("jeffcoach.themes_map")

DIR = C.HOME / "themes"
MAP_FILE = DIR / "mappa.json"
MANUAL_FILE = DIR / "manuale.json"

US_EXCH = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "NYSEARCA", "CBOE", "BATS"}

# gruppi troppo generici per essere un tema (fattori, macro, obbligazioni)
ETF_SKIP: set[str] = set()   # nessun gruppo escluso: tutti i gruppi della lista di Andrea sono temi [RONIN 15/10]
# gruppi generici (fattori, macro, stile): contano nella classifica dei temi ma non sono MAI il tema principale
# di un titolo [RONIN 15/10, Andrea]
GENERIC_GROUPS = {"Growth stocks", "Momentum", "Mega-cap technology", "Innovation", "ESG", "Values-based",
                  "Gender diversity", "Political", "Social sentiment", "Volatility", "Treasury bonds",
                  "AI-resistant assets", "Sustainable economy", "Private technology", "Climate", "Natural resources",
                  "Consumer discretionary", "Consumer staples", "Latin America", "Digital economy", "Metals & mining",
                  "Crude oil", "Platinum", "Palladium", "Carbon credits", "China", "South Korea", "Financial services",
                  "Retail", "Meme stocks", "Internet", "Metaverse"}


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JeffCoach)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def yahoo(sym: str) -> str:
    return sym.replace(".", "-").upper()


def title(name: str) -> str:
    """Nome leggibile: 'OPTICAL NETWORKING' -> 'Optical Networking' (sigle corte restano maiuscole)."""
    words = []
    for w in name.split():
        words.append(w if (len(w) <= 3 and w.isupper() and w not in ("AND", "OIL", "GAS")) or w == "&" else w.capitalize())
    return " ".join(words).replace(" And ", " and ")


# ------------------------------------------------------------------ fonti
def fetch_etf_groups() -> dict[str, str]:
    """ETF tematici della lista di Andrea: {ETF: gruppo}."""
    raw = _get(C.THEME_ETF_SHEET_CSV).decode("utf-8", "ignore")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out = {r["Ticker"].strip().upper(): r["Group"].strip() for r in rows if r.get("Ticker") and r.get("Group")}
    if len(out) < 50:
        raise RuntimeError(f"lista ETF incompleta ({len(out)})")
    return out


def fetch_etf_holdings() -> dict[str, list[dict]]:
    """Prime partecipazioni degli ETF tematici dal repo pubblico di NEL: {ETF: [{symbol, weight}]}.
    Ogni download si archivia in data/themes/etf_holdings_nel.json (nel repo): se NEL sparisce si usa l'archivio."""
    arch = DIR / "etf_holdings_nel.json"
    try:
        d = json.loads(_get(C.THEME_ETF_HOLDINGS_URL))
        funds = d.get("funds") or {}
        out = {k.upper(): [h for h in (v or []) if h.get("symbol")] for k, v in funds.items()}
        if len(out) < 20:
            raise RuntimeError(f"file NEL incompleto ({len(out)} ETF)")
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = arch.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        tmp.replace(arch)
        return out
    except Exception as e:
        if arch.exists():
            log.warning("partecipazioni NEL non raggiungibili (%s): uso l'archivio", e)
            return json.loads(arch.read_text(encoding="utf-8"))
        raise


# ------------------------------------------------------------------ mappa
def overweight(hits: dict[str, dict[str, list[float]]], mcap: dict[str, float]) -> dict[str, dict[str, float]]:
    """Sovrappeso di ogni titolo in ogni gruppo: peso massimo negli ETF del gruppo / peso di mercato del titolo.
    Titoli senza capitalizzazione (sotto 1 mld, esteri): infinito, un ETF che li tiene li sovrappesa per forza."""
    tot = sum(v for v in mcap.values() if v and v > 0)
    out = {}
    for t, by in hits.items():
        mw = (mcap.get(t) or 0) / tot if tot else 0
        out[t] = {g: (max(ws) / mw if mw > 0 else float("inf")) for g, ws in by.items()}
    return out


def keep_groups(ow: dict[str, float], by: Optional[dict[str, list[float]]] = None, vmin: float = None,
                frac: float = None) -> set[str]:
    """Temi specifici in cui il titolo resta: sovrappeso >= vmin e >= frac del suo sovrappeso massimo. Se nessuno
    passa (mega cap, presenti ovunque ma sovrappesate da nessuno) resta il tema principale di prima: il gruppo con più
    ETF che lo tengono, poi il peso più alto (`by` = pesi per gruppo). I gruppi generici (fattori, macro: Momentum,
    Mega-cap technology...) non passano da qui: tengono tutti i titoli dei loro ETF e non sono mai il tema principale."""
    vmin = C.THEME_OVERWEIGHT_MIN if vmin is None else vmin
    frac = C.THEME_OVERWEIGHT_FRAC if frac is None else frac
    spec = {g: v for g, v in ow.items() if g not in GENERIC_GROUPS}
    if not spec:
        return set()
    mx = max(spec.values())
    keep = {g for g, v in spec.items() if v >= vmin and v >= mx * frac}
    if not keep:
        by = by or {g: [v] for g, v in spec.items()}
        keep = {min(spec, key=lambda g: (-len(by.get(g, [])), -max(by.get(g, [0])), g))}
    return keep


def build_map(etf_groups: dict[str, str], holdings: dict[str, list[dict]], manual: Optional[dict] = None,
              mcap: Optional[dict[str, float]] = None) -> dict:
    """{ticker: {"primary": tema, "themes": [..], "source": etf|manuale}}, i temi con la fonte e gli ETF di ogni tema.
    Con `mcap` ({ticker: capitalizzazione}) un titolo resta solo nei temi che lo sovrappesano (keep_groups)."""
    themes: dict[str, set[str]] = {}
    source: dict[str, str] = {}
    prim: dict[str, tuple] = {}
    theme_etfs: dict[str, list[str]] = {}
    hits: dict[str, dict[str, list[float]]] = {}
    ties: dict[str, list[str]] = {}
    for etf, group in etf_groups.items():
        if group in ETF_SKIP:
            continue
        theme_etfs.setdefault(group, []).append(etf)
        for h in holdings.get(etf, []):
            t = yahoo(h["symbol"])
            if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,6}", t):
                continue
            themes.setdefault(t, set()).add(group)
            source.setdefault(t, "etf")
            hits.setdefault(t, {}).setdefault(group, []).append(h.get("weight") or 0)
    ows = overweight(hits, mcap) if mcap else {}
    if mcap:
        for t in list(hits):
            kept = keep_groups(ows[t], hits[t]) | {g for g in hits[t] if g in GENERIC_GROUPS}
            hits[t] = {g: w for g, w in hits[t].items() if g in kept}
            themes[t] = set(hits[t])
    for t, by in hits.items():               # principale: il gruppo con più ETF che lo tengono, poi il peso più alto
        specific = [k for k in by if k not in GENERIC_GROUPS]          # mai un gruppo generico
        prim[t] = ((1, 0), min(specific, key=lambda k: (-len(by[k]), -max(by[k]), k)) if specific else None)
        if specific:                         # pari merito sul numero di ETF: in daily decide l'andamento del titolo
            top = max(len(by[k]) for k in specific)
            tied = sorted(k for k in specific if len(by[k]) == top)
            if len(tied) > 1:
                ties[t] = tied
    for t, th in ((manual or {}).get("aggiungi") or {}).items():
        t = yahoo(t)
        themes.setdefault(t, set()).add(th)
        prim[t] = ((-1, 0), th)
        source[t] = "manuale"
    for t, th in ((manual or {}).get("togli") or {}).items():
        t = yahoo(t)
        if t in themes:
            themes[t].discard(th)
            if prim.get(t, (None, None))[1] == th:
                prim.pop(t, None)
                rest = sorted(x for x in themes[t] if x not in GENERIC_GROUPS)
                if rest:
                    prim[t] = ((2, 0), rest[0])
            if not themes[t]:
                themes.pop(t)
    tickers = {t: {"primary": prim.get(t, (None, None))[1], "themes": sorted(themes[t]), "source": source.get(t, "?")}
               for t in themes}
    for t, ow in ows.items():                # sovrappeso dei temi tenuti (si vede perché un titolo è in un tema)
        if t in tickers:
            tickers[t]["ow"] = {g: (round(v, 1) if v != float("inf") else None) for g, v in ow.items() if g in themes.get(t, ()) and g not in GENERIC_GROUPS}
    for t, tied in ties.items():
        if t in tickers and tickers[t]["source"] == "etf":
            tickers[t]["tied"] = tied
    origin = {g: "etf" for g in theme_etfs}
    for th in ((manual or {}).get("aggiungi") or {}).values():
        origin.setdefault(th, "manuale")
    return {"tickers": tickers, "themes": origin, "theme_etfs": theme_etfs}


def market_caps() -> dict[str, float]:
    """Capitalizzazioni dall'universo Yahoo (data.build_universe, rinnovato ogni settimana); {} se manca."""
    try:
        from . import data as D
        return {k: v.get("mcap") or 0 for k, v in D.build_universe().items()}
    except Exception as e:
        log.warning("temi: capitalizzazioni non disponibili (%s): appartenenza senza filtro di sovrappeso", e)
        return {}


def load_manual() -> dict:
    try:
        return json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ------------------------------------------------------------------ basket di Lone Stock Trader [RONIN 21/10]
def build_lst_map(baskets: dict[str, list[str]], manual: Optional[dict] = None) -> dict:
    """Mappa dai basket di Lone Stock Trader [RONIN 21/10, Andrea: "per tutti i gruppi prendili da questo sito"].
    Ogni basket è un tema col suo nome del sito; un titolo sta in tutti i basket che lo contengono (ETF compresi:
    COPX, XHB, IGV... sono membri come gli altri). Tema principale = il basket più piccolo che lo contiene (il più
    specifico); a pari dimensione decide in daily l'andamento (correlazione con la mediana del basket).
    Le modifiche a mano di data/themes/manuale.json valgono come prima."""
    themes: dict[str, set[str]] = {}
    for b, mem in baskets.items():
        for t in mem:
            themes.setdefault(yahoo(t), set()).add(b)
    size = {b: len(set(v)) for b, v in baskets.items()}
    prim: dict[str, Optional[str]] = {}
    ties: dict[str, list[str]] = {}
    source = {t: "lst" for t in themes}
    for t, bs in themes.items():
        small = min(size[b] for b in bs)
        tied = sorted(b for b in bs if size[b] == small)
        prim[t] = tied[0]
        if len(tied) > 1:
            ties[t] = tied
    for t, th in ((manual or {}).get("aggiungi") or {}).items():
        t = yahoo(t)
        themes.setdefault(t, set()).add(th)
        prim[t], source[t] = th, "manuale"
        ties.pop(t, None)
    for t, th in ((manual or {}).get("togli") or {}).items():
        t = yahoo(t)
        if t in themes:
            themes[t].discard(th)
            if prim.get(t) == th:
                rest = sorted(themes[t], key=lambda b: (size.get(b, 999), b))
                prim[t] = rest[0] if rest else None
            if not themes[t]:
                themes.pop(t)
    tickers = {t: {"primary": prim.get(t), "themes": sorted(th), "source": source.get(t, "lst")} for t, th in themes.items()}
    for t, tied in ties.items():
        if t in tickers and tickers[t]["source"] == "lst":
            tickers[t]["tied"] = tied
    members = {b: [yahoo(t) for t in v] for b, v in baskets.items()}
    for t, th in ((manual or {}).get("aggiungi") or {}).items():
        members.setdefault(th, [])
        if yahoo(t) not in members[th]:
            members[th].append(yahoo(t))
    for t, th in ((manual or {}).get("togli") or {}).items():
        if th in members and yahoo(t) in members[th]:
            members[th].remove(yahoo(t))
    origin = {b: "lst" for b in baskets}
    for th in ((manual or {}).get("aggiungi") or {}).values():
        origin.setdefault(th, "manuale")
    return {"tickers": tickers, "themes": origin, "theme_etfs": {}, "baskets": members}


def refresh_lst() -> dict:
    """Mappa dai basket LST salvati nel repo (data/themes/lst_baskets.json, aggiornati il lunedì alle 01:00 da
    lst_baskets.py sul server). Si ricostruisce quando cambia il file dei basket o il file manuale."""
    from . import lst_baskets as LB
    src = LB.load()
    old = None
    if MAP_FILE.exists():
        try:
            old = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        except ValueError:
            old = None
    if not src or not src.get("baskets"):
        if old and old.get("membership") == "lst":
            log.warning("temi: file dei basket LST mancante, tengo la mappa del %s", (old.get("built_utc") or "")[:10])
            return old
        raise RuntimeError("nessun file dei basket LST (data/themes/lst_baskets.json)")
    manual = load_manual()
    mh = json.dumps(manual, sort_keys=True)
    if old and old.get("membership") == "lst" and old.get("baskets_fetched_utc") == src["fetched_utc"] \
            and old.get("manual_hash") == mh:
        return old
    m = build_lst_map(src["baskets"], manual)
    doc = {"built_utc": datetime.now(timezone.utc).isoformat(), "membership": "lst", "manual_hash": mh,
           "sources": {"baskets": src.get("source")}, "baskets_fetched_utc": src["fetched_utc"],
           "basket_changes": src.get("changes"), **m}
    if old:
        o, n = set(old.get("tickers", {})), set(m["tickers"])
        doc["changes"] = {"added": sorted(n - o)[:200], "removed": sorted(o - n)[:200]}
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MAP_FILE)
    if not MANUAL_FILE.exists():
        MANUAL_FILE.write_text(json.dumps({"aggiungi": {}, "togli": {}}, indent=1), encoding="utf-8")
    log.info("temi: %d titoli in %d basket LST (basket del %s)", len(m["tickers"]), len(m["themes"]), src["fetched_utc"][:10])
    return doc


def refresh(force: bool = False) -> dict:
    """Mappa aggiornata. Dal 21/10 i temi sono i basket di Lone Stock Trader (C.THEME_SOURCE = "lst"); con "etf" la
    vecchia mappa dagli ETF tematici: si riscaricano le fonti il lunedì o se la mappa ha più di 6 giorni."""
    if getattr(C, "THEME_SOURCE", "etf") == "lst":
        return refresh_lst()
    old = None
    if MAP_FILE.exists():
        old = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(old["built_utc"])
        monday = datetime.now(timezone.utc).weekday() == 0 and age > timedelta(hours=20)
        same_rule = old.get("membership") == C.THEME_MEMBERSHIP
        if not force and age < timedelta(days=6) and not monday and old.get("holdings_source", {}).get("nport") and same_rule:   # mappa vecchia (basket o solo top 10): si rifà
            return old
    try:
        etf_groups = fetch_etf_groups()
        try:
            nel = fetch_etf_holdings()                    # riserva: prime 10 partecipazioni (repo di NEL)
        except Exception as e:
            log.warning("temi: partecipazioni NEL non raggiungibili (%s)", e)
            nel = {}
        try:
            holdings, hstats = EH.fetch_full(sorted(etf_groups), nel)   # partecipazioni complete (SEC N-PORT)
        except Exception as e:
            log.warning("temi: N-PORT non raggiungibile (%s), solo le prime 10 di NEL", e)
            holdings, hstats = nel, {"nport": [], "fallback": sorted(nel), "none": []}
        if not holdings:
            raise RuntimeError("nessuna partecipazione ETF")
    except Exception as e:
        if old and "theme_etfs" in old:
            log.warning("temi: fonti non raggiungibili (%s), tengo la mappa del %s", e, old["built_utc"][:10])
            return old
        log.warning("temi: fonti non raggiungibili (%s) e nessuna mappa ETF salvata: nessun tema", e)
        return {"built_utc": None, "tickers": {}, "themes": {}, "theme_etfs": {}}
    mc = market_caps()
    m = build_map(etf_groups, holdings, load_manual(), mc)
    doc = {"built_utc": datetime.now(timezone.utc).isoformat(), "sources": {
        "etf_list": C.THEME_ETF_SHEET_CSV, "etf_holdings": "SEC N-PORT + OpenFIGI", "etf_holdings_fallback": C.THEME_ETF_HOLDINGS_URL},
        "n_etf": len(etf_groups), "membership": C.THEME_MEMBERSHIP if mc else None, "holdings_source": {k: len(v) for k, v in hstats.items()}, "holdings_fallback": hstats["fallback"], "holdings_none": hstats["none"], "proxy_etfs": {g: [e for e in es if e in hstats["none"]] for g, es in m["theme_etfs"].items() if any(e in hstats["none"] for e in es)}, **m}
    if old:                                 # cosa è cambiato rispetto alla settimana prima (va nel riepilogo)
        o, n = set(old.get("tickers", {})), set(m["tickers"])
        doc["changes"] = {"added": sorted(n - o)[:200], "removed": sorted(o - n)[:200]}
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MAP_FILE)
    if not MANUAL_FILE.exists():
        MANUAL_FILE.write_text(json.dumps({"aggiungi": {}, "togli": {}}, indent=1), encoding="utf-8")
    log.info("temi: %d titoli in %d temi (%d ETF)", len(m["tickers"]), len(m["themes"]), len(etf_groups))
    return doc


def groups_from_map(doc: dict, universe: set[str]) -> dict[str, list[str]]:
    """{tema: [titoli dell'universo]} — un titolo può stare in più temi."""
    out: dict[str, list[str]] = {}
    for t, r in (doc.get("tickers") or {}).items():
        if t in universe:
            for th in r["themes"]:
                out.setdefault(th, []).append(t)
    return out
