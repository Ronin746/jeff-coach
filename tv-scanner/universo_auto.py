"""Titoli in più per il 30M PIVOT di Remy, oltre alle watchlist TradingView [RONIN 09/10].

Una volta al giorno, prima dell'apertura (avvia.py lo lancia con il sync delle watchlist, 15:00 Roma):
  1. universo Yahoo: azioni USA con capitalizzazione > 500 milioni (jeffcoach.data.build_universe);
  2. daily di un anno; tengo chi ha adv$ >= 50 milioni (media 50 giorni di volume × close) e RS >= 80;
  3. tengo solo chi oggi può dare una delle tre versioni del pivot (vedi scanner.pivot30_version):
       - trendline discendente daily rotta negli ultimi 10 giorni con volume >= 1,5x, non fallita;
       - oppure EMA9 daily in salita con il close di ieri non oltre 3 ATR sopra la EMA9 (il pivot deve
         poterci arrivare in giornata);
     e non oltre 5,5 ATR sopra la SMA50.
Scrive pivot_wl_auto.txt con "date: AAAA-MM-GG" (seduta di New York): lo scanner lo legge solo quel giorno.

  python universo_auto.py            costruisce il file di oggi
  python universo_auto.py --se-manca  esce subito se il file di oggi c'è già
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(os.environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

OUT = BASE / "pivot_wl_auto.txt"
INFO = BASE / "pivot_wl_auto.json"
ET = ZoneInfo("America/New_York")

MCAP_MIN = 1e9          # Ronin 10/10 (era 500M)
ADV_MIN = 50e6
RS_MIN = 80
MAX_EXT50_ATR = 5.5
EMA9_MAX_ABOVE_ATR = 3.0


def oggi_ny() -> str:
    return datetime.now(ET).date().isoformat()


def costruisci() -> dict:
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from jeffcoach import data as JD
    from jeffcoach import dtl as D
    from rs_rating import compute_rs_rating_from_closes, get_thresholds

    t0 = time.time()
    uni = JD.build_universe()
    syms = sorted(s for s, m in uni.items() if (m.get("mcap") or 0) > MCAP_MIN and "^" not in s)
    today = datetime.now(ET).date()
    th = get_thresholds()[0]

    def dl(tk):
        f = yf.download(tk, period="13mo", interval="1d", auto_adjust=False, group_by="ticker",
                        progress=False, threads=True)
        return f

    spx = dl(["^GSPC"])
    spx = spx["^GSPC"] if isinstance(spx.columns, pd.MultiIndex) else spx
    spx = spx.dropna(subset=["Close"])
    spx = spx[[d.date() < today for d in spx.index]]

    out, info = [], {}
    stats = dict(universo=len(syms), adv=0, rs=0)
    for i in range(0, len(syms), 400):
        chunk = syms[i:i + 400]
        try:
            f = dl(chunk)
        except Exception as e:
            print(f"download {i}: {e}")
            continue
        for s in chunk:
            try:
                df = f[s] if isinstance(f.columns, pd.MultiIndex) else f
                df = df.dropna(subset=["Close"])
            except Exception:
                continue
            df = df[[d.date() < today for d in df.index]]          # solo sedute chiuse
            if len(df) < 120:
                continue
            c, v = df.Close, df.Volume
            adv = float((c * v).rolling(50).mean().iloc[-1])
            if not adv >= ADV_MIN:
                continue
            stats["adv"] += 1
            ref = spx.Close.reindex(df.index).ffill()
            r = compute_rs_rating_from_closes(list(c.values), list(ref.values), th)
            if not r or r[0] < RS_MIN:
                continue
            stats["rs"] += 1
            tr = pd.concat([df.High - df.Low, (df.High - c.shift()).abs(), (df.Low - c.shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
            e9 = c.ewm(span=9, adjust=False).mean()
            s50 = float(c.rolling(50).mean().iloc[-1])
            pc = float(c.iloc[-1])
            if not atr or (pc - s50) / atr > MAX_EXT50_ATR:
                continue
            m = D.read_dtl(df.iloc[-260:], atr)
            dtl_ok = bool(m.get("dt_broken") and m.get("dt_break_ago", 99) <= 10 and m.get("dt_dist_atr", -9) >= -1
                          and ((m.get("dt_break_vol") or 0) >= 1.5 or m.get("dt_confirm_ago") is not None))
            e9_ok = bool(e9.iloc[-1] > e9.iloc[-2] and (pc - e9.iloc[-1]) / atr <= EMA9_MAX_ABOVE_ATR)
            if not (dtl_ok or e9_ok):
                continue
            ex = (uni.get(s, {}).get("exchange") or "").upper()
            pref = "NASDAQ" if ex in ("NMS", "NGM", "NCM") else "NYSE" if ex == "NYQ" else "AMEX" if ex == "ASE" else ""
            out.append(f"{pref}:{s}" if pref else s)
            info[s] = dict(rs=r[0], adv_m=round(adv / 1e6), ext50=round((pc - s50) / atr, 2),
                           dtl=dtl_ok, ema9=e9_ok, dtl_break=m.get("dt_break_date"))
    stats.update(file=len(out), secondi=round(time.time() - t0))
    return dict(out=out, info=info, stats=stats)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--se-manca", action="store_true")
    a = ap.parse_args()
    d = oggi_ny()
    if a.se_manca and OUT.exists() and OUT.read_text(encoding="utf-8").startswith(f"date: {d}"):
        print(f"pivot_wl_auto.txt di {d} già fatto")
        return 0
    res = costruisci()
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(f"date: {d}\n" + "\n".join(res["out"]) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    INFO.write_text(json.dumps(dict(date=d, stats=res["stats"], titoli=res["info"]), indent=1), encoding="utf-8")
    print(json.dumps(res["stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
