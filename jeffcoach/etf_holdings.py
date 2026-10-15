"""Partecipazioni COMPLETE degli ETF tematici [RONIN 15/10, Andrea: "se assegni gli altri a muzzo non ha senso"].

Fonte: i modelli N-PORT che ogni ETF registrato deposita alla SEC (EDGAR, gratis, stesso formato per tutti gli
emittenti): tutte le posizioni, non solo le prime 10. Il CUSIP di ogni posizione si traduce in ticker USA con
OpenFIGI (gratis; chiave facoltativa in OPENFIGI_API_KEY) e la traduzione resta in cache
(data/themes/cusip_ticker.json), quindi dalla seconda settimana servono pochissime richieste.
Gli ETF che non depositano l'N-PORT (trust su materie prime o bitcoin: GLD, SLV, IBIT...) non hanno azioni:
per quelli, e per ogni ETF che dà errore, resta la fonte di riserva (prime partecipazioni dal repo di NEL).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from typing import Optional

from . import config as C

log = logging.getLogger("jeffcoach.etf_holdings")

SEC_UA = os.environ.get("SEC_USER_AGENT", "JeffCoach/1.0 research bot")
MF_INDEX_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SERIES_FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sid}&type=NPORT-P&count=5&output=atom"
FIGI_URL = "https://api.openfigi.com/v3/mapping"
CUSIP_FILE = C.HOME / "themes" / "cusip_ticker.json"
TICKER_RE = re.compile(r"[A-Z][A-Z0-9\-]{0,6}")


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    data = urllib.request.urlopen(req, timeout=timeout).read()
    time.sleep(0.15)                                  # SEC: massimo 10 richieste al secondo
    return data


def series_index() -> dict[str, str]:
    """{ticker ETF: seriesId SEC}."""
    d = json.loads(_get(MF_INDEX_URL))
    f = d["fields"]
    i_s, i_t = f.index("seriesId"), f.index("symbol")
    return {r[i_t].upper(): r[i_s] for r in d["data"] if r[i_t] and r[i_s]}


def latest_nport(series_id: str) -> Optional[str]:
    """XML dell'ultimo N-PORT pubblico della serie, o None."""
    feed = _get(SERIES_FEED.format(sid=series_id)).decode("utf-8", "ignore")
    m = re.search(r"<filing-href>([^<]+)</filing-href>", feed)
    if not m:
        return None
    return _get(m.group(1).rsplit("/", 1)[0] + "/primary_doc.xml").decode("utf-8", "ignore")


def parse_nport(xml: str) -> list[dict]:
    """Posizioni azionarie lunghe: [{cusip, isin, name, weight (frazione)}]."""
    out = []
    for sec in re.findall(r"<invstOrSec>(.*?)</invstOrSec>", xml, re.S):
        def tag(t):
            m = re.search(rf"<{t}>([^<]*)</{t}>", sec)
            return m.group(1).strip() if m else ""
        if tag("assetCat") != "EC" or tag("payoffProfile") not in ("Long", ""):
            continue
        isin = re.search(r'<isin value="([^"]+)"', sec)
        try:
            w = float(tag("pctVal") or 0) / 100
        except ValueError:
            w = 0.0
        cusip = tag("cusip")
        out.append({"cusip": cusip if re.fullmatch(r"[0-9A-Z]{9}", cusip or "") else "",
                    "isin": isin.group(1) if isin else "", "name": tag("name"), "weight": w})
    return out


def _load_cache() -> dict[str, Optional[str]]:
    try:
        return json.loads(CUSIP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CUSIP_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CUSIP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(cache.items())), indent=0), encoding="utf-8")
    tmp.replace(CUSIP_FILE)


def map_ids(ids: list[str], cache: dict, budget_s: float = 1500) -> None:
    """Traduce CUSIP/ISIN in ticker USA (OpenFIGI) e aggiorna la cache; None = nessun titolo quotato in USA."""
    key = os.environ.get("OPENFIGI_API_KEY")
    batch, pause = (100, 0.25) if key else (10, 2.5)          # limiti OpenFIGI con e senza chiave
    todo = [i for i in dict.fromkeys(ids) if i and i not in cache]
    t0 = time.time()
    for k in range(0, len(todo), batch):
        if time.time() - t0 > budget_s:
            log.warning("OpenFIGI: tempo finito, %d identificativi rimandati alla prossima volta", len(todo) - k)
            break
        chunk = todo[k:k + batch]
        jobs = [{"idType": "ID_ISIN" if len(i) == 12 else "ID_CUSIP", "idValue": i, "exchCode": "US"} for i in chunk]
        headers = {"Content-Type": "application/json"}
        if key:
            headers["X-OPENFIGI-APIKEY"] = key
        req = urllib.request.Request(FIGI_URL, data=json.dumps(jobs).encode(), headers=headers, method="POST")
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(60)
                continue
            raise
        for i, r in zip(chunk, res):
            t = None
            for d in r.get("data") or []:
                if d.get("marketSector") == "Equity" and d.get("ticker"):
                    t = d["ticker"].replace("/", "-").replace(".", "-").upper()
                    break
            cache[i] = t if t and TICKER_RE.fullmatch(t) else None
        time.sleep(pause)


def fetch_full(etfs: list[str], fallback: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], dict]:
    """{ETF: [{symbol, weight}]} con le partecipazioni complete; riserva = `fallback` (NEL) ETF per ETF."""
    idx = series_index()
    raw: dict[str, list[dict]] = {}
    for e in etfs:
        sid = idx.get(e.upper())
        if not sid:
            continue
        try:
            xml = latest_nport(sid)
            if xml:
                raw[e] = parse_nport(xml)
        except Exception as ex:
            log.warning("N-PORT %s: %s", e, ex)
    cache = _load_cache()
    ids = [h["cusip"] or h["isin"] for v in raw.values() for h in v]
    try:
        map_ids(ids, cache)
    finally:
        _save_cache(cache)
    out, stats = {}, {"nport": [], "fallback": [], "none": []}
    for e in etfs:
        rows = raw.get(e)
        if rows:
            agg: dict[str, float] = {}
            for h in rows:
                t = cache.get(h["cusip"] or h["isin"])
                if t:
                    agg[t] = agg.get(t, 0.0) + h["weight"]
            if agg:
                out[e] = [{"symbol": t, "weight": w} for t, w in sorted(agg.items(), key=lambda x: -x[1])]
                stats["nport"].append(e)
                continue
        if fallback.get(e):
            out[e] = fallback[e]
            stats["fallback"].append(e)
        else:
            stats["none"].append(e)
    return out, stats
