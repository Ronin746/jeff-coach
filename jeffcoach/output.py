"""Formati di uscita: scritture atomiche, card Discord, txt TradingView."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

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


def _f(v, fmt):
    return "n/a" if v is None else fmt.format(v)


def focus_line(r: dict) -> str:
    """• **SNDK** — res 1152 (EMA21↓ + AVWAP SH) · +1.2% away · ADR 6.1% · Memory · B"""
    word = "sup" if r["side"] == "long" else "res"
    mem = " + ".join(_short(m) for m in (r.get("level_members") or [])[:3])
    s = (f"• **{r['ticker']}** — {word} {_f(r.get('level'), '{:.2f}')} ({mem}) · {_f(r.get('dist_pct'), '{:.1f}%')} away"
         f" · ADR {_f(r.get('adr'), '{:.1f}%')}")
    if r.get("theme"):
        s += f" · {r['theme']}"
    if r.get("grade"):
        s += f" · {r['grade']}"
    if r.get("note"):
        s += f" · {r['note']}"
    return s


def _short(name: str) -> str:
    return (name.replace("AVWAP swing low", "AVWAP SL").replace("AVWAP swing high", "AVWAP SH")
            .replace("AVWAP volume day", "AVWAP vol").replace("swing high", "SH").replace("swing low", "SL")
            .split(" 20")[0])


from . import config as C
from .config import BIAS_EN, PHASE_EN
from .edges import edges_text
MESSAGE_LIMIT = 5900          # Discord: 6000 caratteri per messaggio, tutti gli embed insieme
BIAS_COLOR = {"LONG": 0x2ECC71, "SHORT": 0xE74C3C}       # long bordo verde, short bordo rosso [RONIN 13/10]
SIDE_COLOR = {"long": 0x2ECC71, "short": 0xE74C3C}
FERMO_COLOR = 0x95A5A6                                     # testata con bias FERMO
CARD_THEMES_COLOR = 0x3498DB                               # messaggio dei temi [RONIN 14/10]
MIXED_COLOR = 0xF1C40F                                     # testata con bias MISTO (long e short selettivi)
MISSING_EN = {"confluence": "no confluence level within reach", "not_extended_sma50": "more than 6 ATR from the SMA50", "linear_trend": "choppy trend (low R²)", "not_stretched": "too stretched from the EMA9", "weekly_ema9": "wrong side of the weekly EMA9", "trend_tf": "wrong side of the daily 50 EMA", "not_extended": "extended from the daily EMA9",
              "below_ema9": "still above the daily EMA9", "earnings": "earnings inside the window",
              "list": "not in the right list", "trend": "EMA9/21 not rising", "liquid": "liquidity", "adr": "ADR too low",
              "weekly_not_healthy": "weekly still healthy", "above_ema9": "still below the daily EMA9", "no_streak": "4+ days in a row in the trade direction", "weekly_healthy": "weekly not healthy", "no_strong_candle": "strong candle yesterday",
              "strong_level": "no strong resistance (EMA21/50, swing-high AVWAP, gap)", "weak_sector": "sector too strong to short"}


def level_text(r: dict) -> str:
    """'sup `181.20` 1.4% away · EMA21 + AVWAP SL + SH'"""
    if r.get("level") is None:
        return "no level"
    word = "sup" if r["side"] == "long" else "res"
    mem = members_text(r.get("level_members") or [])
    s = f"{word} `{r['level']:.2f}` {_f(r.get('dist_pct'), '{:.1f}%')} away"
    return s + (f" · {mem}" if mem else "")


def members_text(members, k: int = 3) -> str:
    """'2× AVWAP SL + EMA21': componenti del livello senza ripetizioni."""
    if isinstance(members, str):
        members = [x.strip() for x in members.split(";") if x.strip()]
    out: list[str] = []
    cnt: dict[str, int] = {}
    for m in members:
        n = _short(m)
        if n not in cnt:
            out.append(n)
        cnt[n] = cnt.get(n, 0) + 1
    return " + ".join((f"{cnt[n]}× {n}" if cnt[n] > 1 else n) for n in out[:k])


def card_line(r: dict, note: Optional[str] = None, lim: Optional[int] = None, tag: str = "") -> str:
    """Una voce per titolo, come le card di Sydney, con le misure del metodo Martin:
    • **NVDA** — Leading · RS +8.2 · ADR 4.8% · sup `181.20` 1.4% away · EMA21 + AVWAP SL · Semis (attivo) · A · nota"""
    rs = r.get("rs21")
    parts = [r.get("list") or "", f"RS {rs:+.1f}" if rs is not None else "", f"ADR {_f(r.get('adr'), '{:.1f}%')}", level_text(r),
             edges_text(r, compact=True)]                       # multi-edge [RONIN 22/10]
    if r.get("theme"):
        ph = r.get("theme_phase")
        parts.append(r["theme"] + (f" ({PHASE_EN.get(ph, ph)})" if ph else ""))
    if r.get("grade"):
        parts.append(f"**{r['grade']}**")
    txt = note if note is not None else (r.get("note") or "")
    if lim is not None and len(txt) > lim:
        txt = (txt[:max(lim - 1, 0)].rstrip() + "…") if lim else ""
    if txt:
        parts.append(txt)
    if tag:                      # sempre visibile, anche quando le note si accorciano
        parts.append(tag)
    return f"• **{r['ticker']}** — " + " · ".join(p for p in parts if p)


def focus_line(r: dict) -> str:
    return card_line(r)


def _stalk_note(r: dict) -> str:
    if r.get("demoted"):
        return "demoted in review" + (f": {r['note']}" if r.get("note") else "")
    parts = [r.get("note") or "", f"earnings {r['earnings'][5:]}" if r.get("earnings") else ""]
    return " · ".join(p for p in parts if p)


def card_embeds(d: dict, premarket: Optional[list[dict]] = None) -> list[dict]:
    """Card nello stile di Sydney [RONIN 13/10]: un embed per sezione, una voce per titolo con misure e nota.
    FOCUS (lato del bias) · conteggio dei tracking · PREMARKET. Stalk, a un passo e potent non vanno su Discord:
    sono nel txt allegato (###TRACKING LONG / SHORT). Oltre i 6000 caratteri si accorciano le note."""
    bias = d["bias"]
    color = BIAS_COLOR.get(bias, MIXED_COLOR if bias == "MISTO" else FERMO_COLOR)
    want = {"LONG": "long", "SHORT": "short"}.get(bias)
    risk = d.get("risk_pct")
    head = [f"**MARTIN WATCHLIST — {d['session']}** (close {d['as_of']})",
            f"Bias **{BIAS_EN.get(bias, bias)}**" + (f" · risk `{risk:.2f}%` per trade" if risk is not None else "") + f" — {d['bias_why']}"]
    mm = d.get("market_monitor") if C.STOCKBEE_IN_CARD else None    # [19/10a] solo il modello di Martin
    if mm:
        if mm.get("read") == "pradeep":       # lettura di Pradeep Bonde: niente rapporti 5D/10D [RONIN 16/10]
            head.append(f"Market Monitor **{mm['state']}**"   # senza Breakouts work/fail [RONIN 16/10, Andrea]
                         + (" (own calc)" if mm.get("source") == "own" else "")
                        + f" · ±4% `{mm['up4']:.0f}` / `{mm['down4']:.0f}`"
                        + (f" · 25%Q `{mm['up25q']:.0f}` / `{mm['down25q']:.0f}`" if mm.get("up25q") is not None and mm.get("down25q") is not None else "")
                        + (f" · T2108 `{mm['t2108']:.0f}%`" if mm.get("t2108") is not None else "")
                        + (f" · 20% study `{mm['up20w']:.0f}`" if mm.get("up20w") is not None else ""))
        else:
            head.append(f"Market Monitor **{mm['state']}**" + (" (own calc)" if mm.get("source") == "own" else "") + f" · ±4% `{mm['up4']:.0f}` / `{mm['down4']:.0f}` · 5D `{mm['ratio5']:.2f}`"
                        f" · 10D `{mm['ratio10']:.2f}`" + (f" · T2108 `{mm['t2108']:.0f}%`" if mm.get("t2108") is not None else ""))
    mb = d.get("martin_breadth")
    if mb:                                     # breadth letta come Martin [RONIN 17/10]
        L, o, o1 = mb["lists"], mb.get("lists_5d"), mb.get("lists_1d")
        # variazione giornaliera e a 5 sedute di ogni lista [RONIN 17/10n, Andrea]
        def dl(k):
            parts = ([f"{L[k] - o1[k]:+d} 1d"] if o1 else []) + ([f"{L[k] - o[k]:+d} 5d"] if o else [])
            return f" ({', '.join(parts)})" if parts else ""
        pb = d.get("martin_pool")
        if pb and pb.get("lists"):              # liste del pool di Martin (~130 titoli) [RONIN 17/10o]
            PL_, p1, p5 = pb["lists"], pb.get("lists_1d"), pb.get("lists_5d")
            def dp(k):
                parts = ([f"{PL_[k] - p1[k]:+d} 1d"] if p1 else []) + ([f"{PL_[k] - p5[k]:+d} 5d"] if p5 else [])
                return f" ({', '.join(parts)})" if parts else ""
            lines = [f"**Breadth (Martin)** · Martin pool `{pb['n']}` names · above EMA21 (universe) `{mb['above21_pct']:.0f}%`"]
            lines += [f"- {k} `{PL_[k]}`{dp(k)}" for k in ("Leading", "Mediocre", "Lagging")]
            fd = pb.get("flow_daily") or []
            lines.append(f"Pool flow 5d `{pb['flow5']:+.1f}%` ({pb.get('up_5d', 0)} up, {pb.get('down_5d', 0)} down)"
                         + (" · daily " + " ".join(f"`{x:+.1f}%`" for x in fd[-5:]) if fd else ""))
            lines.append(f"Universe lists L `{L['Leading']}`{dl('Leading')} · M `{L['Mediocre']}`{dl('Mediocre')}"
                         f" · G `{L['Lagging']}`{dl('Lagging')}")
        else:
            lines = [f"**Breadth (Martin)** · above EMA21 `{mb['above21_pct']:.0f}%`"]
            lines += [f"- {k} `{L[k]}`{dl(k)}" for k in ("Leading", "Mediocre", "Lagging")]   # una lista per riga [17/10]
        ser = [] if (pb and pb.get("lists")) else (mb.get("lead_share_series") or [])
        if len(ser) >= 2:                      # quota Leading giorno per giorno [17/10k]
            lines.append("Leading share " + " → ".join(f"`{x:.0f}%`" for x in ser[-6:]))
        f5, fd = mb.get("flow5"), mb.get("flow_daily") or []
        if f5 and not (pb and pb.get("lists")):  # flusso tra le liste dell'universo [17/10m]
            lines.append(f"List flow 5d `{f5['net']:+d}` pts (`{f5['pct']:+.1f}%`: {f5['up']} up, {f5['down']} down)"
                         + (" · daily " + " ".join(f"`{x:+.1f}%`" for x in fd[-5:]) if fd else ""))
        md = mb.get("mediocre") or {}
        if md.get("from_leading") is not None and not (pb and pb.get("lists")):     # Mediocre sul totale e passaggi a 5 sedute [17/10l]
            lines.append(f"Mediocre `{md['share']:.0f}%` of all ({md['growth_pct']:+.0f}% 5d) · in: from L `{md['from_leading']}`"
                         f" from G `{md['from_lagging']}` · out: to L `{md['to_leading']}` to G `{md['to_lagging']}`")
        iq = mb.get("iwm_vs_qqq_21d")
        lines.append((f"IWM vs QQQ 1M `{iq:+.1f}` pts · " if iq is not None else "")
                     + f"IWM {'>' if mb['iwm_above9'] else '<'}9 {'>' if mb['iwm_above21'] else '<'}21"
                     + f" · mega caps above 9 `{mb['mega_above9']}/{mb['mega_n']}`"
                     + f" · leaders below 9 `{mb['leaders_below9']}/{mb['leaders_n']}` below 21 `{mb['leaders_below21']}/{mb['leaders_n']}`")
        st = ", ".join(f"{t} {n}" for t, n in mb.get("scan_themes") or [])
        lines.append(f"Scan +4%: `{mb['scan_n']}` names" + (f" · together: {st}" if st else ""))
        head.append("\n".join(lines))
    sf = d.get("signal_feedback") if C.FEEDBACK_IN_CARD else None      # [19/10b, Andrea] tolto dalla card
    if sf and any((sf.get(k) or {}).get("n") for k in ("long", "short")):
        part = lambda k: (f"{k} `{sf[k]['hit1r']}/{sf[k]['n']}` ≥1R · `{sf[k]['fast_stop']}` stopped fast · `{sf[k]['sum_r']:+.1f}R`"
                          if sf[k]["n"] else f"{k} n/a")
        head.append(f"**Signal feedback** (last {max(sf['long']['n'], sf['short']['n'])}): {part('long')} | {part('short')}")
    if d.get("themes_line"):
        head.append(f"Themes: {d['themes_line']}")
    if d.get("mm_hist") and C.STOCKBEE_IN_CARD:   # ultimi 20 giorni di ±4% sotto il regime [RONIN 16/10]
        from .breadth_chart import table_20d
        tb = table_20d(d["mm_hist"])
        if tb:
            head.append("**±4% last 20 days** (▲ buying · ▼ selling)\n" + tb)
    chart = d.get("breadth_chart")             # grafico studio 20% e T2108, allegato alla card

    rev = d.get("reversal") if C.STOCKBEE_IN_CARD else None
    if rev:                                    # prime 2 sedute dopo l'inversione del flusso ±4% [RONIN 16/10]
        head.insert(2, f"⚠️ **POTENTIAL TREND REVERSAL** — ±4% flow turned to **{rev['direction']}** on {rev['date']} "
                       f"(day {rev['day']} of {C.REVERSAL_DAYS}): Focus long and short")

    def build(note_lim: Optional[int], max_rows: Optional[int]) -> list[dict]:
        if rev:
            embeds = [{"description": "\n".join(head), "color": MIXED_COLOR}]
            for s in ("long", "short"):
                rows = [r for r in d["focus"] if r["side"] == s]
                embeds.append({"description": f"**FOCUS {s.upper()} — potential trend reversal**\n"
                               + ("\n".join(card_line(r, None, note_lim) for r in rows) or "• none"), "color": SIDE_COLOR[s],
                               "_rows": [r["ticker"] for r in rows]})
        elif bias == "MISTO":           # long e short selettivi: un riquadro per lato, verde e rosso [RONIN 13/10]
            embeds = [{"description": "\n".join(head), "color": color}]
            for s in ("long", "short"):
                rows = [r for r in d["focus"] if r["side"] == s]
                embeds.append({"description": f"**FOCUS {s.upper()} — mixed market, best only**\n"
                               + ("\n".join(card_line(r, None, note_lim) for r in rows) or "• none"), "color": SIDE_COLOR[s],
                               "_rows": [r["ticker"] for r in rows]})
        else:
            fo_title = f"FOCUS {bias}" if want else "FOCUS — none (bias FLAT: no entry triggers)"
            fo = "\n".join(card_line(r, None, note_lim) for r in d["focus"]) or ("• none" if want else "")
            embeds = [{"description": "\n".join(head), "color": color},
                      {"description": f"**{fo_title}**" + (f"\n{fo}" if fo else ""), "color": color,
                       "_rows": [r["ticker"] for r in d["focus"]]}]
        aw = d.get("counter_focus") or []
        for s in ("long", "short"):               # lato opposto al regime: sempre i migliori [RONIN 13/10]
            rows = [r for r in aw if r["side"] == s]
            if rows:
                embeds.append({"description": f"**FOCUS {s.upper()} — top quality, against the regime (alerts only, not traded)**\n"
                               + "\n".join(card_line(r, None, note_lim) for r in rows), "color": SIDE_COLOR[s],
                               "_rows": [r["ticker"] for r in rows]})
        tl, ts = d.get("tracking_long") or [], d.get("tracking_short") or []
        if tl or ts:                 # i tracking non vanno nella card: solo nel txt allegato [RONIN 13/10]
            fw = len(d.get("fakeout_watch") or [])
            embeds[1 if len(embeds) > 1 else 0]["description"] += (f"\n\nTracking: {len(tl)} long · {len(ts)} short — in the attached TradingView file"
                + (f"\nFailed breakout/breakdown watch: {fw} tracking names alert only on a failed breakdown (long) or failed breakout (short) at the level" if fw else ""))
        tail = []
        if premarket:
            tail.append("**PREMARKET GAPS**\n" + "\n".join(
                f"• **{p['ticker']}** `{p['gap_pct']:+.1f}%` · {p.get('list') or ''}" + (f" · {p['theme']}" if p.get("theme") else "")
                for p in premarket))
        if tail:
            embeds.append({"description": "\n\n".join(tail), "color": SIDE_COLOR["long"]})   # potent e gap-up: lato long
        if chart:                               # il grafico chiude la parte del regime, prima dei Focus
            embeds[0]["image"] = {"url": f"attachment://{chart}"}
        return embeds

    charts = d.get("focus_charts") or {}
    for note_lim, max_rows in ((None, None), (60, None), (30, 25), (0, 15), (0, 8), (0, 4)):
        e = build(note_lim, max_rows)
        if sum(len(x["description"]) for x in e) <= MESSAGE_LIMIT and all(len(x["description"]) <= CARD_LIMIT for x in e):
            return with_focus_charts(e, charts)
    for x in e:
        x["description"] = x["description"][:CARD_LIMIT]
    return with_focus_charts(e[:4], charts)


def with_focus_charts(embeds: list[dict], charts: dict[str, str]) -> list[dict]:
    """Grafici dei Focus sotto il loro riquadro [ANDREA 28/10, multi-edge]: gallerie di Discord da 4 immagini (riquadri
    con lo stesso url uniti in uno; aprendo un'immagine si scorre con le frecce). Il primo grafico va nel riquadro del
    testo, così la galleria sta subito sotto i nomi. Senza grafici la card resta com'era."""
    out = []
    for e in embeds:
        tk = e.pop("_rows", None) or []
        out.append(e)
        fns = [(t, charts[t]) for t in tk if t in charts]
        for k in range(0, len(fns), 4):
            grp = fns[k:k + 4]
            url = f"https://www.tradingview.com/symbols/{grp[0][0]}/"
            first = e if k == 0 and "image" not in e else None
            for j, (t, fn) in enumerate(grp):
                if j == 0 and first is not None:
                    first["url"], first["image"] = url, {"url": f"attachment://{fn}"}
                else:
                    out.append({"url": url, "color": e.get("color"), "image": {"url": f"attachment://{fn}"}})
    return out


def card_description(d: dict, premarket: Optional[list[dict]] = None) -> str:
    """Compatibilità: tutta la card in un testo."""
    return "\n\n".join(x["description"] for x in card_embeds(d, premarket) if x.get("description"))


def tv_symbol(t: str, exch: Optional[str]) -> str:
    return f"{TV_EXCHANGE.get(exch or '', 'NASDAQ' if not exch else exch)}:{t.replace('-', '.')}"


def tv_txt(sections: list[tuple[str, list[tuple[str, Optional[str]]]]]) -> str:
    """Import TradingView a sezioni [RONIN 13/10]: ###FOCUS LONG, ###FOCUS SHORT, ###TRACKING LONG, ###TRACKING SHORT.
    Le sezioni vuote non si scrivono."""
    out: list[str] = []
    for title, rows in sections:
        if rows:
            out += [f"###{title}", *[tv_symbol(t, e) for t, e in rows]]
    return ",".join(out)


def themes_embed(d: dict) -> dict:
    """Secondo messaggio sotto la card [RONIN 14/10]: temi leading in uptrend e in breakdown. Score, 1M (rendimento a
    21 sedute, media degli ETF), vs S&P e Leading/Breaking sono degli ETF del tema [RONIN 16/10]; tra parentesi i
    titoli del tema in ordine di punteggio (stesso metodo degli ETF: performance vs SPY + livelli, dal 17/10) (gli ETF solo per i temi senza titoli)."""
    tm = d.get("themes_msg") or {}
    tot = tm.get("total", 0)
    pct = lambda v: "n/a" if v is None else f"{v:+.1f}%"

    def line(x: dict) -> str:
        tick = f" ({', '.join(x['tickers'])})" if x.get("tickers") else ""
        stg = f" · {x['stage']}" if x.get("stage") else ""
        lv = f" · {x['etf_lv']}" if x.get("etf_lv") else ""          # livelli dell'ETF del tema [RONIN 17/10]
        return f"• {x['theme']} — score {x['score']}{stg} · 1M {pct(x['ret21'])} · vs S&P {pct(x['vs_spy'])}{lv}{tick}"

    out = [f"**THEMES — {d['session']}**", "", f"**• Leading in uptrend ({tm.get('leading_n', 0)} of {tot})**"]
    out += [line(x) for x in tm.get("leading") or []] or ["• none"]
    out += ["", f"**• Breaking down ({tm.get('breaking_n', 0)} of {tot})**"]
    out += [line(x) for x in tm.get("breaking") or []] or ["• none"]
    text = "\n".join(out)
    return {"description": text[:4000], "color": CARD_THEMES_COLOR}


def themes_embeds(d: dict) -> list[dict]:
    """Messaggio dei temi con i basket di Lone Stock Trader [RONIN 21/10, Andrea]: in testa il grafico RS settimana /
    RS mese dei basket (allegato themes_rs.png), poi la classifica complessiva sul 7-factor (media equal-weight del
    Final_Score dei titoli del basket), poi Leading in uptrend e Breaking down come prima. Senza basket LST: il vecchio
    messaggio a un solo riquadro."""
    tm = d.get("themes_msg") or {}
    if tm.get("source") != "lst":
        return [themes_embed(d)]
    pct = lambda v: "n/a" if v is None else f"{v:+.1f}%"
    tot = tm.get("total", 0)

    def rk_line(x: dict, k: int) -> str:
        d5 = f" ({x['d5']:+.0f} 5d)" if x.get("d5") is not None else ""
        tick = f" ({', '.join(x['tickers'][:k])})" if x.get("tickers") and k else ""
        q = f" Q `{x['rs_q']:.0f}`" if x.get("rs_q") is not None else ""
        return (f"`{x['rank']:>2}` **{x['theme']}** — 7F `{x['score']}`{d5} · W `{x['rs_w']:.0f}` M `{x['rs_m']:.0f}`{q} "
                f"{x['quadrant']} · 1W {pct(x.get('ret1w'))} 1M {pct(x.get('ret1m'))}{tick}")

    def line(x: dict, k: int) -> str:
        tick = f" ({', '.join(x['tickers'][:k])})" if x.get("tickers") and k else ""
        return f"• {x['theme']} — 7F {x['score']} · 1M {pct(x['ret21'])} · vs S&P {pct(x['vs_spy'])}{tick}"

    def build(k_rank: int, k_lb: int, rows_lb: int) -> list[dict]:
        head = f"**THEMES — {d['session']}**" + (f" · groups as of {tm['baskets_fetched']}" if tm.get("baskets_fetched") else "")
        charts = d.get("themes_charts") or []
        e0 = {"description": head + "\nWeek RS (x) vs Month RS (y) · percentile among all groups", "color": CARD_THEMES_COLOR}
        if "themes_rs.png" in charts:
            e0["image"] = {"url": "attachment://themes_rs.png"}
        top = [e0]
        if "themes_rs_3m.png" in charts:           # seconda immagine: RS mese / trimestre
            top.append({"description": "Month RS (x) vs Quarter RS (y) · percentile among all groups", "color": CARD_THEMES_COLOR,
                        "image": {"url": "attachment://themes_rs_3m.png"}})
        rk = [f"**Overall ranking — 7-factor, equal-weight of members ({tm.get('ranked_n', 0)} groups)**"]
        rk += [rk_line(x, k_rank) for x in tm.get("ranking") or []] or ["• none"]
        if tm.get("bottom"):
            rk += ["", "**Weakest**"] + [rk_line(x, k_rank) for x in tm["bottom"]]
        lb = [f"**• Leading in uptrend ({tm.get('leading_n', 0)} of {tot})**"]
        lb += [line(x, k_lb) for x in (tm.get("leading") or [])[:rows_lb]] or ["• none"]
        lb += ["", f"**• Breaking down ({tm.get('breaking_n', 0)} of {tot})**"]
        lb += [line(x, k_lb) for x in (tm.get("breaking") or [])[:rows_lb]] or ["• none"]
        return top + [{"description": "\n".join(rk)[:CARD_LIMIT], "color": CARD_THEMES_COLOR},
                {"description": "\n".join(lb)[:CARD_LIMIT], "color": CARD_THEMES_COLOR}]

    if not C.CARD_THEMES_RANKING:       # [ANDREA 28/10] messaggio più semplice: restano solo i due grafici RS
        return build(0, 0, 0)[:-2]
    for k_rank, k_lb, rows_lb in ((5, 8, 10), (4, 6, 10), (3, 5, 8), (3, 3, 6), (0, 0, 5)):
        e = build(k_rank, k_lb, rows_lb)
        if sum(len(x["description"]) for x in e) <= MESSAGE_LIMIT:
            return e
    return e

