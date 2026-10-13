"""Mappa dei temi a livelli [RONIN 13/10] — la stessa di Martin-coach (copiata da martincoach/themes_map.py).

Per ogni titolo, in ordine di priorità:
  1. basket della watchlist pubblica "🐭Baskets" su TradingView (temi scelti a mano, ~50); tema principale = il basket
     più piccolo che lo contiene (il più specifico);
  2. ETF tematici (lista di Andrea, Google Sheet) con le prime partecipazioni prese dal repo pubblico di NEL;
     ogni gruppo ETF è collegato al basket corrispondente (ETF_TO_BASKET) o diventa un tema a sé;
  3. modifiche a mano in data/themes/manuale.json ({"aggiungi": {"TICKER": "Tema"}, "togli": {"TICKER": "Tema"}});
  4. (in daily) correlazione: i titoli senza tema che si muovono con un basket diventano PROPOSTE, non entrano da soli;
  5. industria Yahoo come riserva.
Le fonti si riscaricano una volta a settimana (lunedì o file più vecchio di 6 giorni); se la rete non risponde
si tiene la mappa precedente.
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

log = logging.getLogger("jeffcoach.themes_map")

DIR = C.STATE / "themes"
MAP_FILE = DIR / "mappa.json"
MANUAL_FILE = DIR / "manuale.json"

US_EXCH = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "NYSEARCA", "CBOE", "BATS"}

# nomi dei basket ripuliti (refusi e caratteri invisibili della watchlist originale)
BASKET_NAME_FIX = {"SEMICONDUTORS": "SEMICONDUCTORS", "FINACE": "FINANCE", "ELECTRIFICATION-RENOWABLES": "ELECTRIFICATION & RENEWABLES",
                   "BRASIL": "BRAZIL"}

# gruppo ETF -> basket; i gruppi non elencati diventano temi a sé; SKIP = gruppi troppo generici per essere un tema
ETF_TO_BASKET = {
    "Space": "SPACE", "Defense": "DEFENSE", "Defense technology": "DEFENSE", "Semiconductors": "SEMICONDUCTORS",
    "Memory": "MEMORIES", "Photonics": "OPTICAL NETWORKING", "Data centers": "DATACENTER", "Neocloud": "DATACENTER",
    "Digital infrastructure": "DATACENTER", "Software": "SOFTWARE", "Cloud": "SOFTWARE", "Cybersecurity": "CYBERSECURITY",
    "Fintech": "FINANCE", "Payments": "FINANCE", "Quantum computing": "QUANTUM COMPUTING", "Cryptocurrency": "CRYPTO",
    "Bitcoin": "CRYPTO", "Blockchain": "CRYPTO", "Ethereum": "CRYPTO", "Electric vehicles": "EV",
    "Electrical grid": "ELECTRIFICATION & RENEWABLES", "Clean energy": "ELECTRIFICATION & RENEWABLES",
    "Wind energy": "ELECTRIFICATION & RENEWABLES", "Solar": "SOLAR", "Hydrogen": "FUEL CELLS", "Lithium": "LITHIUM",
    "Nuclear": "NUCLEAR", "Uranium": "NUCLEAR", "Strategic metals": "RARE EARTHS", "Gold": "GOLD", "Gold miners": "GOLD",
    "Silver": "SILVER", "Silver miners": "SILVER", "Copper": "COPPER", "Steel": "STEEL", "Shipping": "MARINE SHIPPING",
    "Logistics": "LOGISTICS", "Transportation": "LOGISTICS", "Oil services": "OIL AND GAS EQUIPMENT AND SERVICES",
    "Natural gas": "OIL AND GAS UPSTREAM", "Energy infrastructure": "OIL AND GAS MIDSTREAM",
    "Brazil": "BRAZIL", "Argentina": "ARGENTINA", "Infrastructure": "CONSTRUCTION & ENGINEERING", "Healthcare": "HEALTHCARE",
}
ETF_SKIP = {"Growth stocks", "Momentum", "Mega-cap technology", "Innovation", "ESG", "Values-based", "Gender diversity",
            "Political", "Social sentiment", "Volatility", "Treasury bonds", "AI-resistant assets", "Sustainable economy",
            "Private technology", "Climate", "Natural resources", "Consumer discretionary", "Consumer staples",
            "Latin America", "Digital economy", "Metals & mining", "Crude oil", "Platinum", "Palladium", "Carbon credits",
            "China", "South Korea", "Financial services", "Retail", "Meme stocks", "Internet", "Metaverse"}


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
def fetch_baskets() -> dict[str, list[str]]:
    """Basket della watchlist pubblica di TradingView: {nome: [ticker USA]}."""
    html = _get(C.THEME_BASKETS_URL).decode("utf-8", "ignore")
    i = html.index('"symbols":[')
    arr = json.loads(html[i + len('"symbols":'):html.index("]", i) + 1])
    out: dict[str, list[str]] = {}
    cur = None
    for x in arr:
        if x.startswith("###"):
            name = re.sub(r"[^\w&\- ]", "", x[3:]).strip().upper()
            cur = BASKET_NAME_FIX.get(name, name)
            out.setdefault(cur, [])
        elif cur and ":" in x:
            ex, t = x.split(":", 1)
            if ex.upper() in US_EXCH:
                out[cur].append(yahoo(t))
    if sum(len(v) for v in out.values()) < 100:
        raise RuntimeError(f"watchlist basket incompleta ({sum(len(v) for v in out.values())} titoli)")
    return out


def fetch_etf_groups() -> dict[str, str]:
    """ETF tematici della lista di Andrea: {ETF: gruppo}."""
    raw = _get(C.THEME_ETF_SHEET_CSV).decode("utf-8", "ignore")
    rows = list(csv.DictReader(io.StringIO(raw)))
    out = {r["Ticker"].strip().upper(): r["Group"].strip() for r in rows if r.get("Ticker") and r.get("Group")}
    if len(out) < 50:
        raise RuntimeError(f"lista ETF incompleta ({len(out)})")
    return out


def fetch_etf_holdings() -> dict[str, list[dict]]:
    """Prime partecipazioni degli ETF tematici dal repo pubblico di NEL: {ETF: [{symbol, weight}]}."""
    d = json.loads(_get(C.THEME_ETF_HOLDINGS_URL))
    funds = d.get("funds") or {}
    return {k.upper(): [h for h in (v or []) if h.get("symbol")] for k, v in funds.items()}


# ------------------------------------------------------------------ mappa
def build_map(baskets: dict[str, list[str]], etf_groups: dict[str, str], holdings: dict[str, list[dict]],
              manual: Optional[dict] = None) -> dict:
    """{ticker: {"primary": tema, "themes": [..], "source": basket|etf|manuale}} + elenco dei temi con la fonte."""
    themes: dict[str, set[str]] = {}
    source: dict[str, str] = {}
    size = {title(b): len(v) for b, v in baskets.items()}
    prim: dict[str, tuple] = {}
    for b, members in baskets.items():
        tb = title(b)
        for t in members:
            themes.setdefault(t, set()).add(tb)
            source.setdefault(t, "basket")
            key = (0, size[tb])
            if t not in prim or key < prim[t][0]:
                prim[t] = (key, tb)
    for etf, group in etf_groups.items():
        if group in ETF_SKIP:
            continue
        tb = title(ETF_TO_BASKET[group]) if group in ETF_TO_BASKET else group
        for h in holdings.get(etf, []):
            t = yahoo(h["symbol"])
            if not re.fullmatch(r"[A-Z][A-Z0-9\-]{0,6}", t):
                continue
            themes.setdefault(t, set()).add(tb)
            source.setdefault(t, "etf")
            key = (1, -(h.get("weight") or 0))
            if t not in prim or key < prim[t][0]:
                prim[t] = (key, tb)
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
                if themes[t]:
                    prim[t] = ((2, 0), sorted(themes[t])[0])
            if not themes[t]:
                themes.pop(t)
    tickers = {t: {"primary": prim[t][1], "themes": sorted(themes[t]), "source": source.get(t, "?")}
               for t in themes if t in prim}
    origin = {title(b): "basket" for b in baskets}
    for g in etf_groups.values():
        if g not in ETF_SKIP:
            origin.setdefault(title(ETF_TO_BASKET[g]) if g in ETF_TO_BASKET else g, "etf")
    return {"tickers": tickers, "themes": origin}


def load_manual() -> dict:
    try:
        return json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def refresh(force: bool = False) -> dict:
    """Mappa aggiornata: si riscaricano le fonti il lunedì o se la mappa ha più di 6 giorni; altrimenti quella salvata."""
    old = None
    if MAP_FILE.exists():
        old = json.loads(MAP_FILE.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(old["built_utc"])
        monday = datetime.now(timezone.utc).weekday() == 0 and age > timedelta(hours=20)
        if not force and age < timedelta(days=6) and not monday:
            return old
    try:
        baskets = fetch_baskets()
        etf_groups = fetch_etf_groups()
        holdings = fetch_etf_holdings()
    except Exception as e:
        if old:
            log.warning("temi: fonti non raggiungibili (%s), tengo la mappa del %s", e, old["built_utc"][:10])
            return old
        log.warning("temi: fonti non raggiungibili (%s) e nessuna mappa salvata: solo industrie Yahoo", e)
        return {"built_utc": None, "tickers": {}, "themes": {}}
    m = build_map(baskets, etf_groups, holdings, load_manual())
    doc = {"built_utc": datetime.now(timezone.utc).isoformat(), "sources": {
        "baskets": C.THEME_BASKETS_URL, "etf_list": C.THEME_ETF_SHEET_CSV, "etf_holdings": C.THEME_ETF_HOLDINGS_URL},
        "n_baskets": len(baskets), "n_etf": len(etf_groups), **m}
    if old:                                 # cosa è cambiato rispetto alla settimana prima (va nel riepilogo)
        o, n = set(old.get("tickers", {})), set(m["tickers"])
        doc["changes"] = {"added": sorted(n - o)[:200], "removed": sorted(o - n)[:200]}
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MAP_FILE)
    if not MANUAL_FILE.exists():
        MANUAL_FILE.write_text(json.dumps({"aggiungi": {}, "togli": {}}, indent=1), encoding="utf-8")
    log.info("temi: %d titoli in %d temi (%d basket, %d ETF)", len(m["tickers"]), len(m["themes"]), len(baskets), len(etf_groups))
    return doc


def groups_from_map(doc: dict, universe: set[str]) -> dict[str, list[str]]:
    """{tema: [titoli dell'universo]} — un titolo può stare in più temi."""
    out: dict[str, list[str]] = {}
    for t, r in (doc.get("tickers") or {}).items():
        if t in universe:
            for th in r["themes"]:
                out.setdefault(th, []).append(t)
    return out
