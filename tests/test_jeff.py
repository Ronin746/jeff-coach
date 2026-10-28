"""Prove senza rete della parte di Jeff sulla base multi-edge, con la configurazione vera di jeff-coach (multi-edge
acceso, Jeff acceso). Uso: python tests/test_jeff.py   oppure   python -m pytest tests -q

I valori "di prima" (GOLD_*) sono stati calcolati con il codice di jeff-coach main @36a11c0 (jeffcoach/indicators.py,
data.py, peg.py) sugli stessi dati sintetici: le formule di Jeff devono restare identiche."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TMP = Path(tempfile.mkdtemp(prefix="jc_test_"))
os.environ["JEFF_COACH_HOME"] = str(TMP)
os.environ.pop("JEFF_COACH_JEFF", None)            # configurazione vera: Jeff acceso ...
os.environ.pop("JEFF_COACH_META", None)            # ... e multi-edge acceso
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jeffcoach import config as C  # noqa: E402
from jeffcoach import data as D  # noqa: E402
from jeffcoach import engine as E  # noqa: E402
from jeffcoach import jeff as JF  # noqa: E402
from jeffcoach import journal as J  # noqa: E402
from jeffcoach import peg as PG  # noqa: E402
from jeffcoach.calendar_us import ET, open_et, prev_session  # noqa: E402

SESSION = date(2026, 10, 13)
AS_OF = prev_session(SESSION)


def synth(seed: int, drift: float, n: int = 420, vol: float = 0.02, price: float = 50.0, dvol: float = 6e6,
          end: str = "2026-10-09") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    r = rng.normal(drift, vol, n)
    c = price * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, vol / 3, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = rng.uniform(0.6, 1.4, n) * dvol
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=idx)


# ------------------------------------------------------------------ configurazione
def test_configurazione_multi_edge_e_jeff():
    """jeff-coach gira come l'istanza multi-edge di Martin (stesse impostazioni), da sola, con Jeff sopra."""
    assert C.JEFF and C.META_INSTANCE and C.JEFF_LONG_ONLY
    assert C.META_EDGES and C.META_RANK and C.META_RANK_MODE == "side" and not C.META_FILTER
    assert C.TL_CHART and C.HZ_CHART and C.CARD_FOCUS_CHARTS
    assert C.CONFLUENCE_MIN == 4 and C.POOL_ADR_REL == 1.2 and C.POOL_RS_WINDOW == 252
    assert C.DAILY_HISTORY_DAYS == C.CHART_DAILY_DAYS == 1900
    assert C.WRITE_HISTORY is True                                   # storico suo
    for p in (C.LISTS, C.JOURNAL, C.ALERTS_STATE, C.REPORTS, C.STATE, C.HISTORY):
        assert p.parent == C.HOME                                    # niente data/meta
    assert C.RULES_VERSION.endswith("-meta+jeff-2026-10-28")
    assert C.WEBHOOK_ENV == ("COACH_ALERT_DISCORD_WEBHOOK_URL",) and C.BOT_NAME == "Sydney"
    assert not set(C.WEBHOOK_ENV) & set(C.FORBIDDEN_WEBHOOK_ENV)
    assert C.EARNINGS_BLOCK_SESSIONS == C.JEFF_EARNINGS_SESSIONS == 5
    # soglie di Jeff come prima
    assert (C.JEFF_MCAP_MIN, C.JEFF_ADV_MIN, C.JEFF_ATR_PCT_MIN, C.JEFF_SCREEN_ADV_PREFILTER) == (1e9, 50e6, 2.8, 30e6)
    assert C.JEFF_EXCLUDED_INDUSTRIES == ("Biotechnology",) and C.JEFF_EXCLUDED_TICKERS == {"ADPT"}
    assert (C.JEFF_RS_MIN, C.JEFF_SMA200_SLOPE_BARS, C.JEFF_EXT_MAX, C.JEFF_SMA5_MAX_DIST_PCT) == (80, 5, 4.0, 5.0)
    assert (C.JEFF_MA1H_KIND, C.JEFF_MA1H_LEN, C.JEFF_BUCKET_MIN, C.JEFF_MA1H_SESSIONS) == ("ema", 50, 60, 25)
    assert (C.JEFF_EMA9_MAX_ATR, C.JEFF_VCP_MAX, C.JEFF_COMPRESSION_DAYS_MIN, C.JEFF_COMPRESSION_WINDOW) == (1.5, 25.0, 2, 3)
    assert C.PEG == dict(min_bars_ago=4, max_bars_ago=45, gap_min_pct=4.0, gap_min_atr=1.0, vol_mult=1.5, gap_big_pct=8.0,
                         range_below_atr=0.5, range_above_atr=1.0, range5_max_atr=2.5, atr5_atr20_max=0.8,
                         sma200_tol_atr=0.3, rs_min=60)


def test_webhook_solo_sydney(monkeypatch):
    """Card e alert solo col webhook di Sydney: mai quello di Dua (LISA) né quello di Remy / multi-edge di Martin."""
    from jeffcoach import discord as DS
    monkeypatch.setattr(DS, "load_env_file", lambda: None)
    for k in ("COACH_ALERT_DISCORD_WEBHOOK_URL", "LISA_DISCORD_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LISA_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/dua")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/remy")
    assert DS.webhook() is None
    monkeypatch.setenv("COACH_ALERT_DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/sydney")
    assert DS.webhook() == "https://discord.com/api/webhooks/sydney"
    # .env sbagliato: nella riga di Sydney c'è il webhook di un altro bot -> niente invio
    for k, other in (("DISCORD_WEBHOOK_URL", "remy"), ("LISA_DISCORD_WEBHOOK_URL", "dua"),
                     ("COACH_CARD_DISCORD_WEBHOOK_URL", "card-dua")):
        monkeypatch.setenv(k, f"https://discord.com/api/webhooks/{other}")
        monkeypatch.setenv("COACH_ALERT_DISCORD_WEBHOOK_URL", f"https://discord.com/api/webhooks/{other}")
        assert DS.webhook() is None
    assert "COACH_CARD_DISCORD_WEBHOOK_URL" in C.FORBIDDEN_WEBHOOK_ENV


# ------------------------------------------------------------------ formule identiche a prima
GOLD = {"1": dict(atr=2.219552227993778, adv=287473363.29904044, vcp=44.62858958443787, comp=1, rs=91,
                  ext=0.9788557621981896, ema9=49.847283352064764),
        "2": dict(atr=0.7980008363022607, adv=112243188.55937254, vcp=16.239041499775166, comp=2, rs=15,
                  ext=-2.51680619697135, ema9=17.65893833210349),
        "3": dict(atr=7.0922879941650425, adv=688271272.590694, vcp=39.575134940025904, comp=1, rs=98,
                  ext=7.13061675092424, ema9=152.79808125889568)}


def test_formule_di_jeff_identiche_a_prima():
    spx = synth(7, 0.0004, vol=0.009, price=6000, dvol=3e9)
    for seed, drift in ((1, 0.003), (2, -0.001), (3, 0.0015)):
        df = synth(seed, drift, vol=0.03, price=40 + seed)
        m = JF.metrics(df, spx.Close)
        g = GOLD[str(seed)]
        assert abs(m["j_atr"] - g["atr"]) < 1e-9 and abs(m["j_adv"] - g["adv"]) < 1e-3
        assert abs(m["j_vcp"] - g["vcp"]) < 1e-9 and m["j_compression"] == g["comp"] and m["j_rs"] == g["rs"]
        assert abs(m["j_ext"] - g["ext"]) < 1e-9 and abs(m["j_ema9"] - g["ema9"]) < 1e-9
        assert abs(m["j_ema9_dist_atr"] - (m["j_close"] - g["ema9"]) / g["atr"]) < 1e-12
        assert abs(m["j_atr_pct"] - g["atr"] / m["j_close"] * 100) < 1e-12


def test_compressione_2_su_3():
    """Compressione: almeno 2 delle ultime 3 sedute con range% < ADR20% dello stesso giorno; un solo giorno largo non
    azzera i precedenti (caso PLTR)."""
    n = 60
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    c = np.full(n, 100.0)
    rng = np.full(n, 4.0)                      # range normale 4%
    rng[-3], rng[-2], rng[-1] = 1.0, 9.0, 1.0  # stretto, largo, stretto
    df = pd.DataFrame({"Open": c, "High": c * (1 + rng / 100), "Low": c, "Close": c, "Volume": 1e6}, index=idx)
    assert JF.compression_days(df) == 2
    g = dict((k, ok) for k, ok, _ in JF.focus_gates({"j_compression": 2}, None))
    assert g["comp"] is True
    rng[-3] = 9.0                              # due giorni larghi su tre
    df = pd.DataFrame({"Open": c, "High": c * (1 + rng / 100), "Low": c, "Close": c, "Volume": 1e6}, index=idx)
    assert JF.compression_days(df) == 1


def test_barre_da_un_ora_ed_ema50():
    """EMA50 sulle barre da 1 ora costruite dai 5 minuti (7 barre al giorno dalle 9:30, l'ultima di mezz'ora), come
    prima; valore di riferimento calcolato con il codice vecchio."""
    days = pd.bdate_range("2026-09-14", periods=25)
    rows = []
    rng = np.random.default_rng(5)
    px = 100.0
    for d in days:
        for k in range(78):
            t = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30 + 5 * k)
            px *= float(np.exp(rng.normal(0.0002, 0.002)))
            rows.append((t, px, px * 1.001, px * 0.999, px, 1e4))
    b = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")
    bk = JF.buckets(b, {d.date().isoformat() for d in days})
    assert len(bk) == 175 and bk[0][:2] == ("2026-09-14", 0) and bk[-1][:2] == ("2026-10-16", 6)
    assert abs(JF.ma_of([x[2] for x in bk]) - 151.77133448247943) < 1e-9
    seen = {}

    def dl(ch):
        seen["ch"] = list(ch)
        return pd.concat({"AAA": b}, axis=1)
    out = JF.ma_1h(["AAA"], date(2026, 10, 16), download=dl)
    assert seen["ch"] == ["AAA"] and abs(out["AAA"]["ma1h"] - 151.77133448247943) < 1e-9


def _peg_df():
    n = 260
    idx = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=n)
    rng = np.random.default_rng(11)
    c = 50 * np.exp(np.cumsum(rng.normal(0.001, 0.012, n)))
    g = n - 21                                    # gap 20 sedute fa
    c[g:] = c[g:] * 1.12                          # +12% e si tiene
    base = c[g + 2]
    c[-12:] = base * (1 + rng.normal(0, 0.004, 12))   # base stretta nel range del gap
    o = c * (1 + rng.normal(0, 0.002, n))
    o[g] = c[g - 1] * 1.10
    h = np.maximum(o, c) * 1.006
    lo = np.minimum(o, c) * 0.994
    v = rng.uniform(0.8, 1.2, n) * 2e6
    v[g] = 9e6
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=idx)


def test_peg_identico_a_prima():
    df = _peg_df()
    pg = PG.read_peg(df, float(JF.atr(df).iloc[-1]))
    gold = dict(peg_found=True, peg_date="2026-09-11", peg_bars_ago=20, peg_gap_pct=10.0, peg_vol_mult=4.614039,
                peg_day_low=64.322339, peg_day_high=72.809354, peg_gap_day_low=70.330046, peg_after_high=73.535369,
                peg_run_after_pct=0.997145, peg_pos=0.921434, peg_range5_atr=1.257345, peg_atr5_20=0.829918,
                peg_higher_low=True, peg_pivot=73.336031, peg_ok=True, peg_why=[])
    for k, v in gold.items():
        assert (abs(pg[k] - v) < 1e-5) if isinstance(v, float) else pg[k] == v, k
    assert PG.confirm_earnings(pg, ["2026-09-10"]) is True       # utili la sera prima del gap
    assert PG.confirm_earnings(pg, ["2026-08-01"]) is False
    assert PG.confirm_earnings(pg, []) is None


# ------------------------------------------------------------------ universo, gate, regole sostituite
def test_universo_di_jeff():
    ok = dict(j_adv=60e6, j_atr_pct=3.0)
    info = {"quote_type": "EQUITY", "exchange": "NMS", "mcap": 5e9}
    assert JF.universe_reason("AAA", ok, info, "Software—Application") is None
    assert JF.universe_reason("AAA", ok, info, "Utilities—Regulated Electric") is None    # Martin la esclude, Jeff no
    assert JF.universe_reason("AAA", ok, info, "Biotechnology").startswith("single-name")
    assert JF.universe_reason("ADPT", ok, info, "Diagnostics & Research") == "biotech (manual list)"
    assert JF.universe_reason("AAA", ok, dict(info, mcap=9e8), None).startswith("market cap")
    assert JF.universe_reason("AAA", ok, dict(info, quote_type="ETF"), None).startswith("not a stock")
    assert JF.universe_reason("AAA", dict(ok, j_adv=49e6), info, None).startswith("adv$")
    assert JF.universe_reason("AAA", dict(ok, j_atr_pct=2.79), info, None).startswith("ATR%")


def test_gli_8_gate_del_focus():
    m = dict(j_rs=85, j_above_sma200=True, j_sma200_slope_ok=True, j_ext=3.9, j_sma5_dist_pct=-4.9, j_close=100.0,
             j_ema9_dist_atr=0.8, j_vcp=20.0, j_compression=2)
    assert JF.gate_fields(m, 98.0)["jeff_ok"] is True
    for k, v, code in (("j_rs", 79, "rs"), ("j_sma200_slope_ok", False, "sma200"), ("j_above_sma200", False, "sma200"),
                       ("j_ext", 4.01, "ext"), ("j_sma5_dist_pct", 5.1, "sma5"), ("j_ema9_dist_atr", 0.0, "ema9"),
                       ("j_ema9_dist_atr", 1.51, "ema9"), ("j_vcp", 25.1, "vcp"), ("j_compression", 1, "comp")):
        f = JF.gate_fields(dict(m, **{k: v}), 98.0)
        assert f["jeff_ok"] is False and f["jeff_open"] == [code], (k, v, f)
    f = JF.gate_fields(m, 100.5)                                     # close sotto la EMA50 a 1 ora
    assert f["jeff_open"] == ["ma1h"] and "under 1h EMA50" in f["jeff_why"]
    assert JF.gate_fields(m, None)["jeff_open"] == ["ma1h"]          # senza barre da 1 ora il gate resta aperto


def test_regole_long_di_martin_sostituite_da_jeff():
    """Liquidità, ADR, estensione dalla SMA50 e distanza dalla EMA9 di Martin non contano: vale Jeff."""
    df = synth(1, 0.003, vol=0.035, price=41)
    q = synth(105, 0.001, vol=0.01, price=400, dvol=5e7)
    m = E.compute_metrics(df, q)
    ok, info = E.long_candidate("T01", m)
    assert not set(C.JEFF_REPLACES_LONG_CHECKS) & set(info["checks"])
    for k in ("list", "trend", "no_streak", "linear_trend", "trend_tf", "weekly_healthy", "confluence"):
        assert k in info["checks"]                                     # le altre regole di Martin restano


def test_utili_finestra_di_5_sedute():
    raw = {"AAA": {"calendar": ["2026-10-19"]}, "BBB": {"earnings_dates": ["2026-10-20"]}, "CCC": {}}
    uni = {"CCC": {"earnings": "2026-10-14"}}
    ec = JF.earnings_check(["AAA", "BBB", "CCC"], raw, uni, SESSION)     # seduta 13/10: finestra 13-19/10
    assert ec["window"] == ["2026-10-13", "2026-10-19"]
    assert ec["out"] == {"AAA": "2026-10-19", "CCC": "2026-10-14"} and ec["next"]["BBB"] == "2026-10-20"


# ------------------------------------------------------------------ lista, card, txt e alert dall'inizio alla fine
FORCE = ("T01", "T03", "T06", "T09", "T11", "T02")       # candidati long di Martin forzati (le regole di Martin sono
#                                                          provate in test_offline.py)


def _world():
    daily = {}
    for i in range(40):
        drift = 0.003 if i < 20 else -0.003
        daily[f"T{i:02d}"] = synth(i, drift, vol=0.035, price=40 + i, end=str(AS_OF))
    for k, d in (("QQQ", 0.001), ("IWM", 0.0005), ("SPY", 0.0008)):
        daily[k] = synth(100 + len(k), d, vol=0.01, price=400, dvol=5e7, end=str(AS_OF))
    daily["^GSPC"] = synth(7, 0.0004, vol=0.009, price=6000, dvol=3e9, end=str(AS_OF))
    for k in C.SECTOR_ETFS:
        daily[k] = synth(200 + len(k), 0.0, vol=0.012, price=60, end=str(AS_OF))
    uni = {s: {"exchange": "NMS", "quote_type": "EQUITY", "mcap": 5e9, "dv3m": 2e8} for s in daily if s.startswith("T")}
    uni["T08"]["mcap"] = 8e8                                 # sotto 1 mld: fuori dall'universo di Jeff
    uni["T09"]["dv3m"] = 4e7                                 # prefiltro 30-50M$: solo Jeff (Martin non lo scarica)
    ind = {s: {"industry": "Semis" if int(s[1:]) % 2 else "Software"} for s in uni}
    ind["T05"]["industry"] = "Biotechnology"                 # fuori per Jeff e per Martin
    ind["T06"]["industry"] = "Utilities—Regulated Electric"  # fuori per Martin, dentro per Jeff
    return daily, uni, ind


def _install(monkeypatch, bias="LONG"):
    from jeffcoach import daily as DL
    from jeffcoach import themes_map as TM
    daily, uni, ind = _world()
    calls = {}
    monkeypatch.setattr(D, "download_intraday", lambda *a, **k: {})
    monkeypatch.setattr(D, "build_universe", lambda *a, **k: uni)
    monkeypatch.setattr(D, "build_industry_map", lambda *a, **k: ind)

    def dl_daily(syms, start, end, **k):
        calls.setdefault("daily", []).append(list(syms))
        return {s: daily[s] for s in syms if s in daily}
    monkeypatch.setattr(D, "download_daily", dl_daily)
    monkeypatch.setattr(D, "next_earnings", lambda syms, since: {s: None for s in syms})

    def fetch_earnings(syms, since, workers=8):
        calls["earnings"] = sorted(syms)
        out = {s: {"calendar": [], "earnings_dates": [], "past_dates": []} for s in syms}
        if "T02" in out:
            out["T02"]["calendar"] = ["2026-10-15"]           # dentro la finestra di 5 sedute: fuori da tutto
        if "T04" in out:
            out["T04"]["past_dates"] = ["2026-09-10"]          # utili prima del gap: PEG confermato
        return out
    monkeypatch.setattr(D, "fetch_earnings", fetch_earnings)
    fake_map = {"built_utc": "2026-10-12T00:00:00+00:00",
                "tickers": {s: {"primary": "Software" if int(s[1:]) % 2 else "Semiconductors",
                                "themes": ["Software" if int(s[1:]) % 2 else "Semiconductors"], "source": "etf"} for s in uni},
                "themes": {"Software": "etf", "Semiconductors": "etf"},
                "theme_etfs": {"Software": ["IGV"], "Semiconductors": ["SOXX"]}, "proxy_etfs": {}}
    monkeypatch.setattr(TM, "refresh", lambda *a, **k: fake_map)
    # misure di Jeff controllate: tutti nell'universo (liquidi e volatili); T01 chiude tutti i gate, T03 ha il VCP largo
    real_metrics = JF.metrics

    def jm(df, spx):
        m = real_metrics(df, spx)
        if not m:
            return m
        m.update(j_adv=3e8, j_atr_pct=4.0, j_rs=90, j_above_sma200=True, j_sma200_slope_ok=True, j_ext=2.0,
                 j_sma5_dist_pct=1.0, j_ema9_dist_atr=0.5, j_vcp=10.0, j_compression=3, j_sma200=m["j_close"] * 0.9)
        return m
    monkeypatch.setattr(JF, "metrics", jm)
    over = {"T03": dict(j_vcp=40.0), "T11": dict(j_rs=70)}
    real_lc = E.long_candidate

    def lc(t, m):
        ok, info = real_lc(t, m)
        if t in FORCE:
            for k, v in over.get(t, {}).items():
                m[k] = v
            info["checks"] = {k: True for k in info["checks"]}
            info["level"] = {"price": m["close"] * 0.98, "members": ["EMA21", "AVWAP SL", "SH", "gap"], "count": 4,
                             "dist_pct": 2.0}
            return True, info
        return ok, info
    monkeypatch.setattr(E, "long_candidate", lc)
    monkeypatch.setattr(JF, "ma_1h", lambda syms, as_of, **k: {s: ({"ma1h": daily[s].Close.iloc[-1] * 0.97}
                                                                  if s != "T09" else {"err": "no 5m data"}) for s in syms})
    real_peg = PG.read_peg

    def rp(df, atr):
        if abs(float(df.Close.iloc[-1]) - float(daily["T04"].Close.iloc[-1])) < 1e-9:
            c = float(df.Close.iloc[-1])
            return dict(peg_found=True, peg_ok=True, peg_why=[], peg_date="2026-09-11", peg_bars_ago=20, peg_gap_pct=10.0,
                        peg_vol_mult=4.6, peg_day_low=c * 0.93, peg_day_high=c * 1.02, peg_gap_day_low=c * 0.97,
                        peg_after_high=c * 1.03, peg_run_after_pct=1.0, peg_pos=0.8, peg_range5_atr=1.2, peg_atr5_20=0.8,
                        peg_higher_low=True, peg_pivot=c * 1.01)
        return real_peg(df, atr)
    monkeypatch.setattr(PG, "read_peg", rp)
    real_bc = E.best_cluster

    def bc(levels, close, need=None):                         # livello del PEG di T04: 4 supporti a -1,5%
        if levels is not None and abs(close - float(daily["T04"].Close.iloc[-1])) < 1e-9:
            return {"price": close * 0.985, "members": ["EMA21", "AVWAP vol", "SH", "gap"], "count": 4, "dist_pct": 1.5}
        return real_bc(levels, close, need)
    monkeypatch.setattr(E, "best_cluster", bc)
    reg = {"bias": bias, "score": 3 if bias == "LONG" else -3, "score_bias": bias, "risk_pct": C.RISK_PCT, "why": ["test"]}
    monkeypatch.setattr(E, "regime_martin", lambda *a, **k: dict(reg, why=list(reg["why"])))
    monkeypatch.setattr(E, "regime_pool", lambda *a, **k: dict(reg, why=list(reg["why"])))
    work = C.LISTS / f"work_{SESSION}"
    if work.exists():
        shutil.rmtree(work)
    return DL, daily, calls


def test_lista_card_e_txt(monkeypatch):
    DL, daily, calls = _install(monkeypatch)
    assert DL.main(["--session", SESSION.isoformat()]) == 0
    work = C.LISTS / f"work_{SESSION}"
    det = json.loads((work / "detail.json").read_text())
    cands = {r["ticker"]: r for r in det["candidates"]}
    # solo long, solo universo di Jeff: niente biotech (T05) né mcap sotto 1 mld (T08); dentro utility (T06) e T09
    assert all(r["side"] == "long" for r in det["candidates"] + det["near_misses"])
    assert "T05" not in cands and "T08" not in cands and {"T01", "T03", "T06", "T09", "T11"} <= set(cands)
    assert any("T09" in ch for ch in calls["daily"]) and "T06" in calls["daily"][0]
    # utili nella finestra: fuori da tutto (candidati, a un passo, tracking, Focus)
    assert "T02" not in cands and "T02" not in det["tracking"] and det["jeff"]["earnings_out"] == {"T02": "2026-10-15"}
    # Focus solo con gli 8 gate chiusi; chi ne ha uno aperto resta in tracking
    focus = [r["ticker"] for r in det["focus"]]
    assert all(r["jeff_ok"] for r in det["focus"]) and "T01" in focus
    assert {"T03", "T09", "T11"}.isdisjoint(focus) and {"T03", "T09", "T11"} <= set(det["tracking"])
    assert cands["T03"]["jeff_open"] == ["vcp"] and cands["T09"]["jeff_open"] == ["ma1h"] and cands["T11"]["jeff_open"] == ["rs"]
    assert det["jeff"]["held_by_gates"]["T03"].startswith("VCP")
    # edge del multi-edge su candidati e PEG
    assert all("n_edges" in r for r in det["candidates"] + det["peg_watch"] if r.get("level") is not None)
    # PEG: T04 con il livello del sistema, nella card, nel txt e nella lista pubblica per gli alert
    peg = {r["ticker"]: r for r in det["peg_watch"]}
    assert "T04" in peg and peg["T04"]["tradable"] and peg["T04"]["setup"] == "PEG delayed reaction"
    assert peg["T04"]["level"] and peg["T04"]["confluence"] >= C.CONFLUENCE_MIN and not peg["T04"]["counter"]
    pub = json.loads((C.LISTS / "today.json").read_text())
    assert [r["ticker"] for r in pub["peg_watch"]] == list(peg)
    txt = (C.LISTS / f"watchlist_{SESSION}.txt").read_text()
    assert "###PEG" in txt and "NASDAQ:T04" in txt.split("###PEG")[1] and "SHORT" not in txt
    card = json.loads((work / "card.json").read_text())["embeds"]
    alltext = "\n".join(e.get("description") or "" for e in card)
    assert "JEFF COACH WATCHLIST" in alltext and "PEG — delayed reaction" in alltext and "**T04**" in alltext
    assert "FOCUS SHORT" not in alltext and "Jeff RS 90" in alltext and "short —" not in alltext
    # misure di mercato di Martin sul suo universo: i titoli solo di Jeff non entrano nelle liste della breadth
    lists = json.loads((C.HISTORY / f"lists_{AS_OF}.json").read_text())
    assert "T06" not in lists and "T09" not in lists and "T05" not in lists
    summ = (work / "summary_it.md").read_text()
    assert "Fermati dai gate di Jeff" in summ and "PEG delayed reaction" in summ and "Fuori per utili" in summ


def test_regime_short_niente_focus_e_peg_informativi(monkeypatch):
    """Bot solo long: col regime SHORT niente Focus; i migliori long (con gli 8 gate chiusi) restano come "contro il
    regime" e i PEG mandano solo alert informativi (trade ombra)."""
    DL, daily, _ = _install(monkeypatch, bias="SHORT")
    assert DL.main(["--session", SESSION.isoformat()]) == 0
    det = json.loads((C.LISTS / f"work_{SESSION}" / "detail.json").read_text())
    assert det["focus"] == []
    assert det["counter_focus"] and all(r["jeff_ok"] and r["side"] == "long" for r in det["counter_focus"])
    assert all(r["counter"] for r in det["peg_watch"])
    card = json.loads((C.LISTS / f"work_{SESSION}" / "card.json").read_text())["embeds"]
    t = "\n".join(e.get("description") or "" for e in card)
    assert "long-only bot, no entries" in t and "against the regime" in t


def test_alert_e_giornale_del_peg(monkeypatch):
    """Il PEG con il livello passa dal trigger del sistema: tocco del livello, inversione, rottura della barra a 5
    minuti; trade simulato con setup "PEG delayed reaction" e alert "PEG"."""
    from jeffcoach import alerts as A
    sent = []
    monkeypatch.setattr(A, "send_alert", lambda title, body, kind="info", dry_run=False, image=None, image2=None:
                        sent.append(title) or {"sent": True})
    monkeypatch.setattr(A, "alert_chart", lambda *a, **k: None)
    monkeypatch.setattr(A, "group_chart", lambda *a, **k: None)
    monkeypatch.setattr(A, "hourly_bars", lambda tickers: {})
    C.LISTS.mkdir(parents=True, exist_ok=True)
    peg = {"ticker": "T04", "side": "long", "level": 100.0, "level_members": ["EMA21", "AVWAP vol", "SH", "gap"],
           "adr": 5.0, "dv5": 6e8, "adv50": 3e8, "confluence": 4, "setup": "PEG delayed reaction", "peg": True,
           "tradable": True, "also_focus": False, "counter": False, "peg_text": "PEG 2026-09-11 +10% (4.6x vol)",
           "jeff_rs": 88}
    lst = {"session_date": SESSION.isoformat(), "bias": "LONG", "qqq_prev_close": 400.0, "indices": {}, "breadth": {},
           "focus": [], "counter_focus": [], "peg_watch": [peg, dict(peg, ticker="T07", tradable=False)]}
    (C.LISTS / "today.json").write_text(json.dumps(lst))
    o = open_et(SESSION)
    idx = pd.date_range(o, periods=30, freq="1min", tz=ET)
    px = np.r_[np.linspace(101.5, 100.2, 18), np.linspace(100.3, 100.9, 12)]
    bars = pd.DataFrame({"Open": px, "High": px + 0.05, "Low": px - 0.05, "Close": px, "Volume": 1e5}, index=idx)
    qqq = pd.DataFrame({"Open": 400.5, "High": 401, "Low": 400, "Close": 400.5, "Volume": 1e6}, index=idx)
    asked = {}

    def intraday(tickers, interval="1m", **k):
        asked["t"] = sorted(tickers)
        return {"T04": bars, "QQQ": qqq} if interval == "1m" else {}
    monkeypatch.setattr(D, "download_intraday", intraday)
    A.run_once(dry_run=True, now=(idx[-1] + timedelta(seconds=30)).to_pydatetime())
    assert "T04" in asked["t"] and "T07" not in asked["t"]          # senza livello niente alert
    ps = [p for p in J.positions() if p["ticker"] == "T04"]
    assert ps and ps[0]["setup"] == "PEG delayed reaction" and ps[0]["jeff_rs"] == 88
    assert any(t.startswith("T04 · PEG") for t in sent), sent


if __name__ == "__main__":
    import pytest
    try:
        sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
