"""Formati di uscita condivisi: card Discord, txt TradingView, file per Remy, scritture atomiche."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from . import config as C

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
    if r.get("theme"):                    # tema [RONIN 13/10]: ★ = tema leading in uptrend
        s += f"\n  {'★ ' if r.get('theme_leading') else ''}{r['theme']}" + (f" ({r['theme_stage']})" if r.get("theme_stage") else "")
    if r.get("against_regime"):
        s += " · ⚠ against the regime"
    why = r.get("reason_en") or ""
    if lim is not None and len(why) > lim:
        why = why[: lim - 1].rstrip(" ;,") + "…" if lim > 0 else ""
    return s + (f"\n↳ {why}" if why else "")


def sector_groups(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Raggruppa per settore [RONIN 09/10]: settori con più nomi prima, a parità in ordine alfabetico;
    dentro il settore resta l'ordine della lista (RS decrescente)."""
    g: dict[str, list[dict]] = {}
    for r in rows:
        g.setdefault(r.get("sector") or "Other", []).append(r)
    return sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0] == "Other", kv[0]))


def by_sector(rows: list[dict]) -> list[dict]:
    return [r for _, rr in sector_groups(rows) for r in rr]


def _ma65() -> str:
    """Etichetta della media sulle barre 65m: EMA50 dal 20/10 [ANDREA], prima SMA30."""
    return f"{C.MA65_KIND.upper()}{C.MA65_LEN}"


def above_sma65(r: dict) -> bool:
    return "sma65" not in (r.get("open_gates") or [])


def sector_line(name: str, st: Optional[dict]) -> str:
    """Intestazione del settore con le stesse statistiche dei titoli, misurate sull'ETF del settore [RONIN 09/10]."""
    if not st:
        return f"__{name}__"
    s = (f"__{name}__ ({st['etf']}) — RS {_fmt(st.get('rs'), '{}')} · VCP {_fmt(st.get('vcp'), '{:.1f}')} · "
         f"SMA5 {_fmt(st.get('sma5'), '{:+.1f}%')} · Atr Ext {_fmt(st.get('atr_ext'), '{:.2f}×')}")
    if st.get("n"):      # titoli del settore con RS >= 90 sul totale dell'universo [RONIN 09/10]
        s += f" · RS≥90 {st.get('strong', 0)}/{st['n']}"
        if st.get("strong_w1") is not None:         # rispetto alla chiusura della settimana prima [RONIN 09/10]
            s += f" ({st.get('strong', 0) - st['strong_w1']:+d} vs last wk)"
    return s


def regime_line(reg: Optional[dict], themes_line: Optional[str] = None) -> str:
    """Parte del regime in testa alla card, come Martin-coach [RONIN 13/10, 15/10, 16/10]: regime con i motivi,
    Market Monitor letto come Pradeep (±4%, 25% nel trimestre, T2108, studio 20%), tabella ±4% a 20 giorni,
    avviso di potential trend reversal, temi. Il grafico studio 20% / T2108 è l'immagine dello stesso riquadro."""
    if not reg:
        return ""
    bias = {"SHORT": "DEFENSIVE"}.get(reg["bias"], reg["bias"])
    rule = {"MIXED": f"max {C.REGIME_MIXED_MAX_FOCUS} Focus",
            "SHORT": f"Focus only with a LEADING/BUILDING theme (max {C.REGIME_DEFENSIVE_MAX_FOCUS})"}.get(reg["bias"])
    rev = reg.get("reversal")
    if rev and rev.get("direction") == "buying":
        rule = "no Focus limit (potential trend reversal)"
    L = [f"Regime **{bias}**" + (f" · {rule}" if rule else "") + " — " + "; ".join(reg.get("why") or [])]
    if rev:
        L.append(f"⚠️ **POTENTIAL TREND REVERSAL** — ±4% flow turned to **{rev['direction']}** on {rev['date']} "
                 f"(day {rev['day']} of {C.REVERSAL_DAYS})")
    mm = reg.get("market_monitor")
    if mm:
        own = " (own calc)" if mm.get("source") == "own" else ""
        if mm.get("read") == "pradeep":
            L.append(f"Market Monitor **{mm['state']}**{own} · ±4% `{mm['up4']:.0f}` / `{mm['down4']:.0f}`"
                     + (f" · 25%Q `{mm['up25q']:.0f}` / `{mm['down25q']:.0f}`" if mm.get("up25q") is not None and mm.get("down25q") is not None else "")
                     + (f" · T2108 `{mm['t2108']:.0f}%`" if mm.get("t2108") is not None else "")
                     + (f" · 20% study `{mm['up20w']:.0f}`" if mm.get("up20w") is not None else ""))
        else:
            L.append(f"Market Monitor **{mm['state']}**{own} · ±4% `{mm['up4']:.0f}` / `{mm['down4']:.0f}`"
                     + (f" · 5D `{mm['ratio5']:.2f}` · 10D `{mm['ratio10']:.2f}`" if mm.get("ratio10") is not None else "")
                     + (f" · T2108 `{mm['t2108']:.0f}%`" if mm.get("t2108") is not None else ""))
    if reg.get("mm_hist"):
        from .breadth_chart import table_20d
        tb = table_20d(reg["mm_hist"])
        if tb:
            L.append("**±4% last 20 days** (▲ buying · ▼ selling)\n" + tb)
    if themes_line:
        L.append(f"Themes: {themes_line}")
    return "\n".join(L)


def themes_section(th: Optional[dict]) -> Optional[str]:
    if not th or not th.get("n_themes"):
        return None
    L = [f"**THEMES** — LEADING / BUILDING ({len(th['leading'])} of {th['n_themes']}) · score on the theme ETFs (7 factors)"]
    for t in th["leading"][:10]:
        tk = f" ({', '.join(t['tickers'])})" if t.get("tickers") else (f" ({', '.join(t['etfs'][:3])})" if t.get("etfs") else "")
        L.append(f"{'★' if t.get('stage') == 'LEADING' else '•'} {t['theme']} — score {t['score']} · {t.get('stage')}"
                 + (f" · 1M {t['ret21']:+.1f}%" if t.get("ret21") is not None else "")
                 + (f" · vs S&P {t['rs21']:+.1f}%" if t.get("rs21") is not None else "") + tk)
    if th.get("downtrend"):
        dt = th["downtrend"]
        L.append(f"WEAK / BEARISH, names excluded ({len(dt)}): " + ", ".join(dt[:25]) + (" …" if len(dt) > 25 else ""))
    return "\n".join(L)[:3900]


def card_descriptions(title_date: str, focus: list[dict], stalk: list[dict],
                      sectors: Optional[dict] = None, dtl_breaks: Optional[list[dict]] = None,
                      regime: Optional[dict] = None, themes: Optional[dict] = None, as_of: Optional[str] = None) -> list[str]:
    """Card: FOCUS, STALK sopra la media 65m, STALK sotto [RONIN 04/10, 09/10]. Niente tabelle: una voce per nome
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
        head = f"**WATCHLIST — {title_date}**" + (f" (close {as_of})" if as_of else "")
        rl = regime_line(regime, (themes or {}).get("line"))
        parts = ([f"{head}\n{rl}"] if rl else []) + [("" if rl else f"{head}\n\n") + sect("FOCUS", focus, f_lim),
                 sect(f"STALK — above 65m {_ma65()} ({len(up)})", up, s_lim),
                 sect(f"STALK — below 65m {_ma65()} ({len(down)})", down, s_lim)]
        if dtl_breaks:          # rotture della trendline discendente in chiusura con volume >= 1,5x [RONIN 09/10]
            rows = [dict(d, reason_en=(f"downtrend line break, vol {d['break_vol']}× avg" if d.get("break_ago") == 0 else
                                       f"downtrend line broken {d['break_date'][5:]}, confirmed today with vol {d['confirm_vol']}× avg")
                                      + " · line from "
                                      + f"{d['start'][5:]} high {d['start_high']} · next {d['line_next']}"
                                      + ("" if d.get("above_sma200") else " · under SMA200"))
                    for d in dtl_breaks]
            parts.append(sect(f"DOWNTREND LINE BREAK — vol ≥1.5× ({len(rows)})", rows, s_lim))
        ts = themes_section(themes)
        if ts:
            parts.append(ts)
        return parts                                # una sezione per embed, sempre [RONIN 09/10]
    # oltre i 6000 caratteri a messaggio la card continua in un secondo messaggio (discord.post_card): le frasi
    # si accorciano solo se una singola sezione supera i 4096 caratteri di un riquadro
    for f_lim, s_lim in ((None, None), (None, 70), (None, 45), (80, 30), (60, 0), (0, 0)):
        d = build(f_lim, s_lim)
        if all(len(x) <= CARD_LIMIT for x in d):
            return d
    return [x[:CARD_LIMIT] for x in d]


def short_card_descriptions(title_date: str, focus: list[dict], stalk: list[dict]) -> list[str]:
    """Card SHORT [RONIN 12/10]: stesse voci del long, riquadri rossi. Per lo short il lato giusto è SOTTO la media 65m,
    quindi quegli Stalk vengono per primi. Niente statistiche degli ETF di settore (sono pensate per il long)."""
    # nello short il gate "sma65" aperto vuol dire prezzo SOPRA la media 65m (lato sbagliato)
    dn = [r for r in stalk if above_sma65(r)]
    up = [r for r in stalk if not above_sma65(r)]

    def sect(title: str, rows: list[dict], lim: Optional[int]) -> str:
        if not rows:
            return f"**{title}**\n• none"
        blocks = [f"__{sec}__\n" + "\n".join(card_line(r, lim) for r in rr) for sec, rr in sector_groups(rows)]
        return f"**{title}**\n" + "\n\n".join(blocks)

    for f_lim, s_lim in ((None, None), (None, 70), (None, 45), (80, 30), (60, 0), (0, 0)):
        d = [f"**SHORT WATCHLIST — {title_date}**\n\n" + sect("SHORT FOCUS", focus, f_lim),
             sect(f"SHORT STALK — below 65m {_ma65()} ({len(dn)})", dn, s_lim),
             sect(f"SHORT STALK — above 65m {_ma65()} ({len(up)})", up, s_lim)]
        if all(len(x) <= CARD_LIMIT for x in d):
            return d
    return [x[:CARD_LIMIT] for x in d]


def short_tv_txt(focus, stalk_below, stalk_above) -> str:
    """Sezioni short del txt TradingView, dopo quelle long nella stessa riga [RONIN 12/10]."""
    out = ["###SHORT FOCUS", *[tv_symbol(t, e) for t, e in focus],
           f"###SHORT STALK BELOW 65m {_ma65()}", *[tv_symbol(t, e) for t, e in stalk_below],
           f"###SHORT STALK ABOVE 65m {_ma65()}", *[tv_symbol(t, e) for t, e in stalk_above]]
    return ",".join(out)


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
        out += [f"###STALK ABOVE 65m {_ma65()}", *[tv_symbol(t, e) for t, e in stalk],
                f"###STALK BELOW 65m {_ma65()}", *[tv_symbol(t, e) for t, e in stalk_below]]
    return ",".join(out)
