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


CARD_TOTAL_LIMIT = 6000          # Discord: somma delle descrizioni di tutti gli embed di un messaggio


def card_line(r: dict, lim: Optional[int] = None) -> str:
    """Una voce per nome: statistiche sulla prima riga, descrizione subito sotto (restano insieme) [RONIN 09/10]."""
    s = (f"• **{r['ticker']}** — RS {_fmt(r.get('rs'), '{}')} · VCP {_fmt(r.get('vcp'), '{:.1f}')} · "
         f"SMA5 {_fmt(r.get('sma5'), '{:+.1f}%')} · Atr Ext {_fmt(r.get('atr_ext'), '{:.2f}×')}")
    why = r.get("reason_en") or ""
    if lim is not None and len(why) > lim:
        why = why[: lim - 1].rstrip(" ;,") + "…" if lim > 0 else ""
    return s + (f"\n  ↳ {why}" if why else "")


def sector_groups(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Raggruppa per settore [RONIN 09/10]: settori con più nomi prima, a parità in ordine alfabetico;
    dentro il settore resta l'ordine della lista (RS decrescente)."""
    g: dict[str, list[dict]] = {}
    for r in rows:
        g.setdefault(r.get("sector") or "Other", []).append(r)
    return sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0] == "Other", kv[0]))


def by_sector(rows: list[dict]) -> list[dict]:
    return [r for _, rr in sector_groups(rows) for r in rr]


def above_sma65(r: dict) -> bool:
    return "sma65" not in (r.get("open_gates") or [])


def sector_line(name: str, st: Optional[dict]) -> str:
    """Intestazione del settore con le stesse statistiche dei titoli, misurate sull'ETF del settore [RONIN 09/10]."""
    if not st:
        return f"__{name}__"
    return (f"__{name}__ ({st['etf']}) — RS {_fmt(st.get('rs'), '{}')} · VCP {_fmt(st.get('vcp'), '{:.1f}')} · "
            f"SMA5 {_fmt(st.get('sma5'), '{:+.1f}%')} · Atr Ext {_fmt(st.get('atr_ext'), '{:.2f}×')}")


def card_descriptions(title_date: str, focus: list[dict], stalk: list[dict],
                      sectors: Optional[dict] = None) -> list[str]:
    """Card: FOCUS, STALK sopra la SMA30 65m, STALK sotto [RONIN 04/10, 09/10]. Niente tabelle: una voce per nome
    con statistiche e descrizione. Ogni sezione è un embed a sé dello stesso messaggio (Discord: 4096 caratteri per
    embed, 6000 in tutto); oltre si accorciano le frasi, prima degli Stalk.
    I nomi non si tolgono mai."""
    up = [r for r in stalk if above_sma65(r)]
    down = [r for r in stalk if not above_sma65(r)]

    def sect(title: str, rows: list[dict], lim: Optional[int]) -> str:
        if not rows:
            return f"**{title}**\n• none"
        blocks = [sector_line(sec, (sectors or {}).get(sec)) + "\n" + "\n".join(card_line(r, lim) for r in rr)
                  for sec, rr in sector_groups(rows)]
        return f"**{title}**\n" + "\n\n".join(blocks)

    def build(f_lim, s_lim) -> list[str]:
        parts = [f"**WATCHLIST — {title_date}**\n\n" + sect("FOCUS", focus, f_lim),
                 sect(f"STALK — above 65m SMA30 ({len(up)})", up, s_lim),
                 sect(f"STALK — below 65m SMA30 ({len(down)})", down, s_lim)]
        return parts                                # una sezione per embed, sempre [RONIN 09/10]
    for f_lim, s_lim in ((None, None), (None, 70), (None, 45), (80, 30), (60, 0), (0, 0)):
        d = build(f_lim, s_lim)
        if all(len(x) <= CARD_LIMIT for x in d) and sum(len(x) for x in d) <= CARD_TOTAL_LIMIT:
            return d
    return [x[:CARD_LIMIT] for x in d]


def card_description(title_date: str, focus: list[dict], stalk: list[dict]) -> str:
    """Compatibilità: tutto in un testo solo."""
    return "\n\n".join(card_descriptions(title_date, focus, stalk))


def tv_symbol(t: str, exch: Optional[str]) -> str:
    return f"{TV_EXCHANGE.get(exch or '', 'NASDAQ' if not exch else exch)}:{t.replace('-', '.')}"


def tv_txt(focus: Iterable[tuple[str, str]], stalk: Iterable[tuple[str, str]],
           stalk_below: Optional[Iterable[tuple[str, str]]] = None) -> str:
    """###FOCUS,EXCH:T,...,###STALK,... in una riga [RONIN 06/10]. Con stalk_below gli Stalk sono divisi in due
    sezioni, sopra e sotto la SMA30 65m, come sulla card [RONIN 09/10]."""
    out = ["###FOCUS", *[tv_symbol(t, e) for t, e in focus]]
    if stalk_below is None:
        out += ["###STALK", *[tv_symbol(t, e) for t, e in stalk]]
    else:
        out += ["###STALK ABOVE 65m SMA30", *[tv_symbol(t, e) for t, e in stalk],
                "###STALK BELOW 65m SMA30", *[tv_symbol(t, e) for t, e in stalk_below]]
    return ",".join(out)
