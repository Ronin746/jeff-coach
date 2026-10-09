"""Discord: card della watchlist (webhook card) e alert intraday (webhook alert).

Regole [RONIN 04/10, 06/10]: un solo messaggio, un solo embed, niente content, niente menzioni,
niente code fence; txt TradingView allegato; correzioni dello stesso giorno = PATCH sullo stesso messaggio.
Gli URL dei webhook non si stampano mai. I webhook di Remy non si usano mai.

Uso:
  python -m jeffcoach.discord card [--session YYYY-MM-DD] [--dry-run]
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
from typing import Any, Optional

from . import config as C
from .calendar_us import today_rome
from .output import write_atomic

log = logging.getLogger("jeffcoach.discord")


def load_webhook(keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k in C.FORBIDDEN_WEBHOOK_ENV:
            return None
    for k in keys:
        v = os.environ.get(k)
        if v and v.startswith("http"):
            return v.strip()
    try:
        data = json.loads(C.SECRETS_FILE.read_text(encoding="utf-8"))
        for k in keys:
            v = (data.get("card") or {}).get(k) or data.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v.strip()
    except Exception:
        pass
    return None


def _request(url: str, method: str, body: bytes, ctype: str) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": ctype, "User-Agent": "JeffCoach/2.0"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        raw = r.read()
        d = json.loads(raw) if raw else {}
        att = d.get("attachments") or []
        return {"ok": True, "status": r.status, "message_id": d.get("id"), "channel_id": d.get("channel_id"),
                "file_url": att[0].get("url") if att else None}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode(errors="replace")[:400]}
    except Exception as e:
        return {"ok": False, "status": None, "error": type(e).__name__}


def _multipart(payload: dict, filename: str, content: bytes) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode()
            + json.dumps(payload).encode()
            + f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\nContent-Type: text/plain\r\n\r\n".encode()
            + content + f"\r\n--{b}--\r\n".encode())
    return body, f"multipart/form-data; boundary={b}"


def _split_embeds(embeds: list[dict], limit: int = 6000) -> list[list[dict]]:
    """Discord: al massimo 6000 caratteri di testo per messaggio. I riquadri che non ci stanno vanno nel messaggio dopo."""
    out, cur, n = [], [], 0
    for e in embeds:
        k = len(e.get("description") or "") + len(e.get("title") or "")
        if cur and n + k > limit:
            out.append(cur)
            cur, n = [], 0
        cur.append(e)
        n += k
    if cur:
        out.append(cur)
    return out


def post_card(session: date, dry_run: bool = False) -> dict:
    """Card (riquadri) con il file txt per TradingView allegato al primo messaggio [RONIN 09/10]. Se la card supera
    i 6000 caratteri di un messaggio, i riquadri in più vanno in un messaggio subito sotto. Stesso giorno: si
    correggono gli stessi messaggi, mai post nuovi (tranne la continuazione quando serve la prima volta)."""
    work = C.STATE / f"daily_{session}"
    card = json.loads((work / "card.json").read_text(encoding="utf-8"))
    txt_path = C.AGREED / f"watchlist_{session}.txt"
    if not txt_path.exists():
        txt_path = work / f"watchlist_{session}.txt"
    fname = f"watchlist_{session}.txt"
    state_p = work / "discord_post.json"
    prev = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    parts = _split_embeds(card.get("embeds") or [])
    if dry_run:
        return {"dry_run": True, "would": "PATCH" if prev.get("message_id") else "POST", "messages": len(parts)}
    url = load_webhook(C.CARD_WEBHOOK_ENV)
    if not url:
        return {"ok": False, "error": "webhook card non configurato"}
    base, q = url.split("?")[0], ("&" if "?" in url else "?")
    extra = {k: v for k, v in card.items() if k != "embeds"}

    # 1) primo messaggio: primi riquadri + file
    payload = {"username": C.CARD_USERNAME, **extra, "embeds": parts[0] if parts else [], "components": [],
               "attachments": [{"id": 0, "filename": fname}]}
    body, ctype = _multipart(payload, fname, txt_path.read_bytes())
    if prev.get("message_id"):
        res = _request(f"{base}/messages/{prev['message_id']}?with_components=true", "PATCH", body, ctype)
        res["method"] = "PATCH"
        res.setdefault("message_id", prev["message_id"])
    else:
        res = _request(url + q + "wait=true", "POST", body, ctype)
        res["method"] = "POST"
    if not res.get("ok"):
        return res
    state = {**prev, **{k: v for k, v in res.items() if v is not None and k != "file_url"}, "session": str(session)}

    # 2) continuazione (se serve), stesso stile; se non serve più si cancella
    old_more = list(prev.get("more_message_ids") or [])
    more = []
    for i, emb in enumerate(parts[1:]):
        pl = json.dumps({"username": C.CARD_USERNAME, **extra, "embeds": emb}).encode()
        if i < len(old_more):
            r = _request(f"{base}/messages/{old_more[i]}", "PATCH", pl, "application/json")
            r.setdefault("message_id", old_more[i])
        else:
            r = _request(url + q + "wait=true", "POST", pl, "application/json")
        if r.get("ok"):
            more.append(r["message_id"])
    for mid in old_more[len(parts) - 1:]:
        _request(f"{base}/messages/{mid}", "DELETE", b"", "application/json")
    state["more_message_ids"] = more
    res["messages"] = 1 + len(more)

    if state.get("file_message_id"):          # messaggio separato col solo file (versione del 09/10 mattina)
        d = _request(f"{base}/messages/{state['file_message_id']}", "DELETE", b"", "application/json")
        if d.get("ok") or d.get("status") == 404:
            state.pop("file_message_id")
    write_atomic(state_p, state)
    return res


def send_alert(title: str, body: str, image: Optional[bytes] = None) -> dict:
    """Alert intraday: un embed, niente content né menzioni. Con image (PNG) il grafico va dentro l'embed [RONIN 09/10]."""
    url = load_webhook(C.ALERT_WEBHOOK_ENV)
    if not url:
        return {"sent": False, "reason": "discord_not_configured"}
    emb = {"title": title, "description": body, "color": C.ALERT_COLOR}
    payload = {"username": C.ALERT_USERNAME, "allowed_mentions": {"parse": []}, "embeds": [emb]}
    if image:
        emb["image"] = {"url": "attachment://chart.png"}
        payload["attachments"] = [{"id": 0, "filename": "chart.png"}]
        b = uuid.uuid4().hex
        data = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n".encode()
                + json.dumps(payload).encode()
                + f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
                + image + f"\r\n--{b}--\r\n".encode())
        res = _request(url, "POST", data, f"multipart/form-data; boundary={b}")
        if not res.get("ok"):                   # se l'immagine dà problemi, l'alert parte senza
            emb.pop("image", None)
            payload.pop("attachments", None)
            res = _request(url, "POST", json.dumps(payload).encode(), "application/json")
    else:
        res = _request(url, "POST", json.dumps(payload).encode(), "application/json")
    return {"sent": bool(res.get("ok")), "status": res.get("status"), "reason": res.get("error")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["card"])
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    s = date.fromisoformat(a.session) if a.session else today_rome()
    print(json.dumps(post_card(s, a.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
