"""Giornale dei trade simulati con le regole di Martin [RONIN 13/10: file a parte, equity 100k].

File (data/journal/):
  positions.json   posizioni aperte (vere e "ombra")
  trades.csv       un trade per riga, scritto alla chiusura (con tutto il contesto)
  events.csv       ogni esecuzione: apertura, trim, uscita
  equity.csv       una riga per seduta (scritta dalla chiusura serale)
  state.json       pausa dopo serie di perdite

Trade "ombra" = segnali scartati da un filtro (freno, gap degli indici, stop largo, esposizione...):
si gestiscono con le stesse regole ma non toccano l'equity. Servono a misurare se i filtri aiutano.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import config as C
from .calendar_us import ROME
from .output import write_atomic

POS = C.JOURNAL / "positions.json"
TRADES = C.JOURNAL / "trades.csv"
EVENTS = C.JOURNAL / "events.csv"
EQUITY = C.JOURNAL / "equity.csv"
STATE = C.JOURNAL / "state.json"

TRADE_FIELDS = [
    "id", "shadow", "shadow_reason", "rules_version", "date_open", "time_open_rome", "minutes_from_open", "ticker", "side",
    "setup", "theme", "theme_phase", "list", "bias", "qqq_trend", "iwm_trend", "breadth_lead", "grade",
    "level", "level_members", "confluence", "trigger_tf", "entry", "stop", "stop_pct", "adr", "dv5", "size_pct", "shares",
    "risk_usd", "risk_pct", "trimmed", "date_close", "exit_price_avg", "exit_reason", "pnl_usd", "r_multiple", "mfe_r", "mae_r",
    "days_held", "gap_through_stop", "taken_by_andrea", "notes",
    "n_edges", "edges", "edge_score",                       # multi-edge [RONIN 22/10]
]
EVENT_FIELDS = ["ts_rome", "id", "shadow", "ticker", "side", "kind", "shares", "price", "reason"]


def _now() -> str:
    return datetime.now(ROME).isoformat(timespec="seconds")


def _append(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():          # colonne nuove (es. edge, 22/10): si riscrive il file con l'intestazione nuova
        with path.open(newline="", encoding="utf-8") as f:
            head = next(csv.reader(f), None)
        if head and head != fields and set(head) <= set(fields):
            rows = read_csv(path)
            tmp = path.with_name(path.name + ".tmp")
            with tmp.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, path)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def positions() -> list[dict]:
    return json.loads(POS.read_text(encoding="utf-8")) if POS.exists() else []


def save_positions(ps: list[dict]) -> None:
    write_atomic(POS, ps)


def state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s: dict) -> None:
    write_atomic(STATE, s)


# ------------------------------------------------------------------ equity
def realized_equity() -> float:
    """Equity realizzata: 100k + P&L dei trade veri chiusi + parziali dei trade aperti."""
    eq = C.START_EQUITY
    for t in read_csv(TRADES):
        if t["shadow"] != "1":
            eq += float(t["pnl_usd"] or 0)
    for p in positions():
        if not p["shadow"]:
            eq += p.get("realized_usd", 0.0)
    return eq


def gross_exposure_pct(equity: float, prices: Optional[dict] = None) -> float:
    tot = 0.0
    for p in positions():
        if p["shadow"]:
            continue
        px = (prices or {}).get(p["ticker"], p["entry"])
        tot += abs(p["shares_open"] * px)
    return tot / equity * 100 if equity else 0.0


def closed_real(n: Optional[int] = None) -> list[dict]:
    rows = [t for t in read_csv(TRADES) if t["shadow"] != "1"]
    return rows[-n:] if n else rows


def feedback(n: int = C.FEEDBACK_TRADES) -> dict:
    """Trade feedback [ML]: somma degli R degli ultimi N trade veri chiusi, separata per lato."""
    rows = closed_real()
    out = {}
    for side in ("long", "short"):
        rs = [float(t["r_multiple"]) for t in rows if t["side"] == side][-n:]
        out[f"{side}_r"] = round(sum(rs), 2) if rs else None
        out[f"{side}_n"] = len(rs)
    return out


def signal_feedback(n: Optional[int] = None) -> dict:
    """Feedback dei segnali [RONIN 17/10; ML: "il feedback dei trade è il miglior indicatore", 15/07]: per lato, gli
    ultimi N trigger chiusi del giornale (tutti, perché i trade li sceglie Andrea; esclusi quelli d'apertura non
    segnalati): quanti sono arrivati ad almeno +1R, quanti stoppati senza mai arrivare a +0,5R, somma degli R."""
    n = n or C.SIGNAL_FEEDBACK_N
    out = {}
    try:
        rows = [t for t in read_csv(TRADES) if t.get("date_close")]
    except Exception:
        rows = []
    rows = [t for t in rows if not str(t.get("shadow_reason") or "").startswith(("primi", "QQQ in gap"))]
    for side in ("long", "short"):
        rs = [t for t in rows if t["side"] == side][-n:]
        f = lambda t, k: float(t.get(k) or 0)
        out[side] = dict(n=len(rs), hit1r=sum(f(t, "mfe_r") >= 1 for t in rs),
                         fast_stop=sum(f(t, "r_multiple") <= -0.9 and f(t, "mfe_r") < 0.5 for t in rs),
                         sum_r=round(sum(f(t, "r_multiple") for t in rs), 1))
    return out


def loss_streak() -> int:
    k = 0
    for t in reversed(closed_real()):
        if float(t["r_multiple"]) < 0:
            k += 1
        else:
            break
    return k


# ------------------------------------------------------------------ apertura e gestione
def size_for(entry: float, stop: float, equity: float, risk_pct: Optional[float] = None) -> tuple[int, float, float]:
    """Azioni, size % e rischio $: rischio 0,3% dell'equity (0,15% con bias MISTO), size massima 25% [ML]."""
    risk_usd = equity * (risk_pct or C.RISK_PCT) / 100
    per_share = abs(entry - stop)
    if per_share <= 0:
        return 0, 0.0, 0.0
    sh = int(risk_usd / per_share)
    cap = int(equity * C.SIZE_MAX_PCT / 100 / entry)
    sh = max(0, min(sh, cap))
    return sh, sh * entry / equity * 100, sh * per_share


def slippage(price: float, dv5: float, side: str, opening: bool) -> float:
    s = (C.SLIPPAGE_PCT_LIQUID if (dv5 or 0) >= C.DV_TIER else C.SLIPPAGE_PCT_OTHER) / 100
    # chi compra paga di più, chi vende incassa di meno
    buy = (side == "long") == opening
    return price * (1 + s) if buy else price * (1 - s)


def open_trade(ctx: dict, entry_raw: float, stop: float, shadow_reason: Optional[str], session: date,
               minutes_from_open: Optional[float]) -> dict:
    """Apre un trade (vero o ombra). `ctx` porta il contesto della lista (setup, tema, bias, livello...)."""
    side = ctx["side"]
    entry = slippage(entry_raw, ctx.get("dv5", 0), side, opening=True)
    eq = realized_equity()
    sh, size_pct, risk_usd = size_for(entry, stop, eq, ctx.get('risk_pct_day'))
    shadow = bool(shadow_reason)
    if not shadow and sh == 0:
        shadow, shadow_reason = True, "size zero"
    if not shadow and not C.ALERTS_ONLY and gross_exposure_pct(eq) + size_pct > C.GROSS_MAX_PCT:   # [16/10p]
        shadow, shadow_reason = True, "esposizione lorda massima"
    if shadow and sh == 0:
        sh, size_pct, risk_usd = size_for(entry, stop, C.START_EQUITY, ctx.get('risk_pct_day'))
    ps = positions()
    n = sum(1 for p in ps if p["date_open"] == session.isoformat()) + 1
    pid = f"{session.isoformat()}-{ctx['ticker']}-{side}-{n}"
    p = dict(
        id=pid, shadow=shadow, shadow_reason=shadow_reason or "", rules_version=C.RULES_VERSION,
        date_open=session.isoformat(), time_open_rome=_now(), minutes_from_open=None if minutes_from_open is None else round(minutes_from_open),
        ticker=ctx["ticker"], side=side, setup=ctx.get("setup"), theme=ctx.get("theme"), theme_phase=ctx.get("theme_phase"),
        list=ctx.get("list"), bias=ctx.get("bias"), qqq_trend=ctx.get("qqq_trend"), iwm_trend=ctx.get("iwm_trend"),
        breadth_lead=ctx.get("breadth_lead"), grade=ctx.get("grade", ""), level=ctx.get("level"),
        level_members="; ".join(ctx.get("level_members") or []), confluence=ctx.get("confluence"), trigger_tf=ctx.get("trigger_tf"),
        entry=round(entry, 4), stop=round(stop, 4), stop_pct=round(abs(entry - stop) / entry * 100, 3), adr=ctx.get("adr"),
        dv5=ctx.get("dv5"), size_pct=round(size_pct, 2), shares=sh, shares_open=sh, risk_usd=round(risk_usd, 2),
        risk_pct=round(risk_usd / (eq if not shadow else C.START_EQUITY) * 100, 3), trimmed=False, realized_usd=0.0,
        exits=[], hi=entry, lo=entry, gap_through_stop=False,
        e9d=ctx.get("e9d"), atr_d=ctx.get("atr_d"), ext_trims=[], trail_on=False, taken_by_andrea="", notes="",
        n_edges=ctx.get("n_edges"), edges=" ".join(ctx.get("edges") or []), edge_score=ctx.get("edge_score"),
    )
    ps.append(p)
    save_positions(ps)
    _append(EVENTS, EVENT_FIELDS, dict(ts_rome=_now(), id=pid, shadow=int(shadow), ticker=p["ticker"], side=side,
                                       kind="open", shares=sh, price=p["entry"], reason=shadow_reason or ""))
    return p


def r_of(p: dict, price: float) -> float:
    per = abs(p["entry"] - p["stop"])
    move = (price - p["entry"]) if p["side"] == "long" else (p["entry"] - price)
    return move / per if per else 0.0


def update_extremes(p: dict, high: float, low: float) -> None:
    p["hi"] = max(p["hi"], high)
    p["lo"] = min(p["lo"], low)


def fill(p: dict, shares: int, price_raw: float, kind: str, reason: str) -> None:
    """Uscita parziale o totale (prezzo con slippage)."""
    shares = min(shares, p["shares_open"])
    if shares <= 0:
        return
    price = slippage(price_raw, p.get("dv5") or 0, p["side"], opening=False)
    pnl = (price - p["entry"]) * shares if p["side"] == "long" else (p["entry"] - price) * shares
    p["shares_open"] -= shares
    p["realized_usd"] = round(p["realized_usd"] + pnl, 2)
    p["exits"].append({"ts": _now(), "shares": shares, "price": round(price, 4), "kind": kind, "reason": reason})
    _append(EVENTS, EVENT_FIELDS, dict(ts_rome=_now(), id=p["id"], shadow=int(p["shadow"]), ticker=p["ticker"], side=p["side"],
                                       kind=kind, shares=shares, price=round(price, 4), reason=reason))


def close_if_done(p: dict, session: date) -> bool:
    """Se la posizione è a zero la scrive in trades.csv. Ritorna True se chiusa."""
    if p["shares_open"] > 0:
        return False
    sold = sum(e["shares"] for e in p["exits"]) or 1
    avg = sum(e["shares"] * e["price"] for e in p["exits"]) / sold
    per = abs(p["entry"] - p["stop"]) * p["shares"] or 1
    row = dict(p)
    row.update(shadow=int(p["shadow"]), date_close=session.isoformat(), exit_price_avg=round(avg, 4),
               exit_reason=p["exits"][-1]["reason"] if p["exits"] else "", pnl_usd=round(p["realized_usd"], 2),
               r_multiple=round(p["realized_usd"] / per, 3), mfe_r=round(r_of(p, p["hi"] if p["side"] == "long" else p["lo"]), 3),
               mae_r=round(r_of(p, p["lo"] if p["side"] == "long" else p["hi"]), 3),
               days_held=(session - date.fromisoformat(p["date_open"])).days, trimmed=int(p["trimmed"]),
               gap_through_stop=int(p["gap_through_stop"]))
    _append(TRADES, TRADE_FIELDS, row)
    return True


def commit(ps: list[dict], session: date) -> list[dict]:
    """Scrive le posizioni: quelle chiuse passano in trades.csv, le altre restano aperte."""
    still = [p for p in ps if not close_if_done(p, session)]
    save_positions(still)
    return still


def equity_row(session: date, prices: dict[str, float]) -> dict:
    eq_real = realized_equity()
    unreal = 0.0
    for p in positions():
        if p["shadow"] or p["ticker"] not in prices:
            continue
        px = prices[p["ticker"]]
        unreal += (px - p["entry"]) * p["shares_open"] if p["side"] == "long" else (p["entry"] - px) * p["shares_open"]
    rows = read_csv(EQUITY)
    peak = max([float(r["equity_mtm"]) for r in rows] + [C.START_EQUITY])
    mtm = eq_real + unreal
    row = dict(date=session.isoformat(), equity_realized=round(eq_real, 2), equity_mtm=round(mtm, 2),
               drawdown_pct=round(min(0.0, (mtm / max(peak, mtm) - 1) * 100), 2),
               open_positions=sum(1 for p in positions() if not p["shadow"]),
               gross_pct=round(gross_exposure_pct(eq_real, prices), 1))
    rows = [r for r in rows if r["date"] != row["date"]] + [row]
    EQUITY.parent.mkdir(parents=True, exist_ok=True)
    with EQUITY.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        w.writeheader()
        w.writerows(rows)
    return row


# ------------------------------------------------------------------ lock (alert e chiusura scrivono lo stesso giornale)
class lock:
    """Lock su file: alert intraday e chiusura serale non scrivono mai il giornale insieme."""

    def __enter__(self):
        import fcntl
        C.JOURNAL.mkdir(parents=True, exist_ok=True)
        self.f = open(C.JOURNAL / ".lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
