"""Backup del Market Monitor [RONIN 15/10, Andrea: "se il repo di NEL viene cancellato o reso privato"].

1. Archivio: ogni volta che il file di NEL si scarica, le righe si uniscono a data/breadth/market_monitor_nel.json
   (nel repo, quindi su GitHub): lo storico resta anche se NEL sparisce.
2. Calcolo nostro, stesse definizioni di Stockbee, sui dati giornalieri che la lista scarica già:
   - up4 / down4: titoli a +4% / -4% nel giorno con volume maggiore del giorno prima e ≥ 100.000;
   - ratio5 / ratio10: somma up4 / somma down4 su 5 e 10 sedute;
   - up25q / down25q: +25% / -25% in 65 sedute; t2108: % di titoli sopra la media a 40 sedute.
   Il nostro universo (mcap > 1 mld) è più piccolo di quello di NEL: up4 e down4 si riportano alla scala di NEL
   con il rapporto mediano sulle sedute in comune, e il T2108 con una retta stimata sulle stesse sedute
   e i rapporti 5D/10D con una retta sui logaritmi (data/breadth/calibrazione.json, rifatta ogni volta che NEL
   risponde). Le serie nostre si salvano in
   data/breadth/market_monitor_own.json, così il confronto con NEL resta sempre controllabile.
Se NEL non ha la riga del giorno, il regime usa la riga nostra calibrata (stesse soglie, stessa logica).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger("jeffcoach.breadth")

DIR = C.HOME / "breadth"
NEL_FILE = DIR / "market_monitor_nel.json"
OWN_FILE = DIR / "market_monitor_own.json"
CAL_FILE = DIR / "calibrazione.json"
MIN_VOL = 100_000


def _read(p) -> list[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write(p, rows: list[dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def merge(p, rows: list[dict]) -> list[dict]:
    """Unisce `rows` all'archivio per data (le nuove vincono); restituisce l'archivio dalla seduta più recente."""
    by = {r["date"]: r for r in _read(p)}
    for r in rows or []:
        if r.get("date"):
            by[r["date"]] = r
    out = [by[d] for d in sorted(by, reverse=True)]
    _write(p, out)
    return out


def archive_nel(rows: list[dict]) -> list[dict]:
    return merge(NEL_FILE, rows)


def nel_archive() -> list[dict]:
    return _read(NEL_FILE)


def own_rows(daily: dict[str, pd.DataFrame], sessions: int = 300, min_price: float = 0.0) -> list[dict]:
    """Market Monitor calcolato sui nostri titoli (solo azioni), righe dalla seduta più recente."""
    closes = pd.DataFrame({s: df["Close"] for s, df in daily.items() if len(df) > 70})
    vols = pd.DataFrame({s: df["Volume"] for s, df in daily.items() if len(df) > 70}).reindex(closes.index)
    if closes.empty:
        return []
    closes = closes.sort_index()
    vols = vols.sort_index()
    ret = closes.pct_change(fill_method=None)
    vup = (vols > vols.shift(1)) & (vols >= MIN_VOL) & (closes >= min_price)
    up4 = ((ret >= 0.04) & vup).sum(axis=1)
    down4 = ((ret <= -0.04) & vup).sum(axis=1)
    # trimestre e 34 giorni: dal minimo (o massimo) della finestra, come Stockbee (verificato sul suo foglio:
    # correlazione 0,98-0,99); mese: variazione su 20 sedute
    q_up = closes / closes.rolling(66, min_periods=60).min() - 1
    q_dn = closes / closes.rolling(66, min_periods=60).max() - 1
    d_up = closes / closes.rolling(35, min_periods=32).min() - 1
    d_dn = closes / closes.rolling(35, min_periods=32).max() - 1
    r20 = closes / closes.shift(20) - 1
    # Studio 20% di Pradeep Bonde (scan TC2000 "5 Day up 20%": c/c5>=1.2 and minv3.1>=100000 and c>=3, su tutte le
    # azioni ordinarie USA) [RONIN 16/10, video TraderLion kCLiSsIZ7L4 89:30-92:00]; il calo speculare (c/c5<=0.8)
    # per il riquadro rosso dello stesso grafico.
    r5 = closes / closes.shift(5)
    minv3_1 = vols.shift(1).rolling(3).min()
    f20 = (minv3_1 >= MIN_VOL) & (closes >= 3)
    up20w = ((r5 >= 1.2) & f20).sum(axis=1)
    down20w = ((r5 <= 0.8) & f20).sum(axis=1)
    sma40 = closes.rolling(40).mean()
    valid = closes.notna() & sma40.notna()
    t2108 = (closes > sma40).where(valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100
    df = pd.DataFrame({"up4": up4, "down4": down4,
                       "ratio5": up4.rolling(5).sum() / down4.rolling(5).sum().replace(0, np.nan),
                       "ratio10": up4.rolling(10).sum() / down4.rolling(10).sum().replace(0, np.nan),
                       "up25q": (q_up >= 0.25).sum(axis=1), "down25q": (q_dn <= -0.25).sum(axis=1),
                       "up25m": (r20 >= 0.25).sum(axis=1), "down25m": (r20 <= -0.25).sum(axis=1),
                       "up50m": (r20 >= 0.50).sum(axis=1), "down50m": (r20 <= -0.50).sum(axis=1),
                       "up13d34": (d_up >= 0.13).sum(axis=1), "down13d34": (d_dn <= -0.13).sum(axis=1),
                       "up20w": up20w, "down20w": down20w,
                       "t2108": t2108, "universe": closes.notna().sum(axis=1)}).iloc[65:].tail(sessions)
    out = []
    for d, r in df.iloc[::-1].iterrows():
        if any(pd.isna(r[k]) for k in ("ratio5", "ratio10", "t2108")):
            continue
        out.append({"date": d.date().isoformat(), "up4": float(r.up4), "down4": float(r.down4),
                    "ratio5": round(float(r.ratio5), 2), "ratio10": round(float(r.ratio10), 2),
                    "up25q": float(r.up25q), "down25q": float(r.down25q), "up25m": float(r.up25m),
                    "down25m": float(r.down25m), "up50m": float(r.up50m), "down50m": float(r.down50m),
                    "up13d34": float(r.up13d34), "down13d34": float(r.down13d34), "up20w": float(r.up20w),
                    "down20w": float(r.down20w), "t2108": round(float(r.t2108), 2),
                    "universe": float(r.universe)})
    return out


COUNTS = ("up4", "down4", "up25q", "down25q", "up25m", "down25m", "up50m", "down50m", "up13d34", "down13d34", "universe")
# up20w / down20w (studio 20% di Pradeep) non si calibrano: Stockbee non li pubblica nel foglio, sono già sul suo
# stesso universo (azioni ordinarie USA) e con i suoi stessi filtri.


# Finestra della calibrazione: le ultime 120 sedute in comune con Stockbee. Provata a ritroso su 10 anni
# (2017-2026, 2.458 sedute, ricalibrando ogni 20 sedute solo con il passato): 90,6% di stati uguali con 120 sedute,
# 89,8% con 250, 88,1% con 500, 85,3% con 1000 (i titoli di oggi non sono quelli di allora: finestre lunghe
# peggiorano); con una calibrazione vecchia di 60 sedute 89,7%, di un anno 86%. Mai Expansion contro Defensive.
# Provati e scartati: filtro di prezzo minimo (1$, 3$, 5$: peggio) e scale cercate a griglia sugli stati (87-88%).
CAL_WINDOW = 120


def calibrate(own: list[dict], nel: list[dict], window: int = CAL_WINDOW) -> Optional[dict]:
    """Sulle ultime `window` sedute in comune con Stockbee: scala di ogni conteggio (rapporto mediano), retta del
    T2108 e dei rapporti 5D/10D (sui logaritmi); None se le sedute sono meno di 60."""
    n = {r["date"]: r for r in nel}
    pairs = sorted(((o, n[o["date"]]) for o in own if o["date"] in n), key=lambda p: p[0]["date"])[-window:]
    if len(pairs) < 60:
        return None
    k = {}
    for key in COUNTS:
        v = [b[key] / a[key] for a, b in pairs if a.get(key) and b.get(key) is not None]
        k[key] = round(float(np.median(v)), 4) if v else 1.0
    x = np.array([a["t2108"] for a, b in pairs if b.get("t2108") is not None])
    y = np.array([b["t2108"] for a, b in pairs if b.get("t2108") is not None])
    slope, icpt = (np.polyfit(x, y, 1) if len(x) >= 30 else (1.0, 0.0))
    fits = {}
    for key in ("ratio5", "ratio10"):
        xy = [(a[key], b[key]) for a, b in pairs if a.get(key) and b.get(key)]
        fits[key] = np.polyfit(np.log([p[0] for p in xy]), np.log([p[1] for p in xy]), 1) if len(xy) >= 30 else (1.0, 0.0)
    cal = {"sessions": len(pairs), "from": min(a["date"] for a, _ in pairs), "to": max(a["date"] for a, _ in pairs),
           "k": k, "ratio5_fit": [round(float(v), 4) for v in fits["ratio5"]],
           "ratio10_fit": [round(float(v), 4) for v in fits["ratio10"]],
           "t2108_slope": round(float(slope), 4), "t2108_intercept": round(float(icpt), 4)}
    from .regime import mm_state
    cal["state_agreement"] = round(float(np.mean([mm_state(apply(a, cal)) == mm_state(b) for a, b in pairs])), 3)
    cal["state_agreement_raw"] = round(float(np.mean([mm_state(a) == mm_state(b) for a, b in pairs])), 3)
    return cal


def apply(row: dict, cal: Optional[dict]) -> dict:
    """Riga nostra riportata alla scala di Stockbee."""
    if not cal:
        return dict(row)
    r = dict(row)
    k = cal.get("k") or {"up4": cal.get("k4", 1), "down4": cal.get("k4", 1),
                         "up25q": cal.get("k25q", 1), "down25q": cal.get("k25q", 1)}
    for key, f in k.items():
        if row.get(key) is not None:
            r[key] = round(row[key] * f)
    r["t2108"] = round(cal["t2108_slope"] * row["t2108"] + cal["t2108_intercept"], 2)
    for key in ("ratio5", "ratio10"):
        f = cal.get(f"{key}_fit")
        if f and row.get(key):
            r[key] = round(float(np.exp(f[0] * np.log(row[key]) + f[1])), 2)
    return r


def update(own: list[dict], nel: list[dict]) -> list[dict]:
    """Archivia le righe nostre, rifà la calibrazione se NEL c'è, restituisce le righe nostre calibrate."""
    allown = merge(OWN_FILE, own)
    cal = calibrate(allown, nel) if nel else None
    if cal:
        CAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        CAL_FILE.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    else:
        try:
            cal = json.loads(CAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            cal = None
    return [dict(apply(r, cal), source="own") for r in own]


# ------------------------------------------------------------------ replica completa (universo come Stockbee)
# Stockbee conta su ~6.500 azioni ordinarie USA (universo Worden). Noi usiamo tutte le azioni ordinarie quotate su
# NASDAQ, NYSE e AMEX dagli elenchi pubblici di Nasdaq Trader (niente ETF, warrant, unit, diritti, privilegiate):
# ~5.700 titoli. Verificato sul foglio di Stockbee: up4/down4 quasi identici (77 contro 78, 784 contro 799 il 14/10);
# su 10 anni stato uguale nell'83% delle sedute senza calibrazione, 90,6% con la calibrazione a 120 sedute (sopra).
# Gira ogni notte alle 00:00 di Roma (workflow "Market Monitor nostro") e scrive data/breadth/market_monitor_full.json.
FULL_FILE = DIR / "market_monitor_full.json"
CAL_FULL_FILE = DIR / "calibrazione_completa.json"
UNIVERSE_MM_FILE = DIR / "universo_mm.json"
NASDAQ_LISTS = ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
_NOT_COMMON = (r"warrant|\bunits?\b|\brights?\b|preferred|depositary shares? representing|\bnotes? due|debenture"
               r"|\d+(\.\d+)?% |subordinated|acquisition corp")


def mm_universe() -> list[str]:
    """Azioni ordinarie USA dagli elenchi di Nasdaq Trader (ticker in formato Yahoo); se la rete non risponde,
    l'ultimo elenco salvato nel repo."""
    import csv
    import io
    import re
    import urllib.request
    bad = re.compile(_NOT_COMMON, re.I)
    out: set[str] = set()
    try:
        for url in NASDAQ_LISTS:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JeffCoach)"})
            txt = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
            for r in csv.DictReader(io.StringIO(txt), delimiter="|"):
                sym = r.get("Symbol") or r.get("ACT Symbol") or ""
                if r.get("ETF") == "Y" or r.get("Test Issue") == "Y" or bad.search(r.get("Security Name") or ""):
                    continue
                if re.fullmatch(r"[A-Z]{1,5}(\.[A-B])?", sym):
                    out.add(sym.replace(".", "-"))
        if len(out) < 4000:
            raise RuntimeError(f"elenco Nasdaq Trader incompleto ({len(out)})")
        _write(UNIVERSE_MM_FILE, sorted(out))
        return sorted(out)
    except Exception as e:
        saved = _read(UNIVERSE_MM_FILE)
        if saved:
            log.warning("universo Market Monitor: %s, uso l'elenco salvato (%d titoli)", e, len(saved))
            return saved
        raise


def full_rows(end, days: int = 200) -> list[dict]:
    """Market Monitor sull'universo completo fino alla seduta `end` (date)."""
    from datetime import timedelta
    from . import data as D
    syms = mm_universe()
    daily = D.download_daily(syms, (end - timedelta(days=days)).isoformat(), end)
    return own_rows(daily, sessions=days)


def full_backup() -> list[dict]:
    """Righe della replica completa già calcolate (archivio), calibrate su Stockbee, segnate source=own."""
    try:
        cal = json.loads(CAL_FULL_FILE.read_text(encoding="utf-8"))
    except Exception:
        cal = None
    return [dict(apply(r, cal), source="own") for r in _read(FULL_FILE)]


def run_full(end=None) -> dict:
    """Calcolo serale: replica completa, archivio, calibrazione sullo storico di Stockbee (se c'è)."""
    from .calendar_us import close_et, is_session, now_et, prev_session
    if end is None:                                   # ultima seduta USA già chiusa (data di New York)
        now = now_et()
        d = now.date()
        end = d if is_session(d) and now >= close_et(d) else prev_session(d)
    rows = full_rows(end)
    allrows = merge(FULL_FILE, rows)
    cal = calibrate(allrows, nel_archive())
    if cal:
        CAL_FULL_FILE.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    return {"rows": len(rows), "last": rows[0]["date"] if rows else None, "calibration": cal}


def walk_forward(window: int = CAL_WINDOW, gap: int = 0, start: str = "2017-01-01", step: int = 20) -> dict:
    """Prova a ritroso della replica: ogni seduta dal `start` usa una calibrazione fatta solo con le sedute
    precedenti (ricalcolata ogni `step`, vecchia di `gap` sedute). Quota di stati uguali a Stockbee."""
    from .regime import mm_state
    nel = {r["date"]: r for r in nel_archive()}
    P = sorted(((o, nel[o["date"]]) for o in _read(FULL_FILE) if o["date"] in nel and nel[o["date"]].get("ratio10")
                is not None), key=lambda p: p[0]["date"])
    cache, ok, n, opp = {}, 0, 0, 0
    for i, (a, b) in enumerate(P):
        j = i - gap
        jj = j - j % step
        if a["date"] < start or jj - window < 0:
            continue
        if jj not in cache:
            cache[jj] = calibrate([x for x, _ in P[jj - window:jj]], [y for _, y in P[jj - window:jj]], window)
        s, t = mm_state(apply(a, cache[jj])), mm_state(b)
        ok += s == t
        n += 1
        opp += {s, t} == {"Expansion", "Defensive"}
    return {"sessions": n, "agreement": round(ok / n, 3) if n else None, "expansion_vs_defensive": opp}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "orario":
        # si = a Roma è tra mezzanotte e le 3 (GitHub a volte parte in ritardo), a New York oggi c'è stata seduta
        # e la sua riga non è ancora calcolata (dei due orari UTC parte solo il primo utile)
        from datetime import datetime
        from .calendar_us import ROME, now_et, is_session
        d = now_et().date()
        done = any(r.get("date") == d.isoformat() for r in _read(FULL_FILE)[:5])
        ok = datetime.now(ROME).hour < 3 and is_session(d) and not done
        print("si" if ok else "no")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "completo":
        from .data import fetch_market_monitor
        fetch_market_monitor()                       # aggiorna l'archivio di Stockbee per la calibrazione
        print(json.dumps(run_full(), indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "storico":
        # ricostruisce l'archivio dal 2015 (serve quando si aggiunge una colonna, es. lo studio 20% del 16/10)
        from datetime import date as _date
        from .calendar_us import prev_session, now_et
        end = prev_session(now_et().date() + __import__("datetime").timedelta(days=1))
        start = _date.fromisoformat(sys.argv[2] if len(sys.argv) > 2 else "2015-06-01")
        rows = full_rows(end, days=(end - start).days)
        allrows = merge(FULL_FILE, rows)
        print(json.dumps({"rows": len(rows), "first": rows[-1]["date"] if rows else None,
                          "last": rows[0]["date"] if rows else None, "archive": len(allrows)}))
    elif len(sys.argv) > 1 and sys.argv[1] == "verifica":
        print(json.dumps({"calibrazione ora": walk_forward(), "calibrazione vecchia di 60 sedute": walk_forward(gap=60)}))
    else:
        print("uso: python -m jeffcoach.breadth completo|verifica")
