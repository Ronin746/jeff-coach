"""Passaggio di stato tra il turno A e il turno B degli alert in cloud.

  salva   (turno A, dopo l'ultimo invio): mette fired.json di Sydney e signal_state.json di Remy sul ramo
          git "stato-alert" del repo, con la data della seduta.
  unisci  (turno B, prima del primo invio): scarica quel ramo e unisce lo stato di A al proprio. L'unione
          è "tutto ciò che uno dei due ha già mandato o visto": così B non ripete niente di A.

Funziona solo dentro un checkout git con credenziali di push (GitHub Actions). Sul PC non si usa.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANCH = "stato-alert"
FILES = {
    "fired.json": ROOT / "dati" / "state" / "alerts" / "fired.json",
    "signal_state.json": ROOT / "tv-scanner" / "signal_state.json",
}


def _git(*args: str, env: dict | None = None, inp: bytes | None = None) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, input=inp,
                       env={**os.environ, **(env or {})}, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {r.stderr.decode(errors='replace')[-300:]}")
    return r.stdout.decode().strip()


def salva(session: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
        _git("read-tree", "--empty", env=env)
        blobs = {"turno.json": json.dumps({"session": session, "ts": time.time()}).encode()}
        for name, p in FILES.items():
            if p.exists():
                blobs[name] = p.read_bytes()
        for name, data in blobs.items():
            sha = _git("hash-object", "-w", "--stdin", inp=data)
            _git("update-index", "--add", "--cacheinfo", f"100644,{sha},{name}", env=env)
        tree = _git("write-tree", env=env)
        commit = _git("-c", "user.name=jeff-coach-bot", "-c", "user.email=jeff-coach-bot@users.noreply.github.com",
                      "commit-tree", tree, "-m", f"stato alert {session}")
        _git("push", "-f", "origin", f"{commit}:refs/heads/{BRANCH}")
    return f"salvato ({', '.join(blobs)})"


def _union(mine: dict, theirs: dict) -> dict:
    """Unione ricorsiva: le chiavi di entrambi; a parità di chiave tiene la propria."""
    out = dict(theirs)
    for k, v in mine.items():
        out[k] = _union(v, out[k]) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def unisci(session: str, attesa_sec: int = 150) -> str:
    """Aspetta al massimo attesa_sec che lo stato di A per questa seduta sia sul ramo, poi lo unisce."""
    fine = time.time() + attesa_sec
    while True:
        try:
            _git("fetch", "-q", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
            meta = json.loads(_git("show", f"origin/{BRANCH}:turno.json"))
            if meta.get("session") == session:
                break
        except Exception:
            pass
        if time.time() >= fine:
            return "stato del turno A non trovato: continuo con il mio"
        time.sleep(10)
    fatti = []
    for name, p in FILES.items():
        try:
            theirs = json.loads(_git("show", f"origin/{BRANCH}:{name}"))
        except Exception:
            continue
        mine = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_union(mine, theirs), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(p)
        fatti.append(name)
    return f"unito lo stato del turno A ({', '.join(fatti) or 'niente'})"


if __name__ == "__main__":
    cmd, session = sys.argv[1], sys.argv[2]
    print(salva(session) if cmd == "salva" else unisci(session))
