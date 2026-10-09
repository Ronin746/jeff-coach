"""Lettura D (canale rialzista, acquisto nella parte bassa) e lista "canale" con la SMA30 65m (dati sintetici)."""
import numpy as np
import pandas as pd

from jeffcoach import channel as CH, engine as E
from jeffcoach.daily import channel_watch


def _channel_df(end_phase):
    """Canale che sale a scalini (onda di 20 sedute) per 200 sedute; end_phase decide dove finisce il prezzo."""
    n = 200
    t = np.arange(n)
    mid = 50 + 0.15 * t + 3 * np.sin(2 * np.pi * (t - n + 1) / 20 + end_phase)
    idx = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame({"Open": mid, "High": mid + 0.4, "Low": mid - 0.4, "Close": mid,
                         "Volume": np.full(n, 1e6)}, index=idx)


def test_canale_bordo_basso_e_alto():
    low = _channel_df(-np.pi / 2)                   # ultimo close sul minimo dell'onda = bordo basso
    m = CH.read_channel(low, atr=1.5)
    assert m["d_found"] and m["d_pos"] < 0.3, m.get("d_pos")
    ok, why, _ = CH.reading_d(m)
    assert ok, why
    high = _channel_df(np.pi / 2)                   # sul massimo dell'onda = bordo alto, non si compra
    m = CH.read_channel(high, atr=1.5)
    ok, why, _ = CH.reading_d(m)
    assert not ok and m["d_state"] == "at the upper line", (m.get("d_state"), why)


def test_lista_canale_recupero_sma30_sotto_ema9():
    m = dict(pattern_d_ok=True, rs=95, d_state="lower part of the channel", close=100.0, d_lower_next=97.0,
             d_upper_next=110.0, d_pos=0.2, d_width_atr=4.0, ema9=101.0, atr=2.0)
    rows = {"XYZ": E.Row("XYZ", "Out", m, [])}
    w = channel_watch(rows, {"XYZ": {"sma30_65m": 99.0}})
    assert w[0]["above_sma30_65m"] is True and w[0]["under_ema9"] is True     # si segnala anche sotto la EMA9
    w = channel_watch(rows, {"XYZ": {"sma30_65m": 101.5}})
    assert w[0]["above_sma30_65m"] is False                                    # in osservazione per l'alert
