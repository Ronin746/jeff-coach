"""Differenze di codice tra la base di Martin e jeff-coach, a nomi allineati (martincoach -> jeffcoach,
MARTIN_COACH_ -> JEFF_COACH_, MartinCoach -> JeffCoach). Serve a vedere a colpo d'occhio cosa è di Jeff (righe [JEFF])
e a portare qui le modifiche nuove della base.

Uso:  python strumenti/diff_base.py /percorso/martin-coach [--file daily.py] [--stat]
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REN = (("martincoach", "jeffcoach"), ("MARTIN_COACH_", "JEFF_COACH_"), ("MartinCoach", "JeffCoach"))
ONLY_JEFF = {"jeff.py", "peg.py"}          # moduli nuovi della parte di Jeff


def norm(t: str) -> str:
    for a, b in REN:
        t = t.replace(a, b)
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("martin")
    ap.add_argument("--file")
    ap.add_argument("--stat", action="store_true")
    a = ap.parse_args(argv)
    mdir = Path(a.martin).resolve() / "martincoach"
    jdir = ROOT / "jeffcoach"
    mf = {p.name for p in mdir.glob("*.py")}
    jf = {p.name for p in jdir.glob("*.py")}
    if mf - jf:
        print("solo in Martin (da portare?):", ", ".join(sorted(mf - jf)))
    extra = jf - mf - ONLY_JEFF
    if extra:
        print("solo qui (non di Jeff):", ", ".join(sorted(extra)))
    unmarked = 0
    for name in sorted(mf & jf):
        if a.file and name != a.file:
            continue
        m = norm((mdir / name).read_text(encoding="utf-8")).splitlines()
        j = (jdir / name).read_text(encoding="utf-8").splitlines()
        d = list(difflib.unified_diff(m, j, f"martin/{name}", f"jeff/{name}", lineterm="", n=1))
        if not d:
            if a.stat:
                print(f"{name:20s} uguale")
            continue
        plus = [x for x in d if x.startswith("+") and not x.startswith("+++")]
        minus = [x for x in d if x.startswith("-") and not x.startswith("---")]
        hunks = "\n".join(d).split("\n@@")
        bad = [h for h in hunks[1:] if "[JEFF" not in h and "jeff" not in h.lower()]
        unmarked += len(bad)
        if a.stat:
            print(f"{name:20s} +{len(plus)} -{len(minus)}" + (f"  ({len(bad)} blocchi senza [JEFF])" if bad else ""))
        else:
            print("\n".join(d))
    if a.stat:
        print("blocchi senza segno [JEFF]:", unmarked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
