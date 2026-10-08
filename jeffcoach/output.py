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


def card_description(title_date: str, focus: list[dict], stalk: list[dict]) -> str:
    """**WATCHLIST — data** in grassetto in prima riga, poi FOCUS e STALK [RONIN 04/10].
    Se si superano 4096 caratteri si accorciano le frasi Stalk: i nomi non si tolgono mai."""
    def build(stalk_reason_max: Optional[int]):
        st = []
        for r in stalk:
            rr = dict(r)
            if stalk_reason_max is not None and rr.get("reason_en") and len(rr["reason_en"]) > stalk_reason_max:
                rr["reason_en"] = rr["reason_en"][: stalk_reason_max - 1].rstrip(" ;,") + "…"
            st.append(card_line(rr, with_reason=stalk_reason_max != 0))
        fo = "\n".join(card_line(r) for r in focus) or "• none"
        return f"**WATCHLIST — {title_date}**\n\n**FOCUS**\n{fo}\n\n**STALK**\n" + ("\n".join(st) or "• none")
    for lim in (None, 60, 40, 25, 0):
        d = build(lim)
        if len(d) <= CARD_LIMIT:
            return d
    return d[:CARD_LIMIT]


def tv_symbol(t: str, exch: Optional[str]) -> str:
    return f"{TV_EXCHANGE.get(exch or '', 'NASDAQ' if not exch else exch)}:{t.replace('-', '.')}"


def tv_txt(focus: Iterable[tuple[str, str]], stalk: Iterable[tuple[str, str]]) -> str:
    """###FOCUS,EXCH:T,...,###STALK,EXCH:T,... in una riga [RONIN 06/10]."""
    return ",".join(["###FOCUS", *[tv_symbol(t, e) for t, e in focus], "###STALK", *[tv_symbol(t, e) for t, e in stalk]])
