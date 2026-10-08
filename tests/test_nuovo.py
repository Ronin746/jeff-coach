"""Controlli minimi su lettura C, forza del gruppo e scadenza degli Stalk (dati sintetici)."""
import numpy as np
import pandas as pd

from jeffcoach import config as C, engine as E, patterns as P
from jeffcoach.daily import group_strength


def _df(closes, spread=0.01):
    c = np.array(closes, dtype=float)
    idx = pd.bdate_range("2026-01-02", periods=len(c))
    return pd.DataFrame({"Open": c, "High": c * (1 + spread), "Low": c * (1 - spread), "Close": c,
                         "Volume": np.full(len(c), 1e6)}, index=idx)


def test_flag_dopo_spinta_e_stretto():
    base = list(np.linspace(50, 52, 120))
    thrust = list(np.linspace(52, 80, 25))                 # +54% in 25 sedute
    flag = [79.5, 79, 78.6, 78.9, 78.4, 78.7, 78.5, 78.8]  # pausa stretta sotto il massimo
    df = _df(base + thrust + flag)
    m = P.read_structure(df, atr=float(df.Close.iloc[-1] * 0.02))
    ok, why, _ = P.reading_c(m)
    assert ok, why
    assert m["c_thrust_pct"] > 25


def test_niente_spinta_niente_pattern():
    df = _df(list(np.linspace(50, 55, 160)))
    m = P.read_structure(df, atr=1.0)
    ok, why, _ = P.reading_c(m)
    assert not ok


def test_scadenza_stalk_carry():
    gates = [E.Gate("rs", True), E.Gate("ext", False, "x"), E.Gate("sma5", False, "y"), E.Gate("pattern", False, "p")]
    m = {"above_sma200": True, "rs": 90, "pattern_a_ok": False, "pattern_b_ok": False}
    assert E.classify(m, gates, was_listed=True) == "Stalk"     # tenuto solo dalla regola dei 2 gate
    assert E.classify(m, gates, was_listed=False) == "Out"      # come nuovo non entrerebbe: conta la scadenza


def test_gruppo_debole_non_blocca_se_gate_spento():
    assert C.GROUP_FOCUS_MIN_PCTL is None
    gates = [E.Gate("rs", True), E.Gate("pattern", True)]
    assert E.classify({"above_sma200": True, "rs": 90}, gates) == "Focus"


def test_group_strength_percentili():
    metrics = {f"A{i}": {"rs": 95, "ret21_pct": 10} for i in range(3)}
    metrics.update({f"B{i}": {"rs": 40, "ret21_pct": 1} for i in range(3)})
    doc = {"metrics": metrics, "meta": {s: {} for s in metrics},
           "industry": {**{f"A{i}": {"industry": "Forte", "sector": "S"} for i in range(3)},
                        **{f"B{i}": {"industry": "Debole", "sector": "S"} for i in range(3)}}}
    per, groups = group_strength(doc)
    assert per["A0"]["group_pctl"] == 100 and per["B0"]["group_pctl"] == 0
