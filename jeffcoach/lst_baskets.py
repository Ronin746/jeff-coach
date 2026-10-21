"""Basket di Lone Stock Trader (app.lonestocktrader.com/dashboard/basket-charts) [RONIN 21/10, Andrea: "per tutti i
gruppi prendili da questo sito; aggiornali ogni lunedì alle 01:00 italiane"].

Il sito richiede il login (X). La sessione è quella di Supabase (cookie `sb-<ref>-auth-token`, a pezzi .0 .1 ...):
- la prima volta si prende da .env (LST_TOKEN_0, LST_TOKEN_1: i valori dei due cookie copiati dal browser, da una
  finestra in incognito chiusa SENZA fare logout, così la sessione del server è solo sua);
- poi il server tiene la sessione aggiornata in ~/.lst/session.json (fuori dal repo): il sito la rinnova a ogni
  visita (Set-Cookie); se non lo fa, si rinnova direttamente con il refresh token di Supabase.
Una sola lettura a settimana per tutti e tre i bot: il risultato va anche in ~/.lst/baskets.json, gli altri bot lo
copiano se ha meno di 20 ore. Nel repo resta data/themes/lst_baskets.json (lo usano lista e card, anche su GitHub
Actions, senza rete verso il sito). Se la lettura non riesce si tiene il file della settimana prima.

Uso:  python -m <pacchetto>.lst_baskets [--force]      (exit 0 aggiornato, 1 tenuto il vecchio)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SITE = "https://app.lonestocktrader.com"
PAGE = SITE + "/dashboard/basket-charts"
PROJECT_REF = "lcebbiuqiwmnystasuma"
SUPABASE = f"https://{PROJECT_REF}.supabase.co"
COOKIE = f"sb-{PROJECT_REF}-auth-token"
CHUNK = 3180                       # MAX_CHUNK_SIZE di @supabase/ssr
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

REPO = Path(__file__).resolve().parent.parent
REPO_FILE = REPO / "data" / "themes" / "lst_baskets.json"
SHARED = Path(os.environ.get("LST_DIR", Path.home() / ".lst"))
SESSION_FILE = SHARED / "session.json"
SHARED_FILE = SHARED / "baskets.json"
SHARED_MAX_AGE = timedelta(hours=20)
MIN_BASKETS, MIN_TICKERS = 30, 300  # sotto: pagina cambiata o non loggata, non si sovrascrive niente


class LSTError(RuntimeError):
    pass


# ------------------------------------------------------------------ lettura della pagina
_BASKET_RE = re.compile(r'"id":"basket-[^"]*".*?"children":"([^"]+)".*?"tickers":(\[[^\]]*\])', re.S)


def parse(rsc: str) -> dict[str, list[str]]:
    """{BASKET: [ticker, ...]} dal payload RSC (o dall'HTML) della pagina basket-charts, nell'ordine del sito."""
    out: dict[str, list[str]] = {}
    for name, arr in _BASKET_RE.findall(rsc.replace('\\"', '"')):
        try:
            ticks = json.loads(arr)
        except ValueError:
            continue
        seen = []
        for t in ticks:
            t = str(t).strip().upper()
            if t and t not in seen:
                seen.append(t)
        if seen:
            out[name.strip()] = seen
    return out


def check(baskets: dict[str, list[str]]) -> None:
    n = len({t for v in baskets.values() for t in v})
    if len(baskets) < MIN_BASKETS or n < MIN_TICKERS:
        raise LSTError(f"pagina letta ma solo {len(baskets)} basket / {n} titoli: login scaduto o pagina cambiata")


# ------------------------------------------------------------------ sessione
def _save_session(cookies: dict[str, str]) -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cookies": cookies, "updated_utc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(SESSION_FILE)


def load_session() -> dict[str, str]:
    """Cookie di sessione: prima il file del server (sempre il più recente), poi .env."""
    if SESSION_FILE.exists():
        try:
            c = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("cookies") or {}
            if c:
                return c
        except ValueError:
            pass
    c: dict[str, str] = {}
    full = os.environ.get("LST_COOKIE", "").strip()          # in alternativa: la riga Cookie intera
    if full:
        for part in full.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.startswith(COOKIE):
                    c[k] = v
    for i in range(4):
        v = os.environ.get(f"LST_TOKEN_{i}", "").strip()
        if v:
            c[f"{COOKIE}.{i}"] = v
    return c


def _joined(cookies: dict[str, str]) -> str:
    if COOKIE in cookies:
        return cookies[COOKIE]
    parts, i = [], 0
    while f"{COOKIE}.{i}" in cookies:
        parts.append(cookies[f"{COOKIE}.{i}"])
        i += 1
    return "".join(parts)


def _decode(value: str) -> dict:
    from urllib.parse import unquote
    v = unquote(value)
    if v.startswith("base64-"):
        b = v[7:]
        v = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8")
    return json.loads(v)


def _encode(session: dict) -> dict[str, str]:
    v = "base64-" + base64.urlsafe_b64encode(json.dumps(session, separators=(",", ":")).encode()).decode().rstrip("=")
    if len(v) <= CHUNK:
        return {COOKIE: v}
    return {f"{COOKIE}.{i}": v[k:k + CHUNK] for i, k in enumerate(range(0, len(v), CHUNK))}


def _apply_set_cookie(cookies: dict[str, str], headers: list[str]) -> bool:
    changed = False
    for h in headers:
        first = h.split(";", 1)[0]
        if "=" not in first:
            continue
        k, v = first.split("=", 1)
        k = k.strip()
        if not k.startswith(COOKIE):
            continue
        low = h.lower()
        if not v or "max-age=0" in low or "expires=thu, 01 jan 1970" in low:
            changed |= cookies.pop(k, None) is not None
        elif cookies.get(k) != v:
            cookies[k] = v
            changed = True
    if changed and COOKIE in cookies and any(k.startswith(COOKIE + ".") for k in cookies):
        # passaggio tra cookie unico e a pezzi: vale il formato dell'ultima risposta
        newest = [first.split("=", 1)[0].strip() for first in (h.split(";", 1)[0] for h in headers) if "=" in first]
        if COOKIE in newest:
            for k in [k for k in cookies if k.startswith(COOKIE + ".")]:
                cookies.pop(k)
        else:
            cookies.pop(COOKIE, None)
    return changed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, cookies: dict[str, str], rsc: bool = True, timeout: int = 60) -> tuple[int, str, list[str]]:
    h = {"User-Agent": UA, "Accept": "*/*"}
    if rsc:
        h["RSC"] = "1"
    if cookies:
        h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(url, headers=h)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "ignore"), r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        return e.code, "", e.headers.get_all("Set-Cookie") or []


def _anon_key() -> str:
    """Chiave pubblica (anon) di Supabase del sito: è nel JavaScript della pagina di login."""
    p = SHARED / "anon_key"
    if p.exists():
        return p.read_text().strip()
    _, html, _ = _get(SITE + "/login", {}, rsc=False)
    for src in dict.fromkeys(re.findall(r'(/_next/static/chunks/[^"\']+\.js)', html)):
        _, js, _ = _get(SITE + src, {}, rsc=False)
        for tok in re.findall(r"eyJ[A-Za-z0-9_-]+\.(eyJ[A-Za-z0-9_-]+)\.[A-Za-z0-9_-]+", js):
            try:
                pl = json.loads(base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4)))
            except Exception:
                continue
            if pl.get("role") == "anon" and pl.get("ref") == PROJECT_REF:
                key = re.search(r"eyJ[A-Za-z0-9_-]+\." + re.escape(tok) + r"\.[A-Za-z0-9_-]+", js).group(0)
                SHARED.mkdir(parents=True, exist_ok=True)
                p.write_text(key)
                return key
    raise LSTError("chiave pubblica di Supabase non trovata nel sito")


def refresh_supabase(cookies: dict[str, str]) -> dict[str, str]:
    """Nuova sessione dal refresh token (quando il sito non la rinnova da solo)."""
    try:
        sess = _decode(_joined(cookies))
        rt = sess["refresh_token"]
    except Exception as e:
        raise LSTError(f"cookie di sessione illeggibile ({e}): ricopialo in .env") from None
    key = _anon_key()
    req = urllib.request.Request(f"{SUPABASE}/auth/v1/token?grant_type=refresh_token", method="POST",
                                 data=json.dumps({"refresh_token": rt}).encode(),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        new = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        raise LSTError(f"rinnovo della sessione rifiutato ({e.code}): serve un cookie nuovo in .env") from None
    if "expires_at" not in new and new.get("expires_in"):
        new["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(new["expires_in"])
    out = {k: v for k, v in cookies.items() if not k.startswith(COOKIE)}
    out.update(_encode(new))
    return out


def fetch() -> dict[str, list[str]]:
    cookies = load_session()
    if not cookies:
        raise LSTError("nessuna sessione: metti LST_TOKEN_0 e LST_TOKEN_1 in .env")
    for attempt in range(2):
        code, body, sc = _get(PAGE, cookies)
        if _apply_set_cookie(cookies, sc):
            _save_session(cookies)             # il sito ha rinnovato la sessione: si tiene subito quella nuova
        if code == 200:
            b = parse(body)
            check(b)
            _save_session(cookies)
            return b
        if attempt == 0:
            log.info("basket LST: risposta %s, rinnovo la sessione con Supabase", code)
            cookies = refresh_supabase(cookies)
            _save_session(cookies)
    raise LSTError(f"pagina dei basket non accessibile (HTTP {code}) anche dopo il rinnovo")


# ------------------------------------------------------------------ file
def load(path: Path = REPO_FILE) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def update(force: bool = False) -> dict:
    """Basket aggiornati nel repo: dalla copia comune del server se recente, altrimenti dal sito."""
    now = datetime.now(timezone.utc)
    shared = load(SHARED_FILE)
    doc = None
    if not force and shared and now - datetime.fromisoformat(shared["fetched_utc"]) < SHARED_MAX_AGE:
        doc = shared
        how = "copia comune del server"
    else:
        b = fetch()
        doc = {"fetched_utc": now.isoformat(), "source": PAGE, "n_baskets": len(b),
               "n_tickers": len({t for v in b.values() for t in v}), "baskets": b}
        _write(SHARED_FILE, doc)
        how = "sito"
    old = load()
    if old:
        ob, nb = old.get("baskets") or {}, doc["baskets"]
        doc = dict(doc, changes={
            "baskets_added": sorted(set(nb) - set(ob)), "baskets_removed": sorted(set(ob) - set(nb)),
            "tickers_added": {k: sorted(set(v) - set(ob.get(k, []))) for k, v in nb.items() if set(v) - set(ob.get(k, []))},
            "tickers_removed": {k: sorted(set(v) - set(nb.get(k, []))) for k, v in ob.items() if set(v) - set(nb.get(k, []))}})
    _write(REPO_FILE, doc)
    log.info("basket LST (%s): %d basket, %d titoli", how, doc["n_baskets"], doc["n_tickers"])
    return doc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rilegge il sito anche se la copia comune è recente")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        doc = update(a.force)
    except Exception as e:
        old = load()
        print(json.dumps({"ok": False, "error": str(e), "kept": (old or {}).get("fetched_utc")}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "fetched_utc": doc["fetched_utc"], "baskets": doc["n_baskets"], "tickers": doc["n_tickers"],
                      "changes": {k: len(v) for k, v in (doc.get("changes") or {}).items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
