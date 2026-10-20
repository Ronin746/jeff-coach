"""Pool monitorato come fonte del bias, studio 20% e conferma dell'indice [ANDREA 20/10]."""
import numpy as np
import pandas as pd

from jeffcoach import alerts as A, config as C, pool as PL, regime as RG


def _mercato(n_up: int, n_dn: int, days: int = 400):
    idx = pd.bdate_range(end=pd.Timestamp("2026-10-16"), periods=days)
    rng = np.random.default_rng(1)
    daily = {}
    for i in range(n_up + n_dn):
        base = np.linspace(10, 40, days) if i < n_up else np.linspace(40, 10, days)
        c = base * (1 + rng.normal(0, 0.01, days))
        daily[f"T{i:02d}"] = pd.DataFrame({"Open": c, "High": c * 1.04, "Low": c * 0.96, "Close": c,
                                           "Volume": np.full(days, 5e6)}, index=idx)
    return daily, sorted(daily), idx


def test_pool_e_liste():
    daily, syms, idx = _mercato(60, 20)
    pb = PL.pool_breadth(daily, syms, idx)
    assert pb and pb["n"] > 0 and sum(pb["lists"].values()) == pb["n"]
    assert pb["lists"]["Leading"] > pb["lists"]["Lagging"]
    assert set(pb["members"].values()) <= {"Leading", "Mediocre", "Lagging"}


def test_bias_dal_pool():
    daily, syms, idx = _mercato(60, 20)
    pb = PL.pool_breadth(daily, syms, idx)
    idxs = {"QQQ": {}, "IWM": {}}
    good = RG.regime_pool(dict(pb, share=85.0, flow5=25.0, flow_daily=[2.0] * 4), idxs, None)
    bad = RG.regime_pool(dict(pb, share=10.0, flow5=-30.0, flow_daily=[-3.0] * 4), idxs, None)
    flat = RG.regime_pool(dict(pb, share=60.0, flow5=0.0, flow_daily=[0.0] * 4), idxs, None)
    assert good["bias"] == "LONG" and good["score"] >= C.BIAS_LONG_MIN
    assert bad["bias"] == "SHORT" and bad["score"] <= C.BIAS_SHORT_MAX
    assert flat["bias"] == "MIXED"
    # senza pool si torna da sé al Market Monitor (nessuna eccezione)
    assert RG.regime_pool(None, idxs, None)["bias"] in ("LONG", "SHORT", "MIXED")


def test_studio_20_soglie():
    assert C.U20_FILTER and C.U20_LONG_MAX == 150 and C.D20_SHORT_MAX == 100


def test_conferma_indice():
    hi = pd.date_range("2026-08-01 09:30", periods=200, freq="60min", tz="America/New_York")
    up = 500 + np.arange(200) * 0.3
    qh = pd.DataFrame({"Open": up, "High": up + 0.5, "Low": up - 0.5, "Close": up, "Volume": 1e6}, index=hi)
    assert A.trend_60m(qh, float(up[-1]) + 1, "long") is True
    assert A.trend_60m(qh, float(up[-1]) + 1, "short") is False
    dn = up[::-1].copy()
    qd = pd.DataFrame({"Open": dn, "High": dn + 0.5, "Low": dn - 0.5, "Close": dn, "Volume": 1e6}, index=hi)
    assert A.trend_60m(qd, float(dn[-1]) - 1, "short") is True
    assert A.trend_60m(None, 100.0, "long") is None


def test_media_65m_e_ema50():
    """La media sulle barre 65m è la EMA50, non più la SMA30 [ANDREA 20/10]."""
    import pandas as pd
    from jeffcoach import indicators as I
    assert C.MA65_KIND == "ema" and C.MA65_LEN == 50
    closes = list(range(1, 121))                       # serie in salita: la EMA sta sopra la SMA
    v = I.ma65(closes)
    sma = sum(closes[-C.MA65_LEN:]) / C.MA65_LEN
    assert v is not None and v > sma
    assert abs(v - float(pd.Series([float(x) for x in closes]).ewm(span=50, adjust=False).mean().iloc[-1])) < 1e-9
    assert I.ma65(closes[:C.MA65_LEN - 1]) is None      # storico troppo corto: niente media
