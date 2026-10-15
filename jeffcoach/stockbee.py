"""Market Monitor letto direttamente alla fonte: il Google Sheet pubblico di Stockbee [RONIN 15/10, Andrea].

NEL non calcola nulla: legge questo stesso foglio (stockbee.blogspot.com/p/mm.html). Leggendolo noi non dipendiamo
più dal repo di NEL. Le schede del foglio sono una per anno ("2026", "2025"...): si trovano dall'elenco pubblicato,
così a gennaio la scheda nuova entra da sola. Righe nello stesso formato di NEL (dalla seduta più recente).
"""
from __future__ import annotations

import csv
import io
import logging
import re
import urllib.request
from datetime import date
from typing import Optional

log = logging.getLogger("jeffcoach.stockbee")

SHEET_ID = "1O6OhS7ciA8zwfycBfGPbP2fWJnR0pn2UUvFZVDP9jpE"
PUBHTML = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/pubhtml"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/pub?gid={{gid}}&single=true&output=csv"

# intestazioni delle colonne del foglio -> nomi dei campi (gli stessi del file di NEL)
FIELDS = (
    ("up4", ("up 4%", "today")), ("down4", ("down 4%", "today")),
    ("ratio5", ("5 day", "ratio")), ("ratio10", ("10 day", "ratio")),
    ("up25q", ("up 25%", "quarter")), ("down25q", ("down 25%", "quarter")),
    ("up25m", ("up 25%", "month")), ("down25m", ("down 25%", "month")),
    ("up50m", ("up 50%", "month")), ("down50m", ("down 50%", "month")),
    ("up13d34", ("up 13%", "34 days")), ("down13d34", ("down 13%", "34 days")),
    ("universe", ("common stock",)), ("t2108", ("t2108",)),
)


def _get(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JeffCoach)"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def year_tabs() -> dict[int, str]:
    """{anno: gid} dalle schede pubblicate (solo quelle che si chiamano come un anno)."""
    html = _get(PUBHTML)
    out = {}
    for name, gid in re.findall(r'\{name: "(\d{4})", pageUrl: "[^"]*?gid=(\d+)', html):
        out[int(name)] = gid
    return out


def _num(v: str) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _date(v: str) -> Optional[str]:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*", v or "")
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _key(header: str) -> Optional[str]:
    h = re.sub(r"\s+", " ", header.lower()).replace("+", "").replace(" plus", "")
    h = re.sub(r"(\d+)% ?", r"\1% ", h)
    if h.strip() in ("s&p", "s&p 500", "spx"):
        return "sp"
    for k, words in FIELDS:
        if all(w in h for w in words):
            return k
    return None


def parse_csv(text: str) -> list[dict]:
    """Scheda nel formato attuale (una riga per seduta, intestazione 'Date' nelle prime righe)."""
    raw = list(csv.reader(io.StringIO(text)))
    hi = next((i for i, r in enumerate(raw[:12]) if r and r[0].strip().lower() == "date"), None)
    if hi is None:
        return []
    keys = [_key(h) for h in raw[hi]]
    out = []
    for r in raw[hi + 1:]:
        d = _date(r[0]) if r else None
        if not d:
            continue
        row = {"date": d}
        for i, k in enumerate(keys):
            if k and i < len(r):
                row[k] = _num(r[i])
        if row.get("up4") is not None and row.get("down4") is not None:
            out.append(row)
    return out


def fetch(years_back: int = 1) -> list[dict]:
    """Righe dell'anno in corso e del precedente, dalla seduta più recente."""
    tabs = year_tabs()
    if not tabs:
        raise RuntimeError("foglio Stockbee: nessuna scheda anno")
    by = {}
    for y in sorted(tabs)[-(years_back + 1):]:
        for r in parse_csv(_get(CSV_URL.format(gid=tabs[y]))):
            by[r["date"]] = r
    rows = [by[d] for d in sorted(by, reverse=True)]
    if len(rows) < 20:
        raise RuntimeError(f"foglio Stockbee incompleto ({len(rows)} righe)")
    return rows
