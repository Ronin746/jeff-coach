"""Scan pre-market (~08:45 di New York): gap-up ≥5% tra i titoli liquidi, aggiunti alla card con PATCH.

Uso: python -m jeffcoach.premarket [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import time as dtime

from . import config as C
from . import data as D
from .calendar_us import is_session, now_et
from .discord import post_card
from .output import card_embeds, write_atomic

log = logging.getLogger("jeffcoach.premarket")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="anche fuori dalla finestra 08:00-09:25 di New York")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = now_et()
    today = n.date()
    if not is_session(today) or (not a.force and not (dtime(8, 0) <= n.time() <= dtime(9, 25))):
        print(json.dumps({"skipped": True, "reason": "fuori finestra pre-market"}))
        return 0
    work = C.LISTS / f"work_{today}"
    det_p = work / "detail.json"
    if not det_p.exists():
        print(json.dumps({"skipped": True, "reason": "lista di oggi non pronta"}))
        return 0
    if (work / "premarket.json").exists() and not a.force:
        print(json.dumps({"skipped": True, "reason": "già fatto"}))
        return 0
    det = json.loads(det_p.read_text(encoding="utf-8"))
    lists = json.loads((C.HISTORY / f"lists_{det['as_of']}.json").read_text(encoding="utf-8"))
    names = [t for t, v in lists.items() if v in ("Leading", "Mediocre")]
    theme_of = {}
    for r in det.get("themes", []):
        for t in r["members"]:
            theme_of.setdefault(t, r["theme"])
    bars = D.download_intraday(names, period="5d", interval="5m", prepost=True)
    out = []
    for t, b in bars.items():
        prev = b[b.index.date < today]
        cur = b[b.index.date == today]
        if not len(prev) or not len(cur):
            continue
        reg = prev[(prev.index.time >= dtime(9, 30)) & (prev.index.time < dtime(16, 0))]
        if not len(reg):
            continue
        pc, last = float(reg.Close.iloc[-1]), float(cur.Close.iloc[-1])
        g = (last / pc - 1) * 100
        if g >= C.PREMARKET_GAP_MIN:
            out.append({"ticker": t, "gap_pct": round(g, 1), "list": lists.get(t), "theme": theme_of.get(t)})
    out.sort(key=lambda x: -x["gap_pct"])
    out = out[:15]
    write_atomic(work / "premarket.json", out)
    card = {"embeds": card_embeds(det, out)}
    write_atomic(work / "card.json", card)
    res = post_card(today, a.dry_run)
    print(json.dumps({"gappers": [x["ticker"] for x in out], "card": res}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
