"""Discord: un solo canale per card e alert, bot "Sydney" (webhook di Sydney di jeff-coach) [RONIN 13/10; jeff-coach 28/10].

Regole riprese da jeff-coach: un embed per messaggio, niente menzioni, card una volta al giorno con PATCH
sulle correzioni, txt TradingView allegato. Il webhook non si stampa mai e non va nel repo (.env / secret).

Uso:
  python -m jeffcoach.discord card [--session YYYY-MM-DD] [--dry-run]
  python -m jeffcoach.discord test          # un messaggio di prova
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

from . import config as C
from .calendar_us import today_rome
from .output import write_atomic

log = logging.getLogger("jeffcoach.discord")


def load_env_file() -> None:
    """Legge .env nella cartella del repo (server), senza stamparlo."""
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)


def webhook() -> Optional[str]:
    load_env_file()
    for k in C.WEBHOOK_ENV:
        v = os.environ.get(k)
        if v and v.startswith("http"):
            return v.strip()
    return None


def _request(url: str, method: str, body: bytes, ctype: str) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": ctype, "User-Agent": "JeffCoach/1.0"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        raw = r.read()
        d = json.loads(raw) if raw else {}
        return {"ok": True, "status": r.status, "message_id": d.get("id")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode(errors="replace")[:300]}
    except Exception as e:
        return {"ok": False, "status": None, "error": type(e).__name__}


def _multipart(payload: dict, filename: str, content: bytes, extra: Optional[list] = None) -> tuple[bytes, str]:
    """payload_json + file principale (txt) + eventuali altri file [(nome, byte, content-type)]."""
    b = uuid.uuid4().hex
    files = [(filename, content, "image/png" if filename.endswith(".png") else "text/plain")] + list(extra or [])
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode()
            + json.dumps(payload).encode())
    for k, (fn, data, ct) in enumerate(files):
        body += (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"files[{k}]\"; filename=\"{fn}\"\r\nContent-Type: {ct}\r\n\r\n".encode()
                 + data)
    body += f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def split_card(embeds: list[dict], limit_embeds: int = 10, limit_files: int = 10, limit_chars: int = 5900,
               first_files: int = 1) -> list[list[dict]]:
    """Divide la card in più messaggi quando non sta in uno [ANDREA 28/10, grafici dei Focus del multi-edge]: Discord
    accetta 10 riquadri, 10 file e 6000 caratteri per messaggio. Un blocco = un riquadro con testo e i riquadri di sole
    immagini che lo seguono (la galleria dei suoi grafici): un blocco non si spezza, salvo che da solo superi i limiti.
    `first_files`: file già nel primo messaggio (il txt di TradingView)."""
    files = lambda e: 1 if "attachment://" in json.dumps(e.get("image") or {}) else 0
    blocks: list[list[dict]] = []
    for e in embeds:
        if e.get("description") or not blocks:
            blocks.append([e])
        else:
            blocks[-1].append(e)
    msgs: list[list[dict]] = [[]]
    n_e = n_f = n_c = 0
    n_f = first_files
    for b in blocks:
        be, bf, bc = len(b), sum(files(e) for e in b), sum(len(e.get("description") or "") for e in b)
        if msgs[-1] and (n_e + be > limit_embeds or n_f + bf > limit_files or n_c + bc > limit_chars):
            msgs.append([])
            n_e = n_f = n_c = 0
        for e in b:                         # un blocco troppo grande da solo si spezza riquadro per riquadro
            ef = files(e)
            if msgs[-1] and (n_e + 1 > limit_embeds or n_f + ef > limit_files):
                msgs.append([])
                n_e = n_f = n_c = 0
            msgs[-1].append(e)
            n_e, n_f, n_c = n_e + 1, n_f + ef, n_c + len(e.get("description") or "")
    return [m for m in msgs if m]


def post_card(session: date, dry_run: bool = False, if_changed: bool = False) -> dict:
    """Card del giorno: POST la prima volta, poi PATCH sugli stessi messaggi.
    Con if_changed non fa niente se la card è identica a quella già pubblicata (cron doppi, push della revisione).
    Di solito un messaggio; con i grafici dei Focus (multi-edge) la card continua in altri messaggi, uno dopo l'altro:
    il txt di TradingView va nel primo, ogni immagine nel messaggio del suo riquadro [ANDREA 28/10]."""
    import hashlib
    import re
    work = C.LISTS / f"work_{session}"
    card = json.loads((work / "card.json").read_text(encoding="utf-8"))
    card_hash = hashlib.sha256(json.dumps(card, sort_keys=True).encode()).hexdigest()[:16]
    txt = C.LISTS / f"watchlist_{session}.txt"
    fname = txt.name
    msgs = split_card(card.get("embeds") or [])
    bodies = []
    for k, emb in enumerate(msgs):
        refs = list(dict.fromkeys(re.findall(r"attachment://([\w.\-]+)", json.dumps(emb))))
        extra = [(fn, (work / fn).read_bytes(), "image/png") for fn in refs if (work / fn).exists()]
        for _, data, _ in extra:
            card_hash = hashlib.sha256((card_hash + hashlib.sha256(data).hexdigest()).encode()).hexdigest()[:16]
        payload = {"username": C.BOT_NAME, "allowed_mentions": {"parse": []}, "embeds": emb}
        if k == 0:
            payload["attachments"] = [{"id": 0, "filename": fname}] + [{"id": j + 1, "filename": f[0]} for j, f in enumerate(extra)]
            bodies.append(_multipart(payload, fname, txt.read_bytes(), extra))
        else:
            payload["attachments"] = [{"id": j, "filename": f[0]} for j, f in enumerate(extra)]
            bodies.append(_multipart(payload, extra[0][0], extra[0][1], extra[1:]) if extra
                          else (json.dumps(payload).encode(), "application/json"))
    state_p = work / "discord_post.json"
    prev = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    if if_changed and prev.get("card_hash") == card_hash:
        return {"ok": True, "skipped": "card invariata"}
    old_ids = prev.get("message_ids") or ([prev["message_id"]] if prev.get("message_id") else [])
    if dry_run:
        return {"dry_run": True, "would": "PATCH" if old_ids else "POST", "messages": len(bodies),
                "embeds": [len(m) for m in msgs], "bytes": sum(len(b) for b, _ in bodies)}
    url = webhook()
    if not url:
        return {"ok": False, "error": "webhook non configurato"}
    base = url.split("?")[0]
    ids, res = [], {}
    for k, (body, ctype) in enumerate(bodies):
        if k < len(old_ids):
            r = _request(f"{base}/messages/{old_ids[k]}", "PATCH", body, ctype)
            r["method"] = "PATCH"
            r.setdefault("message_id", old_ids[k])
        else:
            r = _request(url + ("&" if "?" in url else "?") + "wait=true", "POST", body, ctype)
            r["method"] = "POST"
        if k == 0:
            res = r
        if not r.get("ok"):
            res = {**r, "failed_message": k}
            break
        ids.append(r.get("message_id"))
    else:
        for mid in old_ids[len(bodies):]:           # card più corta di prima: via i messaggi in più
            _request(f"{base}/messages/{mid}", "DELETE", b"", "application/json")
    if res.get("ok") and ids:
        res["messages"] = len(ids)
        write_atomic(state_p, {**prev, **{k: v for k, v in res.items() if v is not None and k != "error"},
                               "message_id": ids[0], "message_ids": ids, "session": str(session), "card_hash": card_hash})
    return res


def post_themes(session: date, dry_run: bool = False, if_changed: bool = False) -> dict:
    """Messaggio dei temi sotto la card [RONIN 14/10]: POST la prima volta, poi PATCH sullo stesso messaggio."""
    import hashlib
    work = C.LISTS / f"work_{session}"
    src = work / "themes_card.json"
    if not src.exists():
        return {"ok": False, "skipped": "nessun messaggio dei temi"}
    card = json.loads(src.read_text(encoding="utf-8"))
    h = hashlib.sha256(json.dumps(card, sort_keys=True).encode()).hexdigest()[:16]
    for fn in ("themes_rs.png", "themes_rs_3m.png"):
        if (work / fn).exists():
            h = hashlib.sha256((h + hashlib.sha256((work / fn).read_bytes()).hexdigest()).encode()).hexdigest()[:16]
    state_p = work / "discord_themes.json"
    prev = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    if if_changed and prev.get("card_hash") == h:
        return {"ok": True, "skipped": "temi invariati"}
    if dry_run:
        return {"dry_run": True, "would": "PATCH" if prev.get("message_id") else "POST"}
    url = webhook()
    if not url:
        return {"ok": False, "error": "webhook non configurato"}
    pngs = [work / fn for fn in ("themes_rs.png", "themes_rs_3m.png")      # mappa dei temi, due immagini [RONIN 21/10]
            if (work / fn).exists() and f"attachment://{fn}" in json.dumps(card)]
    if pngs:
        payload = {"username": C.BOT_NAME, "allowed_mentions": {"parse": []}, **card,
                   "attachments": [{"id": k, "filename": p.name} for k, p in enumerate(pngs)]}
        body, ctype = _multipart(payload, pngs[0].name, pngs[0].read_bytes(),
                                 [(p.name, p.read_bytes(), "image/png") for p in pngs[1:]])
    else:
        body, ctype = json.dumps({"username": C.BOT_NAME, "allowed_mentions": {"parse": []}, **card}).encode(), "application/json"
    base = url.split("?")[0]
    if prev.get("message_id"):
        res = _request(f"{base}/messages/{prev['message_id']}", "PATCH", body, ctype)
        res["method"] = "PATCH"
        res.setdefault("message_id", prev["message_id"])
    else:
        res = _request(url + ("&" if "?" in url else "?") + "wait=true", "POST", body, ctype)
        res["method"] = "POST"
    if res.get("ok"):
        write_atomic(state_p, {**prev, **{k: v for k, v in res.items() if v is not None and k != "error"},
                               "session": str(session), "card_hash": h})
    return res


def send_alert(title: str, body: str, kind: str = "info", dry_run: bool = False, image: Optional[bytes] = None,
               image2: Optional[bytes] = None) -> dict:
    """Alert intraday come quelli di Sydney: un embed, niente menzioni; con image (PNG) il grafico va dentro l'embed,
    con image2 una seconda immagine in un secondo embed (grafico dell'ETF del gruppo) [RONIN 28/10].
    Se le immagini danno problemi l'alert parte senza."""
    if dry_run:
        log.info("ALERT (dry) %s | %s | grafico %s%s", title, body.replace("\n", " · "), f"{len(image)} byte" if image else "no",
                 f" + ETF {len(image2)} byte" if image2 else "")
        return {"sent": True, "dry_run": True}
    url = webhook()
    if not url:
        return {"sent": False, "reason": "webhook non configurato"}
    emb = {"title": title, "description": body, "color": C.ALERT_COLOR.get(kind, C.ALERT_COLOR["info"])}
    payload = {"username": C.BOT_NAME, "allowed_mentions": {"parse": []}, "embeds": [emb]}
    res = None
    if image:
        emb["image"] = {"url": "attachment://chart.png"}
        files = [("chart.png", image)]
        if image2:
            payload["embeds"].append({"color": emb["color"], "image": {"url": "attachment://etf.png"}})
            files.append(("etf.png", image2))
        payload["attachments"] = [{"id": i, "filename": fn} for i, (fn, _) in enumerate(files)]
        b = uuid.uuid4().hex
        data = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode()
                + json.dumps(payload).encode())
        for i, (fn, img) in enumerate(files):
            data += (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; filename=\"{fn}\"\r\nContent-Type: image/png\r\n\r\n".encode()
                     + img)
        data += f"\r\n--{b}--\r\n".encode()
        res = _request(url, "POST", data, f"multipart/form-data; boundary={b}")
        if not res.get("ok"):
            emb.pop("image", None)
            payload["embeds"] = [emb]
            payload.pop("attachments", None)
            res = None
    if res is None:
        res = _request(url, "POST", json.dumps(payload).encode(), "application/json")
    return {"sent": bool(res.get("ok")), "status": res.get("status"), "reason": res.get("error")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["card", "test"])
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--if-changed", action="store_true")
    a = ap.parse_args(argv)
    if a.what == "test":
        print(json.dumps(send_alert(f"{C.BOT_NAME} · test", "Jeff Coach (multi-edge) is connected to this channel.", "info", a.dry_run)))
        return 0
    s = date.fromisoformat(a.session) if a.session else today_rome()
    res = post_card(s, a.dry_run, a.if_changed)
    if res.get("ok") or res.get("dry_run"):          # temi subito sotto la card [RONIN 14/10]
        res["themes"] = post_themes(s, a.dry_run, a.if_changed)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
