"""Avvio locale (Windows o Linux): alert Jeff Coach + scanner di Remy + sync watchlist di Remy.

Un solo processo, che può restare sempre acceso. Lavora solo durante la seduta NYSE, calcolata in ora
di New York (festività, chiusure anticipate e settimane con l'apertura alle 14:30 di Roma comprese).

  - Alert Jeff Coach: ogni 90 s legge la lista del giorno dal repo GitHub (coach-agreed/today.json).
    Manda l'ingresso sul 30m ORH (solo Focus) e l'RVOL 30% nella prima ora (Focus e Stalk).
  - Scanner di Remy: una scansione 20 s dopo la chiusura di ogni barra da 5 minuti (30m pivot crossback),
    con il suo codice invariato.
  - Watchlist di Remy: alle 15:00 di Roma dei giorni di borsa rilegge le watchlist TradingView pubbliche
    (Main, Focus e la 327715885) e aggiorna i file locali (non le modifica mai su TradingView); poi
    costruisce pivot_wl_auto.txt, i titoli in più con adv$ >= 50M, mcap > 1 mld e RS >= 80
    (tv-scanner/universo_auto.py).

Uso:
  avvia.py               normale (manda su Discord)
  avvia.py --dry-run     prova: calcola tutto ma non manda niente e non salva lo stato di Remy
  avvia.py --once        un solo giro di tutto e poi esce (anche fuori seduta, per provare)

In cloud (GitHub Actions, due turni che si accavallano, vedi .github/workflows/_alert.yml):
  avvia.py --fino-chiusura --invia-fino 13:00 --stato-git      turno A
  avvia.py --fino-chiusura --invia-da 13:00 --stato-git --senza-sync    turno B
      L'ora è quella di New York ed è la chiusura di una barra da 5 minuti (13:00 NY = 19:00 Roma).
      Remy: A manda fino alla barra che chiude alle 13:00 compresa, B dalla barra delle 13:05.
      Sydney: A manda fino alle 13:04:59, B dalle 13:05:00. Nessun buco e nessuna sovrapposizione.
      B gira già da prima ma resta muto (segna come fatto quello che vede, perché lo sta mandando A).
      Alle 13:05 A salva il suo stato ed esce; B lo unisce al proprio prima del suo primo invio.
      Nelle chiusure anticipate (13:00 o prima) A fa tutta la seduta e B esce subito.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
TV = BASE / "tv-scanner"
REMY_WL = {"323848747": "pivot_wl_323848747.txt", "318147906": "pivot_wl_318147906.txt",
           "327715885": "pivot_wl_327715885.txt"}     # [RONIN 09/10] terza lista
REPO_RAW = "https://raw.githubusercontent.com/Ronin746/jeff-coach/main/data/coach-agreed/today.json"


def load_env() -> None:
    """Legge .env (CHIAVE=valore) senza mai stamparne il contenuto."""
    p = BASE / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                os.environ.setdefault(k.strip(), v)
    os.environ.setdefault("JEFF_COACH_HOME", str(BASE / "dati"))
    os.environ.setdefault("JEFF_COACH_AGREED", str(BASE / "dati" / "coach-agreed"))
    os.environ.setdefault("JEFF_COACH_AGREED_URL", REPO_RAW)
    os.environ.setdefault("TV_SCANNER_HOME", str(TV))
    os.environ.setdefault("PYTHONUTF8", "1")


load_env()
sys.path.insert(0, str(BASE))
from jeffcoach import alerts, config as C  # noqa: E402  (dopo load_env: config legge le variabili)
from jeffcoach import discord as D  # noqa: E402
from jeffcoach.calendar_us import ET, ROME, close_et, is_session, now_et, open_et  # noqa: E402

LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)
log = logging.getLogger("locale")


def setup_logging() -> None:
    h = RotatingFileHandler(LOG_DIR / "locale.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    h.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    if (sys.stdout and sys.stdout.isatty()) or os.environ.get("AVVIA_LOG_STDOUT"):
        s = logging.StreamHandler(sys.stdout)
        s.setFormatter(fmt)
        root.addHandler(s)


def single_instance() -> socket.socket | None:
    """Una sola copia attiva: se la porta è occupata c'è già un'altra istanza."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47391))
        s.listen(1)
        return s
    except OSError:
        return None


# ------------------------------------------------------------------ turni (solo in cloud)
class Turno:
    """Finestra in cui questo processo manda le notifiche. Senza --invia-da/--invia-fino manda sempre (PC)."""

    def __init__(self, da: str | None, fino: str | None, stato_git: bool):
        self.da_s, self.fino_s, self.stato_git = da, fino, stato_git
        self.lock_coach = threading.Lock()    # tenuti durante ogni giro: l'unione dello stato li aspetta
        self.lock_remy = threading.Lock()
        self.unito = False

    def _hm(self, s: str | None, d) -> datetime | None:
        if not s:
            return None
        h, m = map(int, s.split(":"))
        return datetime(d.year, d.month, d.day, h, m, tzinfo=ET)

    def bounds(self):
        """(da, fino) come ore di chiusura barra di oggi, tenendo conto delle chiusure anticipate."""
        d = now_et().date()
        da, fino = self._hm(self.da_s, d), self._hm(self.fino_s, d)
        if is_session(d):
            c = close_et(d)
            if fino and fino >= c:
                fino = None                    # chiusura anticipata: A fa tutta la seduta
        return da, fino

    def fase(self, t: datetime, remy: bool) -> str:
        """'invia', 'muto' (prima della propria finestra: registra senza mandare) o 'salta' (dopo la finestra).

        Remy: t è la chiusura della barra (A fino a 13:00 compresa, B dalla 13:05).
        Sydney: t è l'ora del giro (A prima delle 13:05:00, B dalle 13:05:00): nessun buco tra i due.
        """
        da, fino = self.bounds()
        if da is not None:
            ok = t > da if remy else t >= da + timedelta(minutes=5)
            if not ok:
                return "muto"
        if fino is not None:
            ok = t <= fino if remy else t < fino + timedelta(minutes=5)
            if not ok:
                return "salta"     # A non registra niente dopo il passaggio: è roba di B
        return "invia"

    def finito_a(self) -> bool:
        """Turno A: passata la propria finestra."""
        _, fino = self.bounds()
        return fino is not None and now_et() >= fino + timedelta(minutes=5)

    def nessun_invio_oggi(self) -> bool:
        da, _ = self.bounds()
        d = now_et().date()
        return da is not None and (not is_session(d) or da >= close_et(d))

    def forse_unisci(self) -> None:
        """Turno B: prima del primo invio unisce lo stato di A (una volta), fermando per un attimo l'altro giro."""
        da, _ = self.bounds()
        if not self.stato_git or self.unito or da is None or now_et() < da + timedelta(minutes=5):
            return
        with self.lock_coach, self.lock_remy:
            if self.unito:
                return
            try:
                r = subprocess.run([sys.executable, str(BASE / "cloud" / "stato.py"), "unisci", now_et().date().isoformat()],
                                   capture_output=True, text=True, timeout=240)
                log.info("passaggio di turno: %s", (r.stdout or r.stderr).strip()[-300:])
            except Exception as e:
                log.warning("passaggio di turno non riuscito: %s", e)
            self.unito = True

    def salva(self) -> None:
        if not self.stato_git:
            return
        r = subprocess.run([sys.executable, str(BASE / "cloud" / "stato.py"), "salva", now_et().date().isoformat()],
                           capture_output=True, text=True, timeout=180)
        log.info("stato per il turno B: %s", (r.stdout or r.stderr).strip()[-300:])


TURNO = Turno(None, None, False)
_MUTO = threading.local()
_send_alert_vero = alerts.send_alert


def _send_alert_turno(title: str, body: str, image: bytes | None = None) -> dict:
    """Fuori dalla propria finestra: segna l'alert come fatto ma non lo manda (o lo manda al finto Discord)."""
    if not getattr(_MUTO, "on", False):
        return _send_alert_vero(title, body, image=image)
    log.info("muto (fuori turno): %s", title)
    url = os.environ.get("AVVIA_MUTO_URL")
    if url:
        try:
            D._request(url.rstrip("/") + "-sydney", "POST", json.dumps({"embeds": [{"title": title, "description": body}]}).encode(),
                       "application/json")
        except Exception:
            pass
    return {"sent": True, "muted": True}


alerts.send_alert = _send_alert_turno


# ------------------------------------------------------------------ alert Jeff Coach
def coach_loop(dry: bool, stop: threading.Event) -> None:
    lg = logging.getLogger("coach")
    while not stop.is_set():
        if alerts.in_window():
            TURNO.forse_unisci()
            fase = TURNO.fase(now_et(), remy=False)
            if fase == "salta":
                stop.wait(30)
                continue
            with TURNO.lock_coach:
                _MUTO.on = fase == "muto"
                try:
                    lg.info(("[muto] " if _MUTO.on else "") + json.dumps(alerts.run_once(dry_run=dry), default=str))
                except Exception as e:
                    lg.exception("giro alert: %s", e)
            stop.wait(C.POLL_SEC)
        else:
            stop.wait(30)


# ------------------------------------------------------------------ scanner di Remy
def remy_scan(dry: bool, muto: bool = False) -> int:
    cmd = [sys.executable, "refresh_yfinance.py", "--scan"] + (["--dry-run"] if dry else [])
    env = os.environ.copy()
    if muto:      # fuori turno: Remy registra i segnali come fatti ma li manda al finto Discord (o a nessuno)
        env["DISCORD_WEBHOOK_URL"] = (os.environ.get("AVVIA_MUTO_URL") or "http://127.0.0.1:9").rstrip("/") + "-remy"
    with open(LOG_DIR / "remy.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(ROME):%Y-%m-%d %H:%M:%S} START {' '.join(cmd[1:])}{' [muto]' if muto else ''}\n")
        f.flush()
        try:
            rc = subprocess.run(cmd, cwd=TV, stdout=f, stderr=subprocess.STDOUT, timeout=280,
                                env=env).returncode
        except subprocess.TimeoutExpired:
            rc = -9
        f.write(f"{datetime.now(ROME):%Y-%m-%d %H:%M:%S} END rc={rc}\n")
    return rc


def remy_loop(dry: bool, stop: threading.Event) -> None:
    lg = logging.getLogger("remy")
    offset = int(os.environ.get("RTH_SCAN_OFFSET_SEC", "20"))
    while not stop.is_set():
        now = time.time()
        nxt = (int(now) // 300 + 1) * 300 + offset            # prossima chiusura 5m + 20 s
        if (int(now) % 300) < offset:
            nxt -= 300
        stop.wait(max(1, nxt - now))
        if stop.is_set():
            break
        if alerts.in_window():
            bar_close = datetime.fromtimestamp(nxt - offset, tz=ET)
            if bar_close <= open_et(bar_close.date()):
                continue                      # notifiche di Remy solo dall'apertura: prima barra 09:30-09:35
            TURNO.forse_unisci()
            fase = TURNO.fase(bar_close, remy=True)
            if fase == "salta":
                continue
            try:
                with TURNO.lock_remy:
                    rc = remy_scan(dry, muto=fase == "muto")
                if rc != 0:
                    lg.warning("scan Remy rc=%s (vedi logs/remy.log)", rc)
            except Exception as e:
                lg.exception("scan Remy: %s", e)


# ------------------------------------------------------------------ sync watchlist di Remy
SYMS = re.compile(r'"symbols"\s*:\s*(\[[^\]]*\])')


def fetch_tv_watchlist(wl_id: str) -> list[str]:
    req = urllib.request.Request(f"https://www.tradingview.com/watchlists/{wl_id}/",
                                 headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = SYMS.search(html)
    if not m:
        raise RuntimeError("lista simboli non trovata nella pagina")
    return [s for s in json.loads(m.group(1)) if ":" in s and not s.startswith("###")]


def remy_sync(dry: bool) -> None:
    lg = logging.getLogger("remy-sync")
    inbox = TV / "mcp_inbox"
    inbox.mkdir(exist_ok=True)
    for wl_id, fname in REMY_WL.items():
        try:
            syms = fetch_tv_watchlist(wl_id)
        except Exception as e:
            lg.warning("watchlist %s non letta (%s): tengo il file attuale", wl_id, e)
            continue
        if len(syms) < 10:
            lg.warning("watchlist %s: solo %d simboli, sospetto: tengo il file attuale", wl_id, len(syms))
            continue
        dump = inbox / f"wl_{wl_id}.json"
        dump.write_text(json.dumps({"id": wl_id, "symbols": syms}), encoding="utf-8")
        cmd = [sys.executable, "sync_pivot_wl.py", "--from-file", str(dump), "--out", str(TV / fname)] + (["--dry-run"] if dry else [])
        r = subprocess.run(cmd, cwd=TV, capture_output=True, text=True, env=os.environ.copy(), timeout=600)
        lg.info("watchlist %s: %d simboli, sync rc=%s %s", wl_id, len(syms), r.returncode, (r.stdout or r.stderr)[-300:].replace("\n", " "))


def remy_universo(dry: bool) -> None:
    """Ronin 09/10: titoli in più per Remy (adv$ >= 50M, mcap > 1 mld, RS >= 80) -> tv-scanner/pivot_wl_auto.txt."""
    lg = logging.getLogger("remy-sync")
    if dry:
        lg.info("universo automatico: salto (prova)")
        return
    r = subprocess.run([sys.executable, "universo_auto.py", "--se-manca"], cwd=TV, capture_output=True, text=True,
                       env=os.environ.copy(), timeout=1500)
    lg.info("universo automatico rc=%s %s", r.returncode, (r.stdout or r.stderr)[-300:].replace("\n", " "))


def sync_loop(dry: bool, stop: threading.Event) -> None:
    """Una volta al giorno di borsa, alle 15:00 di Roma (o all'avvio se è già passata e non è stata fatta)."""
    mark = BASE / "dati" / "remy_sync_ultimo.txt"
    mark.parent.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        now = datetime.now(ROME)
        today = now.date().isoformat()
        done = mark.exists() and mark.read_text(encoding="utf-8").strip() == today
        if is_session(now_et().date()) and now.hour >= 15 and not done:
            try:
                remy_sync(dry)
            except Exception as e:
                logging.getLogger("remy-sync").exception("sync: %s", e)
            try:
                remy_universo(dry)
            except Exception as e:
                logging.getLogger("remy-sync").exception("universo automatico: %s", e)
            if not dry:
                mark.write_text(today, encoding="utf-8")
        stop.wait(120)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--fino-chiusura", action="store_true", help="esce 5 minuti dopo la chiusura NYSE (o subito se oggi non c'è seduta)")
    ap.add_argument("--max-minuti", type=int, default=0, help="esce con codice 3 dopo N minuti se la seduta non è finita")
    ap.add_argument("--invia-da", help="HH:MM New York: manda solo dalla barra dopo questa (turno B)")
    ap.add_argument("--invia-fino", help="HH:MM New York: manda fino a questa barra compresa, poi esce (turno A)")
    ap.add_argument("--stato-git", action="store_true", help="passa lo stato tra i turni sul ramo git stato-alert")
    ap.add_argument("--senza-sync", action="store_true", help="non aggiorna le watchlist di Remy (lo fa l'altro turno)")
    a = ap.parse_args()
    setup_logging()
    lock = single_instance()
    if lock is None:
        log.info("già in esecuzione: esco")
        return 0
    log.info("avvio (dry_run=%s) — ora New York %s", a.dry_run, now_et().strftime("%Y-%m-%d %H:%M"))
    if a.once:
        log.info("alert: %s", json.dumps(alerts.run_once(dry_run=True), default=str))
        log.info("Remy scan rc=%s", remy_scan(True))
        remy_sync(True)
        return 0
    global TURNO
    TURNO = Turno(a.invia_da, a.invia_fino, a.stato_git)
    t_start = time.time()
    if TURNO.nessun_invio_oggi():
        log.info("turno B: oggi la seduta finisce prima del passaggio di turno, niente da fare: esco")
        return 0

    def finito() -> int | None:
        if not a.fino_chiusura:
            return None
        n = now_et()
        if not is_session(n.date()) or n >= close_et(n.date()) + timedelta(minutes=5):
            return 0
        if TURNO.finito_a():
            return 0
        if a.max_minuti and time.time() - t_start >= a.max_minuti * 60:
            return 3
        return None

    if finito() == 0:
        log.info("oggi niente seduta o seduta già chiusa: esco")
        return 0
    stop = threading.Event()
    if a.senza_sync and not a.dry_run:
        # turno B: il file dei titoli in più lo fa il turno A, ma il commit di A arriva a fine turno.
        # Se manca quello di oggi lo costruisco io (una volta, in un thread a parte).
        threading.Thread(target=lambda: remy_universo(False), daemon=True, name="universo").start()
    ts = [threading.Thread(target=f, args=(a.dry_run, stop), daemon=True, name=f.__name__)
          for f in (coach_loop, remy_loop) + (() if a.senza_sync else (sync_loop,))]
    for t in ts:
        t.start()
    try:
        while True:
            time.sleep(30)
            rc = finito()
            if rc is not None:
                log.info("fine turno (codice %s)", rc)
                stop.set()
                for t in ts:
                    t.join(timeout=300)     # lascia finire la scansione in corso
                if a.invia_fino:
                    try:
                        TURNO.salva()
                    except Exception as e:
                        log.warning("stato per il turno B non salvato: %s", e)
                return rc
            for t in ts:
                if not t.is_alive():
                    log.error("thread %s fermo: riavvio il processo", t.name)
                    return 1
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
