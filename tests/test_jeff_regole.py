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


def _base(**kw):
    """Misure della lettura unica per una base ascendente stretta sul pivot (caso HPQ 08/10, Focus di Jeff)."""
    m = dict(c_ok_data=True, c_kind="pullback base", c_thrust_pct=40.0, c_thrust_atr=9.0, c_base_len=20,
             c_retrace=0.39, c_depth_pct=12.0, c_slope_up_atr=0.0, c_slope_lo_atr=0.10, c_width_atr=1.8,
             c_width0_atr=4.0, c_range5_atr=1.35, last_range_adr=0.5, c_dist_upper_atr=0.3,
             c_close_vs_ema20_atr=0.2, c_close_vs_sma50_atr=2.0, c_closes_under_sma50=0, c_vol_dryup=0.7)
    m.update(kw)
    return m


def test_lettura_unica_base_stretta_sul_pivot():
    """Base nuova dopo un ritracciamento, prezzo sul pivot e stretta: pattern tight (Focus possibile)."""
    st, why, _ = P.reading(_base())
    assert st == "tight", why


def test_lettura_unica_tre_esiti():
    assert P.reading(_base(c_retrace=0.7))[0] == "none"            # ha restituito più di metà della spinta
    assert P.reading(_base(c_thrust_pct=10.0, c_thrust_atr=3.0))[0] == "none"   # nessuna spinta prima della base
    assert P.reading(_base(c_close_vs_sma50_atr=-0.5))[0] == "none"  # persa la 50 durante la base
    st, why, _ = P.reading(_base(c_slope_up_atr=-0.10, c_slope_lo_atr=0.0))
    assert st == "none" and "descending triangle" in why           # forma esclusa (casi RNG, FIVN, SN del 09/10)
    st, why, _ = P.reading(_base(c_slope_up_atr=0.10, c_slope_lo_atr=0.20, c_width_atr=1.0))
    assert st == "none" and "rising wedge" in why
    assert P.reading(_base(c_range5_atr=2.6))[0] == "forming"       # ammesso ma non ancora stretto: Stalk
    assert P.reading(_base(last_range_adr=1.6))[0] == "forming"     # Jeff: mai dopo una seduta larga
    assert P.reading(_base(c_dist_upper_atr=2.0))[0] == "forming"   # lontano dal pivot
    assert P.reading(_base(c_vol_dryup=1.2))[0] == "forming"        # Jeff: volume in calo prima del Focus


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


import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from datetime import date  # noqa: E402


def test_chiusure_mancanti_di_yahoo_dalle_barre_a_60_minuti():
    """28/10: Yahoo ha dato la barra daily del 27/10 senza Close su quasi tutto l'universo (lista del mattino vuota).
    La chiusura si prende dall'ultima barra a 60 minuti del giorno, dentro minimo e massimo; senza barre resta scartata."""
    from jeffcoach import data as D
    ix = pd.DatetimeIndex([pd.Timestamp("2026-10-23"), pd.Timestamp("2026-10-26"), pd.Timestamp("2026-10-27")])
    frames = {
        "AAPL": pd.DataFrame({"Open": [349.1, 343.9, 343.2], "High": [351.7, 347.1, 347.8], "Low": [345.8, 341.0, 342.4],
                              "Close": [347.7, 343.9, np.nan], "Volume": [3.9e7, 4.2e7, 3.9e7]}, index=ix),
        "NVDA": pd.DataFrame({"Open": [211.0, 213.1, 218.3], "High": [213.9, 217.8, 219.2], "Low": [210.2, 212.6, 215.5],
                              "Close": [211.0, 216.0, np.nan], "Volume": [8e7, 9e7, 8.4e7]}, index=ix),
        "MSFT": pd.DataFrame({"Open": [1.0, 1.0, 1.0], "High": [2.0, 2.0, 2.0], "Low": [0.5, 0.5, 0.5],
                              "Close": [1.5, 1.5, np.nan], "Volume": [1, 1, 1]}, index=ix),
    }
    seen = {}

    def fetch(syms, lo, hi):
        seen["call"] = (tuple(syms), lo, hi)
        t = pd.DatetimeIndex(["2026-10-27 14:30", "2026-10-27 15:30"]).tz_localize("America/New_York")
        cols = pd.MultiIndex.from_product([["AAPL", "NVDA"], ["Open", "High", "Low", "Close", "Volume"]])
        return pd.DataFrame([[1, 1, 1, 347.17, 1, 1, 1, 1, 217.37, 1], [1, 1, 1, 347.08, 1, 1, 1, 1, 230.0, 1]],
                            index=t, columns=cols)
    n = D.fill_missing_closes(frames, date(2026, 10, 27), fetch=fetch)
    assert n == 2 and seen["call"] == (("AAPL", "MSFT", "NVDA"), date(2026, 10, 27), date(2026, 10, 28))
    assert frames["AAPL"].Close.iloc[-1] == 347.08
    assert frames["NVDA"].Close.iloc[-1] == 219.2           # fuori dalla barra daily: tagliata al massimo
    assert np.isnan(frames["MSFT"].Close.iloc[-1])           # senza barre a 60 minuti resta vuota (poi scartata)
    assert D.fill_missing_closes({"X": frames["AAPL"]}, date(2026, 10, 27), fetch=fetch) == 0


def test_charting_mets_29_10():
    """[ANDREA 29/10] Versione di prima con il charting e i supporti di METS: grafico daily in scala log con livello,
    trendline e orizzontali; gallerie dei Focus nella card; card divisa entro 10 riquadri e 10 file per messaggio."""
    from datetime import date as _d
    import numpy as _np
    import pandas as _pd
    from jeffcoach import config as C
    from jeffcoach.mets import chart as MC
    from jeffcoach.discord import _split_embeds
    assert C.METS_CHART and C.CARD_FOCUS_CHARTS
    ix = _pd.bdate_range("2024-01-01", periods=600)
    c = 50 * _np.exp(_np.cumsum(_np.sin(_np.arange(600) / 15) * 0.01 + 0.001))
    df = _pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=ix)
    png = MC.alert_chart("XYZ", "long", None, 5, ix[-1].date() + _pd.Timedelta(days=1), level=float(c[-1]) * 0.98,
                         title="prova", daily=df, panel=False)
    assert png and png[:4] == b"\x89PNG"
    e = {"description": "**FOCUS**\n• A", "color": 1}
    more = MC.gallery(e, ["A", "B", "C", "D", "E"], {t: f"focus_{t}.png" for t in "ABCDE"})
    assert e["image"]["url"] == "attachment://focus_A.png" and len(more) == 4 and more[3]["url"] != e["url"]
    msgs = _split_embeds([{"description": "head", "image": {"url": "attachment://breadth.png"}}, e] + more
                         + [{"description": "**STALK**"}] * 3)
    assert all(len(m) <= 10 for m in msgs) and sum(len(m) for m in msgs) == 9
