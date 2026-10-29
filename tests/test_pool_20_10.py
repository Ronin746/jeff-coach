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


def test_banda_ingresso_20_10h():
    """[20/10h di Martin] ingresso solo fra lo 0,05% e l'1,0% oltre il livello del trigger, nel verso del trade."""
    from jeffcoach import config as C
    assert C.ENTRY_BAND
    assert C.in_entry_band(100.5, 100.0, "long")          # +0,5% sopra l'ORH: dentro
    assert not C.in_entry_band(100.02, 100.0, "long")     # sul livello: fuori
    assert not C.in_entry_band(101.5, 100.0, "long")      # +1,5%: si insegue, fuori
    assert C.in_entry_band(99.5, 100.0, "short")          # -0,5% sotto l'ORL: dentro
    assert not C.in_entry_band(98.5, 100.0, "short")      # troppo lontano: fuori
    assert not C.in_entry_band(100.5, 100.0, "short")     # dalla parte sbagliata


def test_media_intraday_oraria_21_10():
    """[ANDREA 21/10] la media del reclaim di Sydney e' la EMA50 sulle barre da 1 ora (ancorate alle 9:30 ET)."""
    import pandas as pd
    from jeffcoach import config as C
    from jeffcoach.data import buckets_65m
    assert C.BUCKET_MIN == 60 and C.MA_TF_LABEL == "1h" and C.MA65_KIND == "ema" and C.MA65_LEN == 50
    idx = pd.date_range("2026-10-20 09:30", "2026-10-20 15:55", freq="5min", tz="America/New_York")
    b = buckets_65m(pd.DataFrame({"Close": range(len(idx))}, index=idx))
    assert [x[1] for x in b] == list(range(7))            # 9:30, 10:30, ... 15:30: sette barre al giorno
    assert [x[3] for x in b] == [12] * 6 + [6]             # l'ultima e' di mezz'ora


def test_card_regime_alla_martin_21_10():
    from jeffcoach import output as O
    reg = dict(bias="SHORT", score=-2, why=["pool lists: score -2 → DEFENSIVE",
               "pool (167): Leading 47% of Leading+Lagging · Leading 45 / Mediocre 71 / Lagging 50",
               "pool flow 5d -19.4% (8 up, 37 down)", "Market Monitor Expansion (context)"],
               market_monitor=dict(state="Expansion", up4=363, down4=108), mm_hist=[{"date": "2026-10-20", "up4": 1, "down4": 2}],
               pool_card=dict(n=167, lists={"Leading": 45, "Mediocre": 71, "Lagging": 50}, flow5=-19.4, up_5d=8, down_5d=37,
                              lists_1d={"Leading": 44, "Mediocre": 72, "Lagging": 50}, lists_5d=None, flow_daily=[1.9]),
               martin_breadth=None)
    out = O.regime_line(reg, "Oil & gas (leading)").split("\n")
    assert out[0].startswith("Regime **DEFENSIVE** · Focus only with a LEADING/BUILDING theme")
    assert out[0].endswith("pool lists: score -2 → DEFENSIVE; pool (167): Leading 47% of Leading+Lagging; pool flow 5d -19.4% (8 up, 37 down)")
    assert out[1] == "**Breadth** · monitored pool `167` names" and out[2] == "- Leading `45` (+1 1d)"
    assert out[-1] == "Themes: Oil & gas (leading)"
    assert "Market Monitor" not in "\n".join(out) and "±4%" not in "\n".join(out)
