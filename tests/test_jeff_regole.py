"""Regole dai post per abbonati di Jeff (08/10): gap da riempire, triangolo ascendente, PEG, ingresso con RVOL e LoD."""
import numpy as np
import pandas as pd

from jeffcoach import alerts as A, engine as E, patterns as P, peg as PG


def _df(o, h, l, c, v=None):
    idx = pd.bdate_range("2026-01-02", periods=len(c))
    v = np.full(len(c), 1e6) if v is None else v
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx).astype(float)


def test_gap_aperto_e_riempito():
    c = np.full(80, 100.0); h = c + 1; l = c - 1; o = c.copy()
    c[70:], h[70:], l[70:], o[70:] = 95, 96, 94, 95          # gap giù: massimo 96 < minimo prima 99
    g = E.gap_resistance(_df(o, h, l, c), atr=2.0)
    assert g["gap_open"] and g["gap_top"] == 99
    h[78] = 99.5                                            # un massimo torna a 99: gap riempito
    assert not E.gap_resistance(_df(o, h, l, c), atr=2.0)["gap_open"]


def test_gap_e_gate_soft():
    assert "gap" in E.SOFT_GATES


def test_triangolo_ascendente():
    n = 160
    base = list(np.linspace(50, 80, 100))                   # trend sopra la 50
    t = np.arange(60)
    lows = 74 + 0.12 * t + 0.0                               # minimi che salgono
    wave = np.abs(np.sin(np.pi * t / 10))                    # oscilla tra supporto e tetto 82
    mid = lows + (82 - lows) * wave
    c = np.array(base + list(mid)); h = c + 0.3; l = c - 0.3; o = c.copy()
    h[100:] = np.minimum(h[100:], 82.0)
    c[-1], h[-1], l[-1] = 81.5, 81.8, 81.0
    m = P.read_triangle(_df(o, h, l, c), atr=1.0)
    assert m.get("t_found"), m
    assert abs(m["t_top"] - 82.0) < 0.5


def test_peg_ritorno_nel_range():
    n = 160
    c = np.full(n, 50.0); c[:100] = np.linspace(40, 50, 100)
    o, h, l, v = c.copy(), c + 0.5, c - 0.5, np.full(n, 1e6)
    o[130], h[130], l[130], c[130], v[130] = 56, 58, 55, 57, 5e6     # gap +12% con 5x volume
    c[131:] = 54.0 + 0.05 * np.arange(n - 131); o[131:] = c[131:]; h[131:] = c[131:] + 0.4; l[131:] = c[131:] - 0.4
    m = PG.read_peg(_df(o, h, l, c, v), atr=1.0)
    assert m["peg_found"] and m["peg_ok"], m.get("peg_why")
    assert PG.confirm_earnings(m, [m["peg_date"]])


def test_ingresso_rvol_e_lod():
    ref = {"adv": 3e8, "prev_rvol": 0.38, "atr": 1.0}
    assert abs(A.rvol_needed(ref) - 0.18) < 1e-9
    assert A.rvol_needed({"adv": 2e9}) is None                    # liquido: niente RVOL
    assert not A.entry_checks(10.5, 10.0, 0.10, 30, ref)[0]      # volume insufficiente
    assert not A.entry_checks(10.9, 10.0, 0.30, 30, ref)[0]      # LoD 90% ATR
    assert A.entry_checks(10.5, 10.0, 0.30, 30, ref)[0]



def test_gap_spento():
    from jeffcoach import config as C
    assert C.GAP_GATE_ON is False          # [RONIN 08/10] da rifare prima di usarlo


def test_base_dopo_ritracciamento_sul_pivot_e_stretta():
    """Caso HPQ 08/10 (Focus di Jeff, mini triangolo ascendente): base nuova dopo un ritracciamento,
    prezzo sul pivot della base ma oltre 10% sotto il vecchio massimo. A e B devono vederla stretta."""
    from jeffcoach import engine as E
    m = dict(a_range10_adr=1.6, a_off_high20_pct=-10.5, last_range_adr=0.5,
             a_close5_adr=0.7, a_thrust60_pct=55.0, b_rally20_atr=4.6, b_pullback_atr=4.4, b_thrust_atr=7.5,
             c_retrace=0.39, b_slope_h8=0.13, b_slope_l8=0.13, b_last_range_atr=0.53, ret1_pct=0.6,
             b_range5_atr=1.35, b_dist_hi10_atr=0.32)
    assert E.reading_a(m)[0] and E.reading_b(m)[0]
    m2 = dict(m, c_retrace=0.7)               # ha restituito più di metà della spinta: non è più una base
    assert not E.reading_b(m2)[0]
    m3 = dict(m, a_off_high20_pct=-31.0)       # oltre 30% sotto il massimo a 20 giorni
    assert not E.reading_a(m3)[0]


def test_trendline_discendente_rotta_con_volume():
    """Discesa dal picco con massimi decrescenti, poi rottura con volume: la linea parte dal picco e la rottura
    è oggi, con volume 2x la media."""
    import numpy as np
    import pandas as pd
    from jeffcoach import dtl
    n = 160
    idx = pd.bdate_range("2026-03-02", periods=n)
    base = np.r_[np.linspace(60, 100, 40), np.linspace(100, 70, 110), np.linspace(70, 70, 9), [80.0]]
    wave = np.r_[np.zeros(40), 4 * np.sin(np.linspace(0, 6 * np.pi, 110)), np.zeros(10)]
    close = base + wave
    high, low = close + 1.0, close - 1.0
    vol = np.full(n, 1_000_000.0)
    vol[-1] = 2_000_000.0
    df = pd.DataFrame(dict(Open=close, High=high, Low=low, Close=close, Volume=vol), index=idx)
    m = dtl.read_dtl(df, atr=2.0)
    assert m["dt_found"] and m["dt_broken"] and m["dt_break_ago"] == 0
    assert m["dt_break_vol"] >= 1.5
    assert dtl.state(m) == "break"
