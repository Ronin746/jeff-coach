"""Prova di invio [RONIN 09/10]: rigioca la seduta di oggi (o l'ultima) barra per barra con le regole nuove e manda
qualche esempio su Discord, con "TEST" nel titolo.

  Remy:   30 minute pivot nelle tre versioni (DTL break + EMA9, DTL break 5d, EMA9 undercut), su watchlist +
          titoli automatici (adv$ >= 50M, mcap > 500M, RS >= 80).
  Sydney: un paio di "Channel" con il grafico, solo nomi che passano le regole nuove dei canali.

  python cloud/test_invio.py            calcola e stampa, non manda
  python cloud/test_invio.py --invia    manda (DISCORD_WEBHOOK_URL per Remy, COACH_ALERT_DISCORD_WEBHOOK_URL per Sydney)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TV = ROOT / "tv-scanner"
sys.path.insert(0, str(TV))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TV_SCANNER_HOME", str(TV))
os.environ.setdefault("JEFF_COACH_HOME", str(ROOT / "dati"))
ET = ZoneInfo("America/New_York")


def remy_replay(max_send: int) -> list[dict]:
    import pandas as pd
    import yfinance as yf
    import scanner as S
    from refresh_yfinance import bars_from_df
    import universo_auto as U

    if not (TV / "pivot_wl_auto.txt").exists() or not (TV / "pivot_wl_auto.txt").read_text().startswith(f"date: {U.oggi_ny()}"):
        res = U.costruisci()
        (TV / "pivot_wl_auto.txt").write_text(f"date: {U.oggi_ny()}\n" + "\n".join(res["out"]) + "\n", encoding="utf-8")
        print("universo automatico:", res["stats"])
    syms = S.load_pivot_wl()
    tick = {s: s.split(":")[-1].replace(".", "-") for s in syms}
    print("titoli:", len(syms))
    f5 = yf.download(list(tick.values()), period="5d", interval="5m", prepost=False, auto_adjust=False,
                     group_by="ticker", progress=False, threads=True)
    fd = yf.download(list(tick.values()) + ["^GSPC"], period="2y", interval="1d", auto_adjust=False,
                     group_by="ticker", progress=False, threads=True)
    from rs_rating import compute_rs_rating
    spx = bars_from_df(fd["^GSPC"].dropna(subset=["Close"]))
    found = []
    for s, t in tick.items():
        try:
            b5 = bars_from_df(f5[t].dropna(subset=["Close"]))
            bd = bars_from_df(fd[t].dropna(subset=["Close"]))
        except Exception:
            continue
        if len(b5) < 100 or len(bd) < 260:
            continue
        day = S._et_day(int(b5[-1]["t"]))
        rs = compute_rs_rating(s, daily_bars=bd, spx_bars=spx, now=int(b5[-1]["t"]) + 600)
        if S.RS_MIN_30M_PIVOT is not None and (rs is None or rs < S.RS_MIN_30M_PIVOT):
            continue
        today = [b for b in b5 if S._et_day(int(b["t"])) == day]
        for b in today[12:]:                                   # dalle 10:30 in poi
            now = int(b["t"]) + 320
            upto = [x for x in b5 if int(x["t"]) <= int(b["t"])]
            ind = S.compute_indicators(upto, now)
            if ind is None:
                continue
            sig = S.detect_30m_pivot(s, upto, ind, now=now, rs_rating=rs, min_rs=S.RS_MIN_30M_PIVOT, daily_bars=bd)
            if sig is not None:
                found.append(sig)
    print("segnali nella seduta:", len(found))
    for g in found:
        print(f"  {g.symbol:16s} {datetime.fromtimestamp(g.bar_t, ET):%H:%M}  {g.pivot_version:18s} @ {g.price:.2f}  H {g.pivot_high:.2f} / L {g.pivot_low:.2f}  RS {g.rs_rating}")
    # per la prova: uno o due per versione, i più recenti
    pick, per = [], {}
    for g in sorted(found, key=lambda x: -x.bar_t):
        if per.get(g.pivot_version, 0) < 2 and len(pick) < max_send:
            pick.append(g)
            per[g.pivot_version] = per.get(g.pivot_version, 0) + 1
    return pick


def send_remy(sigs) -> None:
    from discord_notify import build_discord_embeds, _normalize, load_webhook_url
    url = load_webhook_url()
    if not url:
        print("Remy: webhook non configurato (DISCORD_WEBHOOK_URL)")
        return
    for g in sorted(sigs, key=lambda x: x.bar_t):
        embeds = build_discord_embeds(_normalize([g]))
        for e in embeds:
            e["title"] = "TEST · " + e["title"]
        req = urllib.request.Request(url, data=json.dumps({"embeds": embeds, "allowed_mentions": {"parse": []}}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "jeff-coach"})
        try:
            urllib.request.urlopen(req, timeout=30).read()
            print("Remy mandato:", embeds[0]["title"])
        except Exception as e:
            print("Remy errore:", e)
        time.sleep(1.5)


def sydney_channels(n: int, invia: bool) -> None:
    import pandas as pd
    import yfinance as yf
    from jeffcoach import channel as CH
    from jeffcoach import indicators as I
    from jeffcoach.alerts import fmt_channel
    from jeffcoach.chart import channel_chart
    from jeffcoach.discord import send_alert

    d = json.loads((ROOT / "data" / "coach-agreed" / "today.json").read_text(encoding="utf-8"))
    names = [c["ticker"] for c in d.get("channel_watch") or []]
    raw = yf.download(names, period="2y", interval="1d", auto_adjust=False, group_by="ticker", progress=False)
    today = datetime.now(ET).date()
    sent = 0
    for t in names:
        df = raw[t].dropna(subset=["Close"])
        df = df[[x.date() < today for x in df.index]].iloc[-260:]
        tr = pd.concat([df.High - df.Low, (df.High - df.Close.shift()).abs(), (df.Low - df.Close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        m = CH.read_channel(df, atr)
        ok, why, _ = CH.reading_d(m) if m.get("d_found") else (False, ["no channel"], [])
        print(f"  canale {t:6s} {'OK  ' + m['d_state'] if ok else 'no: ' + '; '.join(why)}")
        if not ok or sent >= n:
            continue
        price = float(df.Close.iloc[-1])
        e9 = float(I.ema(df.Close, 9).iloc[-1])
        c = dict(ticker=t, state=m["d_state"], ema9=e9, lower_line_next=m["d_lower_next"], upper_line_next=m["d_upper_next"])
        title, body = fmt_channel(c, price, price)
        body = body.replace("65m SMA30 reclaimed", "65m SMA30 (prova, valore al close)")
        if invia:
            img = channel_chart(c, None, price, None)
            r = send_alert("TEST · " + title, body, image=img)
            print("Sydney mandato:", title, r.get("sent", r))
            time.sleep(1.5)
        sent += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--invia", action="store_true")
    ap.add_argument("--remy", type=int, default=5)
    ap.add_argument("--sydney", type=int, default=2)
    a = ap.parse_args()
    pick = remy_replay(a.remy)
    if a.invia:
        send_remy(pick)
    sydney_channels(a.sydney, a.invia)
    return 0


if __name__ == "__main__":
    sys.exit(main())
