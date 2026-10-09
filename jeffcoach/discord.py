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


def post_card(session: date, dry_run: bool = False) -> dict:
    """Card (riquadri) e, subito sotto, un secondo messaggio con il solo file txt per TradingView, così il file
    da scaricare sta in fondo alla card [RONIN 09/10]. Stesso giorno: si correggono i due messaggi, mai nuovi post."""
    work = C.STATE / f"daily_{session}"
    card = json.loads((work / "card.json").read_text(encoding="utf-8"))
    txt_path = C.AGREED / f"watchlist_{session}.txt"
    if not txt_path.exists():
        txt_path = work / f"watchlist_{session}.txt"
    fname = f"watchlist_{session}.txt"
    state_p = work / "discord_post.json"
    prev = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    if dry_run:
        return {"dry_run": True, "would": "PATCH" if prev.get("message_id") else "POST"}
    url = load_webhook(C.CARD_WEBHOOK_ENV)
    if not url:
        return {"ok": False, "error": "webhook card non configurato"}
    base, q = url.split("?")[0], ("&" if "?" in url else "?")

    # 1) la card, senza allegati (attachments: [] toglie anche un file allegato da una versione precedente)
    payload = {"username": C.CARD_USERNAME, **card, "attachments": []}
    body = json.dumps(payload).encode()
    if prev.get("message_id"):
        res = _request(f"{base}/messages/{prev['message_id']}", "PATCH", body, "application/json")
        res["method"] = "PATCH"
        res.setdefault("message_id", prev["message_id"])
    else:
        res = _request(url + q + "wait=true", "POST", body, "application/json")
        res["method"] = "POST"
    if not res.get("ok"):
        return res
    state = {**prev, **{k: v for k, v in res.items() if v is not None}, "session": str(session)}

    # 2) il file, in un messaggio subito sotto la card
    fpay = {"username": C.CARD_USERNAME, "allowed_mentions": {"parse": []}, "attachments": [{"id": 0, "filename": fname}]}
    fbody, ctype = _multipart(fpay, fname, txt_path.read_bytes())
    if prev.get("file_message_id"):
        fres = _request(f"{base}/messages/{prev['file_message_id']}", "PATCH", fbody, ctype)
        fres.setdefault("message_id", prev["file_message_id"])
    else:
        fres = _request(url + q + "wait=true", "POST", fbody, ctype)
    if fres.get("ok"):
        state["file_message_id"] = fres.get("message_id")
    res["file_ok"] = bool(fres.get("ok"))

    # 3) tasto in fondo alla card che apre il file ospitato da Discord (quello del messaggio sotto) [RONIN 09/10]
    if fres.get("file_url"):
        btn = [{"type": 1, "components": [{"type": 2, "style": 5, "label": f"⬇ {fname}", "url": fres["file_url"]}]}]
        bres = _request(f"{base}/messages/{state['message_id']}?with_components=true", "PATCH",
                        json.dumps({"components": btn}).encode(), "application/json")
        res["button"] = bool(bres.get("ok"))
        if not bres.get("ok"):
            res["button_error"] = bres.get("error")
    state.pop("file_url", None)
    write_atomic(state_p, {k: v for k, v in state.items() if k not in ("file_url", "button", "button_error")})
    return res


def send_alert(title: str, body: str) -> dict:
    """Alert intraday: un embed, niente content né menzioni."""
    url = load_webhook(C.ALERT_WEBHOOK_ENV)
    if not url:
        return {"sent": False, "reason": "discord_not_configured"}
    payload = {"username": C.ALERT_USERNAME, "allowed_mentions": {"parse": []},
               "embeds": [{"title": title, "description": body, "color": C.ALERT_COLOR}]}
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
