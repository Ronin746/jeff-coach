"""Prova di identità della base: lo stesso mondo sintetico passa dal codice di Martin e da quello di jeff-coach con la
parte di Jeff spenta (JEFF_COACH_JEFF=0), e le uscite della lista devono essere uguali.

Uso (serve una copia di Ronin746/Martin-coach, anche solo in lettura):
    python strumenti/identita_base.py /percorso/martin-coach            # multi-edge acceso (come l'istanza di Martin)
    python strumenti/identita_base.py /percorso/martin-coach --meta 0   # regole di Dua

Confronta today.json, detail.json, card.json, themes_card.json, il txt di TradingView e summary_it.md. Le differenze
attese sono solo di percorso (l'istanza multi-edge di Martin scrive in data/meta, jeff-coach in data/): i file si
leggono ognuno dal suo posto. Esce con 0 se tutto è uguale.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION = "2026-10-13"
AS_OF = "2026-10-12"

RUNNER = r'''
import importlib, json, pickle, shutil, sys
from datetime import date
from pathlib import Path
pkg, world_p, themes_src = sys.argv[1], sys.argv[2], sys.argv[3]
C = importlib.import_module(pkg + ".config")
D = importlib.import_module(pkg + ".data")
TM = importlib.import_module(pkg + ".themes_map")
w = pickle.loads(Path(world_p).read_bytes())
(C.HOME / "themes").mkdir(parents=True, exist_ok=True)
shutil.copy(themes_src, C.HOME / "themes" / "mappa_etf.json")
D.build_universe = lambda *a, **k: w["uni"]
D.build_industry_map = lambda *a, **k: w["ind"]
D.download_daily = lambda syms, start, end, **k: {s: w["daily"][s] for s in syms if s in w["daily"]}
D.next_earnings = lambda syms, since: {s: None for s in syms}
D.download_intraday = lambda syms, period="1d", interval="1m", **k: (
    {s: w["hourly"][s] for s in syms if s in w["hourly"]} if interval == "60m" else {})
D.fetch_market_monitor = lambda: []
TM.refresh = lambda *a, **k: w["map"]
DL = importlib.import_module(pkg + ".daily")
assert DL.main(["--session", "%s"]) == 0
work = C.LISTS / "work_%s"
out = {}
for fn in ("detail.json", "card.json", "themes_card.json", "summary_it.md"):
    out[fn] = (work / fn).read_text(encoding="utf-8")
for fn in ("today.json", "watchlist_%s.txt"):
    out[fn] = (C.LISTS / fn).read_text(encoding="utf-8")
print("@@OUT@@" + json.dumps(out))
''' % (SESSION, SESSION, SESSION)


def world():
    import numpy as np
    import pandas as pd
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=700)

    def synth(seed, drift, vol=0.03, price=50.0, dvol=6e6):
        rng = np.random.default_rng(seed)
        r = rng.normal(drift, vol, len(idx))
        c = price * np.exp(np.cumsum(r))
        o = c * (1 + rng.normal(0, vol / 3, len(idx)))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, len(idx))))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, len(idx))))
        v = rng.uniform(0.6, 1.4, len(idx)) * dvol
        return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=idx)
    daily = {}
    for i in range(120):
        drift = (i % 9 - 4) * 0.0012
        daily[f"S{i:03d}"] = synth(i, drift, vol=0.02 + 0.0002 * i, price=20 + i, dvol=3e6 * (1 + i % 7))
    for k, d in (("QQQ", 0.0008), ("IWM", 0.0004), ("SPY", 0.0006), ("^GSPC", 0.0005)):
        daily[k] = synth(1000 + len(k), d, vol=0.01, price=400, dvol=5e7)
    for j, k in enumerate(("SOXX", "IGV", "XLF", "XLE", "XLV", "XLI", "XBI", "ARKK", "UFO", "CIBR", "URA", "QTUM", "BLOK",
                           "SMH", "GLD")):
        daily[k] = synth(2000 + j, 0.0003, vol=0.012, price=60, dvol=2e7)
    hourly = {}
    for s, df in daily.items():
        rows = []
        for d, r in df.iloc[-25:].iterrows():
            for h in range(7):
                t = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30 + 60 * h)
                f = h / 6
                px = r.Open + (r.Close - r.Open) * f
                rows.append((t, px, max(px, r.Open) * 1.002, min(px, r.Open) * 0.998, px, r.Volume / 7))
        hourly[s] = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")
    stocks = [s for s in daily if s.startswith("S")]
    uni = {s: {"exchange": "NMS", "quote_type": "EQUITY", "mcap": 5e9, "dv3m": 2e8} for s in stocks}
    inds = ("Semiconductors", "Software—Application", "Utilities—Regulated Electric", "Biotechnology", "Internet Retail")
    ind = {s: {"sector": "x", "industry": inds[k % len(inds)]} for k, s in enumerate(stocks)}
    themes = ("Semiconductors", "Software", "Retail")
    mp = {"built_utc": "2026-10-12T00:00:00+00:00",
          "tickers": {s: {"primary": themes[k % 3], "themes": [themes[k % 3]], "source": "etf"} for k, s in enumerate(stocks)},
          "themes": {t: "etf" for t in themes},
          "theme_etfs": {"Semiconductors": ["SOXX", "SMH"], "Software": ["IGV"], "Retail": ["XLI"], "Gold": ["GLD"]},
          "proxy_etfs": {"Gold": ["GLD"]}}
    return dict(daily=daily, hourly=hourly, uni=uni, ind=ind, map=mp)


def run(repo: Path, pkg: str, env_extra: dict, world_p: Path, themes_src: Path) -> dict:
    home = Path(tempfile.mkdtemp(prefix=f"id_{pkg}_"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MARTIN_COACH_", "JEFF_COACH_"))}
    env.update(env_extra)
    env["MARTIN_COACH_HOME" if pkg == "martincoach" else "JEFF_COACH_HOME"] = str(home)
    env["PYTHONPATH"] = str(repo)
    r = subprocess.run([sys.executable, "-c", RUNNER, pkg, str(world_p), str(themes_src)], cwd=repo, env=env,
                       capture_output=True, text=True)
    shutil.rmtree(home, ignore_errors=True)
    if "@@OUT@@" not in r.stdout:
        raise SystemExit(f"{pkg}: lista non riuscita\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return json.loads(r.stdout.split("@@OUT@@", 1)[1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("martin", help="cartella di una copia di Ronin746/Martin-coach")
    ap.add_argument("--meta", default="1", choices=("0", "1"))
    a = ap.parse_args(argv)
    martin = Path(a.martin).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="id_world_"))
    try:
        wp = tmp / "world.pkl"
        wp.write_bytes(pickle.dumps(world()))
        themes_src = martin / "data" / "themes" / "mappa_etf.json"
        m = run(martin, "martincoach", {"MARTIN_COACH_META": a.meta}, wp, themes_src)
        j = run(ROOT, "jeffcoach", {"JEFF_COACH_META": a.meta, "JEFF_COACH_JEFF": "0"}, wp, themes_src)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = 0
    det = json.loads(m["detail.json"])
    print(f"mondo sintetico: {len(det.get('candidates', []))} candidati, {len(det.get('near_misses', []))} a un passo, "
          f"Focus {[r['ticker'] for r in det.get('focus', [])]}, bias {det.get('bias')}, regole {det.get('rules_version')}")
    for fn in m:
        if m[fn] == j[fn]:
            print(f"uguale   {fn}")
            continue
        bad += 1
        print(f"DIVERSO  {fn}")
        for line in list(difflib.unified_diff(m[fn].splitlines(), j[fn].splitlines(), "martin", "jeff", lineterm=""))[:40]:
            print("   " + line)
    print("BASE IDENTICA" if not bad else f"{bad} file diversi")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
