"""Temi = basket di Lone Stock Trader [21/10]: classifica sul 7-factor medio dei titoli, RS settimana/mese, sezione
temi della card con grafico e classifica complessiva (dati sintetici)."""
import numpy as np
import pandas as pd

from jeffcoach import config as C, themes as TH, themes_map as TM, rs_chart as RC
from jeffcoach.daily import lst_ranking
from jeffcoach.output import card_descriptions


def _df(seed, drift, n=300):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    idx = pd.bdate_range("2025-06-02", periods=n)
    return pd.DataFrame({"Open": c * 0.995, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.full(n, 3e6)}, index=idx)


def test_basket_lst_classifica_e_card():
    daily = {f"U{i}": _df(i, 0.003) for i in range(6)} | {f"D{i}": _df(50 + i, -0.003) for i in range(6)}
    daily["SPY"] = _df(99, 0.0005)
    baskets = {"UP": [f"U{i}" for i in range(6)], "DOWN": [f"D{i}" for i in range(6)], "MIX": ["U0", "D0", "U1"],
               "TINY": ["U2", "NOPE"]}
    m = TM.build_lst_map(baskets)
    assert m["tickers"]["U0"]["primary"] == "MIX" and m["tickers"]["U3"]["primary"] == "UP"
    tmap = {"built_utc": "x", "membership": "lst", "baskets_fetched_utc": "2026-10-20T23:00:00+00:00", **m}
    metrics = {s: {"adv": 2e8} for s in daily if s != "SPY"}
    th = TH.build(daily, daily["SPY"].Close, set(metrics), metrics, tmap)
    names = [r["theme"] for r in th["rows"]]
    assert names[0] == "UP" and "TINY" not in names
    assert th["ticker"]["U0"] == "MIX"
    rk = lst_ranking(th)
    assert rk["ranked_n"] == 3 and all(0 < x["rs_w"] <= 100 for x in rk["ranking"])
    themes = dict(leading=[], downtrend=[], n_themes=len(th["rows"]), line="", **rk)
    d = card_descriptions("2026-10-21", [], [], themes=themes, as_of="2026-10-20")
    assert any(x.startswith("**THEMES** · groups as of 2026-10-20") for x in d)
    assert any(x.startswith("Month RS (x) vs Quarter RS (y)") for x in d) and not any("Lone Stock" in x for x in d)
    assert not any("Overall ranking" in x or "LEADING / BUILDING" in x for x in d)     # [ANDREA 28/10] tolta
    pngs = RC.render_all(rk["points"])
    assert set(pngs) == {"themes_rs.png", "themes_rs_3m.png"}
