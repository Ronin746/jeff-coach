"""Chiusura serale (dopo le 22:00 di Roma): regole sulla chiusura daily dei trade simulati ed equity.

  - recupero: se il server ha perso dei pezzi di seduta, stop e massimi/minimi si controllano sulla barra daily;
  - MGMT_MODE "ext_h50" [17g]: aggiorna EMA9 e ATR(14) daily della posizione (base dei parziali di domani) e chiude
    dopo MGMT_MAX_SESSIONS sedute; il resto (parziali, trailing sulla EMA50 oraria) lo fanno gli alert;
  - MGMT_MODE "classic" (fino alla 17f):
    long: chiusura sotto la EMA9 daily = fuori [ML]; chiusura ≥15% sopra la EMA9 = trim 15% (una volta) [ML];
    short: dopo SHORT_MAX_DAYS sedute si chiude [ML: short = swing di pochi giorni], tranne con bias SHORT
    (a inizio downtrend Martin tiene gli short; restano lo stop, la copertura a 3R e la barra oraria sopra la EMA50) [RONIN 14/10];
  - una riga in equity.csv e un riepilogo in reports/giornale_<data>.md.

Uso: python -m jeffcoach.chiusura [--session YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

import pandas as pd

from . import config as C
from . import data as D
from . import indicators as I
from . import journal as J
from .calendar_us import is_session, last_sessions, today_rome
from .output import write_atomic

log = logging.getLogger("jeffcoach.chiusura")


def session_bias(session: date) -> str | None:
    """Bias della lista della seduta (LONG, SHORT, MISTO, FERMO); None se la lista non c'è."""
    for p in (C.LISTS / f"{session}.json", C.LISTS / "today.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("session_date", d.get("session")) == session.isoformat():
            return d.get("bias")
    return None


def run(session: date, dry_run: bool = False) -> dict:
    bias = session_bias(session)
    with J.lock():
        ps = J.positions()
        tickers = sorted({p["ticker"] for p in ps})
        daily = D.download_daily(tickers, (session - timedelta(days=120)).isoformat(), session) if tickers else {}
        prices, done = {}, []
        for p in ps:
            df = daily.get(p["ticker"])
            if df is None or df.index[-1].date() != session or p["shares_open"] <= 0:
                continue
            bar = df.iloc[-1]
            close = float(bar.Close)
            prices[p["ticker"]] = close
            # recupero di quello che gli alert potrebbero non aver visto
            if p["date_open"] != session.isoformat() and not p.get(f"open_checked_{session}"):
                o = float(bar.Open)
                if (p["side"] == "long" and o <= p["stop"]) or (p["side"] == "short" and o >= p["stop"]):
                    p["gap_through_stop"] = True
                    J.fill(p, p["shares_open"], o, "exit", "gap oltre lo stop all'apertura (recupero serale)")
                    done.append(p["id"])
                    continue
            J.update_extremes(p, float(bar.High), float(bar.Low))
            # il minimo/massimo del giorno d'ingresso comprende la discesa (o la salita) di PRIMA dell'ingresso, e lo stop è
            # proprio il LOD/HOD: nel giorno d'ingresso lo stop lo controllano gli alert sulle barre intraday [fix 17/10]
            if p["date_open"] != session.isoformat() and \
                    ((p["side"] == "long" and bar.Low <= p["stop"]) or (p["side"] == "short" and bar.High >= p["stop"])):
                J.fill(p, p["shares_open"], p["stop"], "exit", "stop (recupero serale)")
                done.append(p["id"])
                continue
            e9 = float(I.ema(df.Close, C.EMA_FAST).iloc[-1])
            sess = [d.isoformat() for d in last_sessions(session, 40)]
            held = len(sess) - sess.index(p["date_open"]) - 1 if p["date_open"] in sess else 99
            if C.MGMT_MODE == "ext_h50":
                # domani i parziali si misurano dalla EMA9 e dall'ATR di questa chiusura
                pc = df.Close.shift(1)
                tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
                p["e9d"], p["atr_d"] = round(e9, 4), round(float(tr.rolling(14).mean().iloc[-1]), 4)
                if held >= C.MGMT_MAX_SESSIONS:
                    J.fill(p, p["shares_open"], close, "exit", f"tenuto {held} sedute")
                    done.append(p["id"])
                continue
            if p["side"] == "long":
                if close < e9:
                    J.fill(p, p["shares_open"], close, "exit", "chiusura sotto la EMA9")
                    done.append(p["id"])
                elif close >= e9 * (1 + C.LONG_TRIM_EXT_EMA9_PCT / 100) and not p.get("trimmed_ext"):
                    p["trimmed_ext"] = True
                    J.fill(p, max(1, int(p["shares"] * C.LONG_TRIM_FRAC)), close, "trim", "15% sopra la EMA9")
            else:
                if held >= C.SHORT_MAX_DAYS and bias not in C.SHORT_TIME_EXIT_FREE_BIAS:
                    J.fill(p, p["shares_open"], close, "exit", f"short tenuto {held} sedute")
                    done.append(p["id"])
        if dry_run:
            return {"dry_run": True, "closed": done, "open": len(ps)}
        ps = J.commit(ps, session)
        eq = J.equity_row(session, prices)
        trades = [t for t in J.read_csv(J.TRADES) if t["date_close"] == session.isoformat()]
        lines = [f"# Giornale {session}", "",
                 f"Equity simulata {eq['equity_mtm']:,.0f} (realizzata {eq['equity_realized']:,.0f}), drawdown {eq['drawdown_pct']}%, "
                 f"posizioni aperte {eq['open_positions']}, esposizione {eq['gross_pct']}%", "",
                 "| Trade | Lato | Ombra | R | Motivo |", "|---|---|---|---|---|"]
        lines += [f"| {t['ticker']} | {t['side']} | {'sì' if t['shadow'] == '1' else 'no'} | {t['r_multiple']} | {t['exit_reason']} |" for t in trades]
        write_atomic(C.REPORTS / f"giornale_{session}.md", "\n".join(lines) + "\n", as_json=False)
        return {"closed_today": len(trades), "equity": eq}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = date.fromisoformat(a.session) if a.session else today_rome()
    if not is_session(s):
        print(json.dumps({"skipped": True}))
        return 0
    print(json.dumps(run(s, a.dry_run), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
