"""Formati di uscita condivisi: card Discord, txt TradingView, file per Remy, scritture atomiche."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

TV_EXCHANGE = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NYQ": "NYSE", "NYS": "NYSE",
               "ASE": "AMEX", "PCX": "AMEX", "BTS": "CBOE"}
CARD_LIMIT = 4096


def write_atomic(path: Path, data, *, as_json: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if as_json:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    else:
        tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _fmt(v, f):
    return "n/a" if v is None else f.format(v)


def card_line(r: dict, with_reason: bool = True) -> str:
    s = (f"• **{r['ticker']}** — RS {_fmt(r.get('rs'), '{}')} · VCP {_fmt(r.get('vcp'), '{:.1f}')} · "
         f"{_fmt(r.get('sma5'), '{:+.1f}%')} SMA5 · Atr Ext {_fmt(r.get('atr_ext'), '{:.2f}×')}")
    if with_reason and r.get("reason_en"):
        s += f" · {r['reason_en']}"
    return s


def _num(v, f: str, w: int) -> str:
    return ("n/a" if v is None else f.format(v)).rjust(w)


def card_table(rows: list[dict], lim: Optional[int] = None) -> str:
    """Colonne allineate in un blocco a larghezza fissa; sotto ogni nome, rientrata, la sua descrizione
    (statistiche e motivo restano insieme) [RONIN 09/10]."""
    head = f"{'':6}{'RS':>3} {'VCP':>5} {'SMA5':>6} {'AtrExt':>6}"
    lines = [head]
    for r in rows:
        lines.append(f"{r['ticker']:<6}{_num(r.get('rs'), '{}', 3)} {_num(r.get('vcp'), '{:.1f}', 5)} "
                     f"{_num(r.get('sma5'), '{:+.1f}%', 6)} {_num(r.get('atr_ext'), '{:.2f}', 6)}")
        why = r.get("reason_en") or ""
        if lim is not None and len(why) > lim:
            why = why[: lim - 1].rstrip(" ;,") + "…" if lim > 0 else ""
        if why:
            lines.append("  " + why)
    return "```\n" + "\n".join(lines) + "\n```"


def above_sma65(r: dict) -> bool:
    return "sma65" not in (r.get("open_gates") or [])


def card_description(title_date: str, focus: list[dict], stalk: list[dict]) -> str:
    """**WATCHLIST — data** in grassetto in prima riga, poi FOCUS e STALK [RONIN 04/10].
    Statistiche in colonne allineate, sotto ogni tabella la descrizione completa di ogni nome; Stalk divisi tra
    sopra e sotto la SMA30 65m [RONIN 09/10]. Oltre 4096 caratteri si accorciano le frasi (prima gli Stalk):
    i nomi non si tolgono mai."""
    up = [r for r in stalk if above_sma65(r)]
    down = [r for r in stalk if not above_sma65(r)]

    def sect(title: str, rows: list[dict], lim: Optional[int]) -> str:
        return f"**{title}**\n" + (card_table(rows, lim) if rows else "• none")

    def build(f_lim: Optional[int], s_lim: Optional[int]):
        return (f"**WATCHLIST — {title_date}**\n\n" + sect("FOCUS", focus, f_lim) + "\n\n"
                + sect(f"STALK — above 65m SMA30 ({len(up)})", up, s_lim) + "\n\n"
                + sect(f"STALK — below 65m SMA30 ({len(down)})", down, s_lim))
    for f_lim, s_lim in ((None, None), (None, 60), (None, 40), (80, 30), (60, 0), (0, 0)):
        d = build(f_lim, s_lim)
        if len(d) <= CARD_LIMIT:
            return d
    return d[:CARD_LIMIT]


def tv_symbol(t: str, exch: Optional[str]) -> str:
    return f"{TV_EXCHANGE.get(exch or '', 'NASDAQ' if not exch else exch)}:{t.replace('-', '.')}"


def tv_txt(focus: Iterable[tuple[str, str]], stalk: Iterable[tuple[str, str]]) -> str:
    """###FOCUS,EXCH:T,...,###STALK,EXCH:T,... in una riga [RONIN 06/10]."""
    return ",".join(["###FOCUS", *[tv_symbol(t, e) for t, e in focus], "###STALK", *[tv_symbol(t, e) for t, e in stalk]])
