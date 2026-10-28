"""Prove senza rete della BASE (bot Martin, Martin-coach main @062aae2): le stesse prove del repo di Martin, con il
pacchetto rinominato. [JEFF] Girano con la parte di Jeff spenta e il multi-edge spento (JEFF_COACH_JEFF=0,
JEFF_COACH_META=0), cioè con le regole di Dua come nel repo di Martin: dimostrano che la base è rimasta la stessa.
Le prove della parte di Jeff e della configurazione vera sono in tests/test_jeff.py.
Uso: python tests/test_offline.py  oppure  JEFF_TEST_SUITE=base python -m pytest tests -q"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TMP = Path(tempfile.mkdtemp(prefix="mc_test_"))
os.environ["JEFF_COACH_HOME"] = str(TMP)
os.environ.setdefault("JEFF_COACH_JEFF", "0")      # [JEFF] base di Martin: parte di Jeff spenta ...
os.environ.setdefault("JEFF_COACH_META", "0")      # [JEFF] ... e regole di Dua (in Martin il multi-edge è spento di default)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jeffcoach import config as C  # noqa: E402
from jeffcoach import data as D  # noqa: E402
from jeffcoach import engine as E  # noqa: E402
from jeffcoach import journal as J  # noqa: E402
from jeffcoach.calendar_us import ET, open_et, prev_session  # noqa: E402

SESSION = date(2026, 10, 13)
AS_OF = prev_session(SESSION)


def synth(seed: int, drift: float, n: int = 420, vol: float = 0.02, price: float = 50.0, dvol: float = 6e6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    r = rng.normal(drift, vol, n)
    c = price * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, vol / 3, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = rng.uniform(0.6, 1.4, n) * dvol
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}, index=idx)


def fake_world():
    daily = {}
    for i in range(40):
        drift = 0.003 if i < 20 else -0.003
        daily[f"T{i:02d}"] = synth(i, drift, vol=0.035, price=40 + i)
    for k, d in (("QQQ", 0.001), ("IWM", 0.0005), ("SPY", 0.0008)):
        daily[k] = synth(100 + len(k), d, vol=0.01, price=400, dvol=5e7)
    for k in C.SECTOR_ETFS:
        daily[k] = synth(200 + len(k), 0.0, vol=0.012, price=60)
    uni = {s: {"exchange": "NMS", "quote_type": "EQUITY"} for s in daily if s.startswith("T")}
    ind = {s: {"industry": "Semis" if int(s[1:]) % 2 else "Software"} for s in uni}
    return daily, uni, ind


def test_metrics_and_candidates():
    daily, _, _ = fake_world()
    m = E.compute_metrics(daily["T01"], daily["QQQ"])
    assert m["list"] in ("Leading", "Mediocre", "Lagging")
    ok, info = E.long_candidate("T01", m)
    assert "confluence" in info["checks"]
    lv = E.best_cluster([{"name": "a", "price": 100}, {"name": "b", "price": 100.5}, {"name": "c", "price": 90}], 101)
    assert lv["count"] == 2 and abs(lv["price"] - 100.25) < 1e-9


def test_daily_build(monkeypatch=None):
    from jeffcoach import data as _D
    _D.download_intraday = lambda *a, **k: {}
    daily, uni, ind = fake_world()
    from jeffcoach import daily as DL
    D.build_universe = lambda *a, **k: uni
    D.build_industry_map = lambda *a, **k: ind
    D.download_daily = lambda syms, start, end, **k: {s: daily[s] for s in syms if s in daily}
    D.next_earnings = lambda syms, since: {s: None for s in syms}
    from jeffcoach import themes_map as TM
    fake_map = {"built_utc": "2026-10-12T00:00:00+00:00",
                "tickers": {s: {"primary": "Software" if int(s[1:]) % 2 else "Semiconductors",
                                "themes": ["Software" if int(s[1:]) % 2 else "Semiconductors"], "source": "etf"} for s in uni},
                "themes": {"Software": "etf", "Semiconductors": "etf"},
                "theme_etfs": {"Software": ["IGV"], "Semiconductors": ["SOXX", "SMH"], "Gold": ["GLD"]},
                "proxy_etfs": {"Gold": ["GLD"]}}
    daily["GLD"] = synth(321, 0.002, vol=0.01, price=300, dvol=2e6)
    TM.refresh = lambda *a, **k: fake_map
    rc = DL.main(["--session", SESSION.isoformat()])
    assert rc == 0
    pub = (C.LISTS / "today.json").read_text()
    assert '"session_date": "2026-10-13"' in pub
    assert (C.LISTS / f"work_{SESSION}" / "card.json").exists()
    import json as _j
    th = _j.loads((C.LISTS / f"work_{SESSION}" / "themes_card.json").read_text())["embeds"][0]["description"]
    assert "Leading in uptrend" in th and "Breaking down" in th and "★" not in th
    assert (C.HISTORY / f"lists_{AS_OF}.json").exists()
    det = _j.loads((C.LISTS / f"work_{SESSION}" / "detail.json").read_text())
    gold = [r for r in det["themes"] if r["theme"] == "Gold"]
    assert gold and gold[0]["members"] == ["GLD"]                 # ETF senza azioni: l'ETF stesso è il tema
    assert all(r["ticker"] != "GLD" for r in det["focus"] + det.get("counter_focus", []))


def test_daily_basket_lst():
    """Temi = basket di Lone Stock Trader [21/10]: classifica sul 7-factor medio dei titoli, RS settimana/mese in
    percentile, grafico in testa al messaggio dei temi; i titoli dei basket fuori universo non diventano candidati."""
    from jeffcoach import data as _D
    _D.download_intraday = lambda *a, **k: {}
    daily, uni, ind = fake_world()
    from jeffcoach import daily as DL
    from jeffcoach import themes_map as TM
    D.build_universe = lambda *a, **k: uni
    D.build_industry_map = lambda *a, **k: ind
    D.download_daily = lambda syms, start, end, **k: {s: daily[s] for s in syms if s in daily}
    D.next_earnings = lambda syms, since: {s: None for s in syms}
    daily["XOUT"] = synth(777, 0.004, vol=0.03, price=30, dvol=9e7)        # nel basket, fuori universo
    baskets = {"UP A": [f"T{i:02d}" for i in range(0, 8)], "UP B": [f"T{i:02d}" for i in range(8, 20)] + ["XOUT"],
               "DOWN A": [f"T{i:02d}" for i in range(20, 30)], "DOWN B": [f"T{i:02d}" for i in range(30, 40)],
               "MIX": ["T01", "T21", "T02", "T22"], "TINY": ["T03", "NOPE"]}
    m = TM.build_lst_map(baskets, {"aggiungi": {}, "togli": {}})
    assert m["tickers"]["T01"]["primary"] == "MIX" and m["tickers"]["T05"]["primary"] == "UP A"
    assert m["tickers"]["T03"]["primary"] == "TINY"                       # il basket più piccolo
    TM.refresh = lambda *a, **k: {"built_utc": "2026-10-12T00:00:00+00:00", "membership": "lst", "theme_etfs": {},
                                  "baskets_fetched_utc": "2026-10-12T23:00:00+00:00", **m}
    work = C.LISTS / f"work_{SESSION}"
    if work.exists():
        shutil.rmtree(work)
    assert DL.main(["--session", SESSION.isoformat()]) == 0
    import json as _j
    import json
    det = _j.loads((work / "detail.json").read_text())
    names = [r["theme"] for r in det["themes"]]
    assert "TINY" not in names and names[0].startswith("UP")              # TINY: 1 solo titolo con storia
    assert all(r.get("rs_w") is not None and 0 < r["rs_m"] <= 100 for r in det["themes"])
    assert all(r["ticker"] != "XOUT" for r in det["focus"] + det.get("counter_focus", []) + det["candidates"])
    emb = _j.loads((work / "themes_card.json").read_text())["embeds"]
    assert len(emb) == 2 and emb[0]["image"]["url"] == "attachment://themes_rs.png"     # [ANDREA 28/10] senza classifica
    assert emb[1]["image"]["url"] == "attachment://themes_rs_3m.png" and "Lone Stock" not in json.dumps(emb)
    assert "Overall ranking" not in json.dumps(emb) and "Leading in uptrend" not in json.dumps(emb)
    assert (work / "themes_rs_3m.png").exists()
    assert (work / "themes_rs.png").read_bytes()[:4] == b"\x89PNG"
    assert sum(len(e["description"]) for e in emb) <= 5900


def test_lst_parse_e_sessione():
    from jeffcoach import lst_baskets as L
    rsc = ('{"id":"basket-ai","children":[["$","h2",null,{"children":"AI"}],["$","$L13",null,{"tickers":["NVDA","MU","NVDA"]}]]}'
           '{"id":"basket-oil","children":[["$","h2",null,{"children":"OIL AND GAS"}],["$","x",null,{"tickers":["XOM"]}]]}')
    assert L.parse(rsc) == {"AI": ["NVDA", "MU"], "OIL AND GAS": ["XOM"]}
    sess = {"access_token": "a" * 900, "refresh_token": "r", "user": {"id": "x" * 3000}}
    ck = L._encode(sess)
    assert len(ck) == 2 and L._decode(L._joined(ck)) == sess
    assert L._apply_set_cookie(ck, [L.COOKIE + ".0=NEW; Path=/", L.COOKIE + ".1=; Max-Age=0"])
    assert ck == {L.COOKIE + ".0": "NEW"}
    try:
        L.check({"A": ["X"]})
        raise AssertionError("doveva fallire")
    except L.LSTError:
        pass


def test_temi_solo_etf():
    """Temi = gruppi ETF della lista di Andrea; tema principale = ETF dove il titolo pesa di più; gruppi generici esclusi."""
    from jeffcoach import themes_map as TM
    groups = {"SOXX": "Semiconductors", "IGV": "Software", "MTUM": "Momentum"}
    TM.ETF_SKIP = {"Momentum"}
    hold = {"SOXX": [{"symbol": "NVDA", "weight": 0.09}, {"symbol": "MSFT", "weight": 0.01}],
            "IGV": [{"symbol": "MSFT", "weight": 0.08}], "MTUM": [{"symbol": "HPQ", "weight": 0.05}]}
    m = TM.build_map(groups, hold, {"aggiungi": {"FROG": "Software"}, "togli": {}})
    t = m["tickers"]
    assert t["NVDA"]["primary"] == "Semiconductors" and t["MSFT"]["primary"] == "Software"
    assert t["MSFT"]["themes"] == ["Semiconductors", "Software"]
    assert "HPQ" not in t and "Momentum" not in m["themes"]
    assert t["FROG"] == {"primary": "Software", "themes": ["Software"], "source": "manuale"}
    assert m["theme_etfs"] == {"Semiconductors": ["SOXX"], "Software": ["IGV"]}
    TM.ETF_SKIP = set()
    m2 = TM.build_map(groups, hold)
    assert "Momentum" in m2["themes"]
    assert m2["tickers"]["HPQ"] == {"primary": None, "themes": ["Momentum"], "source": "etf"}   # generico: mai principale


def test_partecipazioni_complete_nport():
    """N-PORT: solo azioni lunghe, CUSIP -> ticker dalla cache, pesi sommati; riserva NEL per chi non ha N-PORT."""
    from jeffcoach import etf_holdings as EH
    xml = ("<invstOrSec><name>Qualcomm</name><cusip>747525103</cusip><identifiers><isin value='x'/></identifiers>"
           "<pctVal>3.5</pctVal><payoffProfile>Long</payoffProfile><assetCat>EC</assetCat></invstOrSec>"
           "<invstOrSec><name>Cash</name><cusip>000000000</cusip><pctVal>1</pctVal><payoffProfile>Long</payoffProfile>"
           "<assetCat>STIV</assetCat></invstOrSec>")
    rows = EH.parse_nport(xml)
    assert rows == [{"cusip": "747525103", "isin": "", "name": "Qualcomm", "weight": 0.035}]
    old = (EH.series_index, EH.latest_nport, EH.map_ids)
    try:
        EH.series_index = lambda: {"SMH": "S1"}
        EH.latest_nport = lambda sid: xml
        EH.map_ids = lambda ids, cache, **k: cache.update({i: "QCOM" for i in ids})
        out, st = EH.fetch_full(["SMH", "GLD", "BLOK"], {"BLOK": [{"symbol": "COIN", "weight": 0.03}]})
    finally:
        EH.series_index, EH.latest_nport, EH.map_ids = old
    assert out["SMH"] == [{"symbol": "QCOM", "weight": 0.035}] and out["BLOK"][0]["symbol"] == "COIN"
    assert st == {"nport": ["SMH"], "fallback": ["BLOK"], "none": ["GLD"]}


def test_market_monitor_nostro():
    """Backup del Market Monitor: righe calcolate dai nostri titoli, calibrate sullo storico NEL."""
    from jeffcoach import breadth as B
    daily, uni, _ = fake_world()
    own = B.own_rows({s: daily[s] for s in uni})
    assert own and own[0]["date"] == AS_OF.isoformat() and 0 <= own[0]["t2108"] <= 100
    nel = [dict(r, up4=r["up4"] * 5, down4=r["down4"] * 5, up25q=r["up25q"] * 5 + 1, down25q=r["down25q"] * 5 + 1)
           for r in own]
    cal = B.calibrate(own, nel)
    assert cal and abs(cal["k"]["up4"] - 5) < 0.01 and cal["state_agreement"] > 0.9
    rows = B.update(own, nel)
    assert rows[0]["source"] == "own" and (C.HOME / "breadth" / "calibrazione.json").exists()
    B.archive_nel(nel[:3])
    assert any(r["date"] == AS_OF.isoformat() for r in B.nel_archive())


def test_market_monitor_fonti():
    """Foglio Stockbee letto da noi; se Stockbee e NEL non rispondono si usa l'archivio nel repo."""
    from jeffcoach import stockbee as SB, breadth as B
    txt = (",Primary Breadth Indicators,,,\n"
           "Date,Number of stocks up 4% plus today,Number of stocks down 4% plus today,5 day ratio,10 day  ratio ,"
           "Number of stocks up 25% plus in a quarter,Number of stocks down 25% + in a quarter,T2108,S&P\n"
           '10/14/2026,77,784,0.32,0.52,642,1575,24.50,"7,718.94"\n')
    r = SB.parse_csv(txt)[0]
    assert r == {"date": "2026-10-14", "up4": 77.0, "down4": 784.0, "ratio5": 0.32, "ratio10": 0.52,
                 "up25q": 642.0, "down25q": 1575.0, "t2108": 24.5, "sp": 7718.94}
    B.archive_nel([dict(r, date="2099-01-02")])
    old = (SB.fetch, C.MM_URLS)
    try:
        def boom(*a, **k):
            raise RuntimeError("offline")
        SB.fetch = boom
        C.MM_URLS = ("http://127.0.0.1:9/none.json",)
        rows = D.fetch_market_monitor()
    finally:
        SB.fetch, C.MM_URLS = old
    assert rows and rows[0]["date"] == "2099-01-02"


def test_journal_cycle():
    ctx = dict(ticker="T05", side="long", setup="pullback long", dv5=6e8, adr=4.0, level=50.0)
    p = J.open_trade(ctx, 50.0, 49.5, None, SESSION, 20)
    assert p["shares"] > 0 and not p["shadow"]
    assert abs(p["risk_usd"] / C.START_EQUITY * 100 - C.RISK_PCT) < 0.05 or p["size_pct"] <= C.SIZE_MAX_PCT + 0.01
    ps = J.positions()
    J.fill(ps[0], ps[0]["shares_open"], 52.0, "exit", "test")
    J.commit(ps, SESSION)
    rows = J.read_csv(J.TRADES)
    assert rows and float(rows[-1]["r_multiple"]) > 3
    sh = J.open_trade(dict(ctx, ticker="T06"), 50.0, 49.0, "freno: massimo trade del giorno", SESSION, 30)
    assert sh["shadow"]


def test_alerts_trigger():
    from jeffcoach import alerts as A
    import json
    C.LISTS.mkdir(parents=True, exist_ok=True)
    lst = {"session_date": SESSION.isoformat(), "bias": "LONG", "qqq_prev_close": 400.0, "indices": {}, "breadth": {},
           "focus": [{"ticker": "T10", "side": "long", "level": 100.0, "level_members": ["EMA21", "AVWAP SL"], "adr": 5.0,
                      "dv5": 6e8, "confluence": 2, "setup": "pullback long", "theme": "Software"}]}
    (C.LISTS / "today.json").write_text(json.dumps(lst))
    o = open_et(SESSION)
    idx = pd.date_range(o, periods=30, freq="1min", tz=ET)
    # scende sul livello (tocco a 100.2), poi rompe il massimo della barra 5m precedente
    px = np.r_[np.linspace(101.5, 100.2, 18), np.linspace(100.3, 100.9, 12)]
    t10 = pd.DataFrame({"Open": px, "High": px + 0.05, "Low": px - 0.05, "Close": px, "Volume": 1e5}, index=idx)
    qqq = pd.DataFrame({"Open": 400.5, "High": 401, "Low": 400, "Close": 400.5, "Volume": 1e6}, index=idx)
    D.download_intraday = lambda tickers, interval="1m", **k: {"T10": t10, "QQQ": qqq} if interval == "1m" else {}
    now = idx[-1] + timedelta(seconds=30)
    res = A.run_once(dry_run=True, now=now.to_pydatetime())
    ps = [p for p in J.positions() if p["ticker"] == "T10"]
    assert ps, res
    assert ps[0]["trigger_tf"] == "5m" and ps[0]["stop"] < ps[0]["entry"]


def test_chiusura_and_report():
    from jeffcoach import chiusura as CH, report as R
    daily, _, _ = fake_world()
    t10 = daily["T10"].copy()
    t10.index = pd.bdate_range(end=pd.Timestamp(SESSION), periods=len(t10))
    D.download_daily = lambda syms, start, end, **k: {"T10": t10}
    res = CH.run(SESSION)
    assert "equity" in res
    md = R.build("weekly", SESSION + timedelta(days=1))
    assert "Trade veri" in md
    md = R.build("monthly", SESSION + timedelta(days=1))
    assert "Cosa migliorare" in md


if __name__ == "__main__":
    try:
        for fn in (test_metrics_and_candidates, test_daily_build, test_journal_cycle, test_alerts_trigger, test_chiusura_and_report):
            fn()
            print("ok", fn.__name__)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


def test_watchlist_sezioni_e_card_senza_tracking():
    from jeffcoach.output import card_embeds, tv_txt
    txt = tv_txt([("FOCUS LONG", [("PANW", "NMS")]), ("FOCUS SHORT", []),
                  ("TRACKING LONG", [("NOW", "NYQ")]), ("TRACKING SHORT", [("ORCL", "NYQ")])])
    assert txt == "###FOCUS LONG,NASDAQ:PANW,###TRACKING LONG,NYSE:NOW,###TRACKING SHORT,NYSE:ORCL"
    d = {"bias": "LONG", "bias_why": "x", "session": "2026-10-13", "as_of": "2026-10-12", "themes_line": "",
         "focus": [], "tracking_long": ["NOW"], "tracking_short": ["ORCL"], "potent": ["ZZZ"],
         "candidates": [{"ticker": "NOW", "side": "long"}], "near_misses": []}
    desc = "\n".join(e["description"] for e in card_embeds(d))
    assert "NOW" not in desc and "ORCL" not in desc and "ZZZ" not in desc
    assert "Tracking: 1 long · 1 short" in desc


def test_regole_2026_10_14_livello_short_forte():
    lv = [{"name": "EMA9", "price": 100.0}, {"name": "swing low 2026-09-01", "price": 100.3},
          {"name": "EMA50", "price": 104.0}, {"name": "AVWAP swing high 2026-09-10", "price": 104.2}]
    any_cl = E.best_cluster(lv, 99.0)
    strong = E.best_cluster(lv, 99.0, need=E.strong_short_level)
    assert set(any_cl["members"]) == {"EMA9", "swing low 2026-09-01"}
    assert set(strong["members"]) == {"EMA50", "AVWAP swing high 2026-09-10"}
    assert E.strong_short_level("gap") and not E.strong_short_level("EMA21w") and not E.strong_short_level("EMA9")
    assert E.best_cluster([{"name": "EMA9", "price": 100.0}], 99.0, need=E.strong_short_level) is None
    daily, _, _ = fake_world()
    m = E.compute_metrics(daily["T30"], daily["QQQ"])
    ok, info = E.short_candidate("T30", m)
    assert "strong_level" in info["checks"]


def test_regole_2026_10_14_apertura():
    from jeffcoach import alerts as A
    o = open_et(SESSION)
    idx = pd.date_range(o, periods=5, freq="1min", tz=ET)
    stretta = pd.DataFrame({"Open": 100.0, "High": 100.5, "Low": 99.8, "Close": 100.2, "Volume": 1e5}, index=idx)
    ampia = stretta.assign(High=102.0, Low=99.0)
    assert A.early_reason("short", 5, stretta, 0.0, 110.0, 4.0)           # primi 15 minuti: apertura lontana dal livello
    assert A.early_reason("short", 5, stretta, 0.0, 101.0, 4.0) is None   # apertura già sulla resistenza [17/10d]
    assert A.early_reason("long", 5, stretta, 0.0, 99.5, 4.0) is None     # gap down sul supporto, prima candela stretta
    assert A.early_reason("long", 5, ampia, 0.0, 99.5, 4.0)               # ... ma non con la prima candela ampia
    assert A.early_reason("long", 11, ampia, 0.0, 90.0, 4.0) is None      # dopo 10 minuti: trigger normale
    assert A.early_reason("long", 20, ampia, 1.0)                        # QQQ in gap up: long dopo 30 minuti
    assert A.early_reason("short", 20, ampia, -1.0)                      # QQQ in gap down: short dopo 30 minuti
    assert A.early_reason("short", 31, ampia, -1.0) is None              # ... poi trigger normale
    assert A.early_reason("long", C.INDEX_GAP_UP_LONG_WAIT_MIN + 1, ampia, 1.0) is None


def test_regole_2026_10_14_short_senza_uscita_a_tempo():
    import json
    from jeffcoach import chiusura as CH
    from jeffcoach.calendar_us import last_sessions
    opened = last_sessions(SESSION, 5)[0]
    ctx = dict(ticker="TSH", side="short", setup="pullback short", dv5=6e8, adr=4.0, level=50.0)
    J.open_trade(ctx, 50.0, 51.0, None, opened, 20)
    idx = pd.bdate_range(end=pd.Timestamp(SESSION), periods=150)
    df = pd.DataFrame({"Open": 48.0, "High": 48.4, "Low": 47.6, "Close": 48.0, "Volume": 1e7}, index=idx)
    D.download_daily = lambda syms, start, end, **k: {"TSH": df}
    C.LISTS.mkdir(parents=True, exist_ok=True)
    old, C.MGMT_MODE = C.MGMT_MODE, "classic"          # regola della gestione classica (fino alla 17f)
    try:
        for bias, aperta in (("SHORT", True), ("MISTO", False)):
            (C.LISTS / f"{SESSION}.json").write_text(json.dumps({"session_date": SESSION.isoformat(), "bias": bias}))
            CH.run(SESSION)
            still = any(p["ticker"] == "TSH" for p in J.positions())
            assert still == aperta, (bias, still)
    finally:
        C.MGMT_MODE = old


def test_regole_2026_10_14b_tipi_short(monkeypatch):
    monkeypatch.setattr(C, "SHORT_EARLY_DOWNTREND", True)    # setup spenti dal 20/10a: qui si prova la regola
    monkeypatch.setattr(C, "SHORT_EXLEADER", True)
    base = dict(list="Mediocre", e9=99.0, e9_prev=100.0, e21=100.0, e21_slope=-1.0, e50=100.5, e50_slope=0.1,
                close=97.0, adr=5.0, dv5=6e8, vol10=2e6, w_close=102.0, ew9=105.0, ew21=100.0, close_pos=0.3, ret1_adr=-0.5,
                up_52w_low=40.0, rs5=-2.0,
                resistances=[{"name": "EMA21", "price": 100.0}, {"name": "EMA9", "price": 99.0}, {"name": "gap", "price": 99.5}])
    ok, info = E.short_candidate("TG", dict(base))                      # trend che gira: weekly sano ammesso
    assert ok and info["short_type"] == "trend che gira", info
    exl = dict(base, e9=99.0, e21=97.5, e21_slope=1.0, e50=97.8, up_52w_low=400.0,   # sotto la 50 daily [17i]
               resistances=[{"name": "EMA9", "price": 99.0}, {"name": "AVWAP swing high 2026-09-22", "price": 101.5}])
    ok, info = E.short_candidate("EX", exl)                              # ex-leader: sotto la 9 e la 21 daily [16/10n]
    assert ok and info["short_type"] == "top ex-leader", info
    ok, info = E.short_candidate("NO", dict(exl, up_52w_low=40.0))       # senza grande corsa: niente
    assert not ok


def test_regole_2026_10_14e_niente_alert_lontano_dal_livello():
    """Tocco della resistenza in apertura e poi -4%: niente alert né ingresso (caso COIN 14/10)."""
    from jeffcoach import alerts as A
    import json
    lst = {"session_date": SESSION.isoformat(), "bias": "SHORT", "qqq_prev_close": 400.0, "indices": {}, "breadth": {},
           "focus": [{"ticker": "TC", "side": "short", "level": 100.0, "level_members": ["EMA21", "EMA9"], "adr": 5.0,
                      "dv5": 6e8, "confluence": 2, "setup": "pullback short", "theme": "Crypto"}]}
    (C.LISTS / "today.json").write_text(json.dumps(lst))
    o = open_et(SESSION)
    idx = pd.date_range(o, periods=120, freq="1min", tz=ET)
    px = np.r_[np.linspace(99.0, 100.3, 10), np.linspace(100.2, 95.5, 110)]
    tc = pd.DataFrame({"Open": px + 0.05, "High": px + 0.1, "Low": px - 0.1, "Close": px, "Volume": 1e5}, index=idx)
    qqq = pd.DataFrame({"Open": 400.0, "High": 401, "Low": 399, "Close": 400.0, "Volume": 1e6}, index=idx)
    D.download_intraday = lambda tickers, **k: {"TC": tc, "QQQ": qqq}
    res = A.run_once(dry_run=True, now=(idx[-1] + timedelta(seconds=30)).to_pydatetime())
    assert not res["sent"], res
    assert not [p for p in J.positions() if p["ticker"] == "TC"]


def test_regole_2026_10_14f_avvicinamento():
    from jeffcoach import alerts as A
    import json
    lst = {"session_date": SESSION.isoformat(), "bias": "LONG", "qqq_prev_close": 400.0, "indices": {}, "breadth": {},
           "focus": [{"ticker": "TS", "side": "short", "level": 100.0, "level_members": ["EMA21"], "adr": 5.0, "dv5": 6e8,
                      "confluence": 2, "setup": "pullback short", "theme": "Crypto"},
                     {"ticker": "TL", "side": "long", "level": 50.0, "level_members": ["EMA21"], "adr": 5.0, "dv5": 6e8,
                      "confluence": 2, "setup": "pullback long", "theme": "Software", "breakout_level": 55.0}]}
    (C.LISTS / "today.json").write_text(json.dumps(lst))
    o = open_et(SESSION)
    idx = pd.date_range(o, periods=40, freq="1min", tz=ET)
    ts = pd.DataFrame({"Open": 98.9, "High": 99.0, "Low": 98.8, "Close": 98.9, "Volume": 1e5}, index=idx)
    tl = pd.DataFrame({"Open": 54.5, "High": 54.6, "Low": 54.4, "Close": 54.5, "Volume": 1e5}, index=idx)
    qqq = pd.DataFrame({"Open": 400.0, "High": 401, "Low": 399, "Close": 400.0, "Volume": 1e6}, index=idx)
    D.download_intraday = lambda tickers, **k: {"TS": ts, "TL": tl, "QQQ": qqq}
    res = A.run_once(dry_run=True, now=(idx[-1] + timedelta(seconds=30)).to_pydatetime())
    assert "TS · Approaching resistance" in res["sent"] and not any("breakout" in x for x in res["sent"]), res


def test_regole_2026_10_16_classifica_temi_basket():
    """Temi in classifica come i basket di Ratatouille: media del Final_Score a 7 fattori dei titoli [RONIN 16/10]."""
    from jeffcoach import basket_score as BS, themes as T
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2026-01-02", periods=160)

    def mk(drift):
        c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, len(idx))))
        o = c * (1 - drift * 5)
        return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99,
                             "Close": c, "Volume": 1e6}, index=idx)
    daily = {f"U{i}": mk(0.004) for i in range(5)}
    daily.update({f"D{i}": mk(-0.004) for i in range(5)})
    daily["SPY"] = mk(0.0005)
    sc = BS.universe_scores(daily, [s for s in daily if s != "SPY"], daily["SPY"])
    assert sc.loc[[f"U{i}" for i in range(5)], "Final_Score"].mean() > sc.loc[[f"D{i}" for i in range(5)], "Final_Score"].mean()
    metrics = {s: dict(list="Leading", close=1, e21=1, e9=1, rs21=0, dv20=1, dv60=1, ret21=0, ext50=0) for s in daily}
    closes = pd.DataFrame({s: daily[s].Close for s in daily})
    rows = T.score_groups({"Su": [f"U{i}" for i in range(5)], "Giu": [f"D{i}" for i in range(5)]}, metrics, closes,
                          daily["SPY"].Close, {}, min_members=1, bscores=sc)
    assert [r["theme"] for r in rows] == ["Su", "Giu"] and "Short_Score" not in sc.columns
    assert rows[0]["top_pick"].startswith("U") and abs(rows[0]["score"] - sc.loc[rows[0]["members"], "Final_Score"].mean()) < 1e-9
    # tema misurato sui suoi ETF [RONIN 16/10]: punteggio = Final_Score dell'ETF, i titoli restano membri
    esc = BS.universe_scores(daily, ["U0", "D0"], daily["SPY"])
    rows = T.score_groups({"Su": ["D1", "D2"], "Giu": ["U1"]}, metrics, closes, daily["SPY"].Close, {}, bscores=esc,
                          etfs={"Su": ["U0"], "Giu": ["D0"], "Senza dati": ["XXX"]})
    assert [r["theme"] for r in rows] == ["Su", "Giu"] and rows[0]["etfs"] == ["U0"] and rows[0]["members"] == ["D1", "D2"]
    assert abs(rows[0]["score"] - esc.loc["U0", "Final_Score"]) < 1e-9


def test_regole_2026_10_16e_appartenenza_sovrappeso():
    """Un titolo resta in un tema solo se l'ETF lo sovrappesa rispetto al mercato [RONIN 16/10]."""
    from jeffcoach import themes_map as TM
    groups = {"CIBR": "Cybersecurity", "SMH": "Semiconductors", "IGV": "Software", "MTUM": "Momentum", "WGMI": "Bitcoin"}
    hold = {"CIBR": [{"symbol": "MSFT", "weight": 0.03}, {"symbol": "CRWD", "weight": 0.08}],
            "SMH": [{"symbol": "NVDA", "weight": 0.20}], "IGV": [{"symbol": "MSFT", "weight": 0.08}, {"symbol": "CRWD", "weight": 0.06}],
            "MTUM": [{"symbol": "MSFT", "weight": 0.01}], "WGMI": [{"symbol": "NVDA", "weight": 0.02}, {"symbol": "IREN", "weight": 0.10}]}
    mcap = {"MSFT": 4e12, "NVDA": 5e12, "CRWD": 1e11, "IREN": 1e10, "ALTRO": 9.089e13}      # totale 100.000 mld
    t = TM.build_map(groups, hold, None, mcap)["tickers"]
    assert t["NVDA"]["themes"] == ["Semiconductors"]                       # 2% in WGMI contro 5% di mercato: fuori
    assert t["MSFT"]["themes"] == ["Momentum", "Software"] and t["MSFT"]["primary"] == "Software"   # ripiego + generico
    assert t["CRWD"]["themes"] == ["Cybersecurity", "Software"] and t["IREN"]["themes"] == ["Bitcoin"]
    assert TM.build_map(groups, hold)["tickers"]["NVDA"]["themes"] == ["Bitcoin", "Semiconductors"]     # senza mcap: come prima


def test_regole_2026_10_16_market_monitor_pradeep():
    """Market Monitor letto come Pradeep Bonde [RONIN 16/10]: T2108 < 20 rialzista, T30A, studio 20% > 100 = selettivo,
    25% nel trimestre + acquisti/vendite."""
    from jeffcoach import engine as E

    def rows(**over):
        base = [dict(date=f"2026-09-{30 - k:02d}" if k < 29 else f"2026-08-{60 - k:02d}", up4=250, down4=150,
                     up25q=1500, down25q=1000, t2108=50 - k * 0.3, up20w=40, ratio5=1.2, ratio10=1.2) for k in range(40)]
        for k, d in over.items():
            for i, v in d.items():
                base[i][k] = v
        return base
    r = rows()
    assert E.market_monitor(r, r[0]["date"])["label"] == "Breakouts work"            # 25%Q verde, acquisti
    r = rows(up20w={3: 150})
    assert E.market_monitor(r, r[0]["date"])["label"] == "Breakouts work"            # sotto 200: nessun avviso
    r = rows(up20w={3: 250})
    m = E.market_monitor(r, r[0]["date"])
    assert m["label"] == "Be selective" and any("dip likely" in w for w in m["mm_why"])  # studio 20% >= 200
    r = rows(up20w={3: 250}, t2108={20: 15})
    assert E.market_monitor(r, r[0]["date"])["label"] == "Breakouts work"            # T30A: uscita da ipervenduto
    r = rows(up4={i: 100 for i in range(5)}, down4={i: 400 for i in range(5)}, up25q={0: 800},
             t2108={0: 30, 5: 40})
    assert E.market_monitor(r, r[0]["date"])["label"] == "Breakouts fail"
    for i in range(40):
        r[i]["down20w"] = 250 if i == 2 else 30
    m = E.market_monitor(r, r[0]["date"])
    assert m["label"] == "Be selective" and any("bounce likely" in w for w in m["mm_why"])   # -20% >= 200
    r = rows(t2108={0: 15})
    assert "start getting bullish" in " ".join(E.market_monitor(r, r[0]["date"])["mm_why"])


def test_regole_2026_10_16_card_regime_grafico():
    """In cima alla card: tabella ±4% a 20 giorni e grafico studio 20% (+/-, stesso filtro) e T2108 [RONIN 16/10]."""
    from jeffcoach import breadth_chart as BC
    own = [dict(date=f"2026-09-{d:02d}", up4=100 + d, down4=200 - d, t2108=30 + d, up20w=d * 5, down20w=d) for d in range(1, 31)]
    sb = [dict(date="2026-09-30", up4=489, down4=139, t2108=25)]
    h = BC.mm_history(sb, own, "2026-09-30")
    assert h[-1]["up4"] == 489 and h[-1]["up20w"] == 150 and h[-1]["source"] == "Stockbee"
    tb = BC.table_20d(h)
    assert tb.startswith("```") and "30/09  489  139▲" in tb and tb.count("\n") == 12
    png = BC.render(h, 200, 200)
    assert png and png[:4] == b"\x89PNG"


def test_regole_2026_10_16f_stadi_temi():
    """Stadi di Ratatouille (punteggio e variazione a 5 sedute) [RONIN 16/10]."""
    from jeffcoach import themes as T
    assert T.stage(75, 1) == "LEADING" and T.stage(75, -1) == "FADING"
    assert T.stage(60, 3) == "BUILDING" and T.stage(60, -4) == "SLIPPING" and T.stage(60, 0) == "HOLDING"
    assert T.stage(45, 4) == "RECOVERY" and T.stage(45, 0) == "WEAK" and T.stage(30, 0) == "BEARISH"
    assert set(C.STAGE_LONG) == {"LEADING", "BUILDING"} and set(C.STAGE_SHORT) == {"FADING", "SLIPPING", "WEAK"}


def test_regole_2026_10_16g_potential_trend_reversal():
    """Primo giorno ▲ dopo una fase di vendite ±4% (e il successivo): potential trend reversal [RONIN 16/10]."""
    from jeffcoach import engine as E
    mk = lambda pairs: [dict(date=f"2026-10-{i + 1:02d}", up4=u, down4=d) for i, (u, d) in enumerate(pairs)]
    h = mk([(100, 200), (200, 100), (100, 300), (100, 400), (80, 700), (480, 140)])
    r = E.flow_reversal(h)
    assert r and r["direction"] == "buying" and r["day"] == 1
    assert E.flow_reversal(h + mk([(1, 1)] * 7)[-1:])["day"] == 2          # vale anche la seduta dopo
    assert E.flow_reversal(h + mk([(300, 100)] * 2)) is None                # dal terzo giorno no


def test_regole_2026_10_16k_linearita_ed_estensione():
    """Trend poco lineari (WRBY) e titoli troppo estesi dalla EMA9 (LITE) fuori dai candidati [RONIN 16/10]."""
    from jeffcoach import engine as E
    up = pd.Series(np.exp(np.linspace(0, 0.5, 130)))
    chop = pd.Series(100 + np.tile([0, 5, -5, 3, -3], 26).astype(float))
    assert E.trend_r2(up) > 0.95 and E.trend_r2(chop) < C.MIN_TREND_R2
    lite = dict(adr=6.6, ext9=-11.3)
    assert E.stretched(lite, "short") and not E.stretched(lite, "long")
    assert not E.stretched(dict(adr=5.0, ext9=-2.0), "short") and E.stretched(dict(adr=4.0, ext9=6.5), "long")


def test_regole_2026_10_16n_ex_leader_sotto_la_21(monkeypatch):
    monkeypatch.setattr(C, "SHORT_EARLY_DOWNTREND", True)    # setup spenti dal 20/10a: qui si prova la regola
    monkeypatch.setattr(C, "SHORT_EXLEADER", True)
    """Ex-leader solo dopo la chiusura sotto la EMA21 daily (SNDK: non il 2/10, sì dal 6/10) [RONIN 16/10]."""
    base = dict(list="Leading", e9=99.0, e9_prev=100.0, e21=97.5, e21_slope=1.0, e50=90.0, e50_slope=0.5,
                close=97.0, adr=5.0, dv5=6e8, w_close=110.0, ew9=105.0, ew21=100.0, close_pos=0.3, ret1_adr=-0.5,
                up_52w_low=400.0, rs5=-2.0, resistances=[{"name": "EMA9", "price": 99.0},
                                                          {"name": "AVWAP swing high 2026-09-22", "price": 101.5}])
    assert E.short_candidate("EX", base)[1]["short_type"] == "top ex-leader"
    assert E.short_candidate("EX", dict(base, close=98.0))[1].get("short_type") is None      # ancora sopra la 21


def test_regole_2026_10_17b_weekly_ema9():
    old_tf, C.TREND_TF = C.TREND_TF, "weekly_ema9"
    """Consonanza weekly: short solo sotto la EMA9 weekly, long solo sopra [RONIN 17/10]."""
    base = dict(list="Mediocre", e9=99.0, e9_prev=100.0, e21=100.0, e21_slope=-1.0, e50=100.5, e50_slope=0.1,
                close=97.0, adr=5.0, dv5=6e8, w_close=102.0, ew9=105.0, ew9_slope=-0.5, ew21=100.0, close_pos=0.3,
                ret1_adr=-0.5, up_52w_low=40.0, rs5=-2.0,
                resistances=[{"name": "EMA21", "price": 100.0}, {"name": "EMA9", "price": 99.0}, {"name": "gap", "price": 99.5}])
    assert E.short_candidate("W", base)[1]["checks"]["trend_tf"]
    assert not E.short_candidate("W", dict(base, w_close=106.0, ew9_slope=0.5))[1]["checks"]["trend_tf"]
    assert E.short_candidate("W", dict(base, w_close=106.0, ew9_slope=-0.5))[1]["checks"]["trend_tf"]   # 9 in discesa
    assert not E.short_candidate("W", dict(base, w_close=110.0, ew9_slope=-0.5))[1]["checks"]["trend_tf"]
    C.TREND_TF = old_tf


def test_regole_2026_10_17g_gestione_estensioni_e_ema50_oraria():
    """Parziali nelle estensioni dalla EMA9 daily e trailing sulla EMA50 oraria solo dopo +1R."""
    from jeffcoach import alerts as A
    assert C.MGMT_MODE == "ext_h50"
    ET_ = A.ET
    t0 = pd.Timestamp(f"{SESSION} 10:00", tz=ET_)
    # short: entry 100, stop 101 (1R = 1), EMA9 daily 101, ATR 2 -> parziali a 98 (-1.5 ATR) e 96 (-2.5 ATR)
    ctx = dict(ticker="XS", side="short", setup="pullback short", dv5=6e8, adr=4.0, level=100.0, e9d=101.0, atr_d=2.0)
    p = J.open_trade(ctx, 100.0, 101.0, None, SESSION, 30)
    p["time_open_rome"] = t0.tz_convert("Europe/Rome").isoformat()
    idx = pd.date_range(t0, periods=3, freq="1min")
    b = pd.DataFrame({"Open": [100, 99, 97.5], "High": [100.2, 99.2, 97.8], "Low": [99.5, 97.9, 97.0],
                      "Close": [99.6, 98.2, 97.2], "Volume": 1e5}, index=idx)
    # barre orarie: tutte sotto la EMA50 tranne l'ultima chiusa, che chiude sopra
    hidx = pd.date_range(t0 - pd.Timedelta(hours=80), periods=80, freq="60min")
    h = pd.DataFrame({"Open": 100.0, "High": 100.5, "Low": 99.5, "Close": 100.0, "Volume": 1e6}, index=hidx)
    old = A.hourly_bars
    A.hourly_bars = lambda t: {"XS": h}
    try:
        A.manage_positions([p], {"XS": b}, SESSION, dry_run=True)
    finally:
        A.hourly_bars = old
    kinds = [(e["kind"], e["reason"]) for e in p["exits"]]
    assert ("trim", "parziale -1.5 ATR dalla EMA9 daily") in kinds, kinds
    assert not any("2.5" in r for _, r in kinds)
    assert p["trail_on"] is True                       # +1R toccato (minimo 97.9 < 99)
    assert p["shares_open"] > 0 or any(k == "exit" for k, _ in kinds)
    # long senza +1R: la EMA50 oraria non lo fa uscire (vale lo stop iniziale)
    ctx = dict(ticker="XL", side="long", setup="pullback long", dv5=6e8, adr=4.0, level=100.0, e9d=99.0, atr_d=2.0)
    q = J.open_trade(ctx, 100.0, 99.0, None, SESSION, 30)
    q["time_open_rome"] = (t0 - pd.Timedelta(minutes=30)).tz_convert("Europe/Rome").isoformat()   # l'ultima oraria chiusa è dopo l'ingresso
    bl = pd.DataFrame({"Open": 100.0, "High": 100.4, "Low": 99.6, "Close": 100.1, "Volume": 1e5}, index=idx)
    hl = h.assign(Close=[110.0] * 79 + [100.0])        # ultima oraria sotto la EMA50
    A.hourly_bars = lambda t: {"XL": hl}
    try:
        A.manage_positions([q], {"XL": bl}, SESSION, dry_run=True)
        assert q["shares_open"] == q["shares"] and not q["trail_on"]
        q["trail_on"] = True                           # dopo +1R la stessa barra oraria lo fa uscire
        q["seen_ts"] = None
        A.manage_positions([q], {"XL": bl}, SESSION, dry_run=True)
        assert q["shares_open"] == 0 and "EMA50 oraria" in q["exits"][-1]["reason"]
    finally:
        A.hourly_bars = old


def test_regole_2026_10_17i_ema50_daily_al_posto_della_9_weekly():
    m = dict(close=97.0, e50=100.0, e50_slope=-0.5, adr=4.0)
    assert E.trend_tf_ok(m, "short") and not E.trend_tf_ok(m, "long")
    assert E.trend_tf_ok(dict(m, close=101.5), "short")                  # appena sopra, 50 in discesa: ammesso
    assert not E.trend_tf_ok(dict(m, close=101.5, e50_slope=0.5), "short")  # appena sopra, 50 in salita: no
    assert not E.trend_tf_ok(dict(m, close=103.0), "short")              # oltre 0,5 ADR: no
    assert E.weekly_align(m, "short") == 1 and E.weekly_align(dict(m, close=103.0, e50_slope=0.5), "short") == -1


def test_regole_2026_10_17m_flusso_tra_le_liste():
    """Leading→Mediocre e Mediocre→Lagging -1, Leading→Lagging -2, il contrario +; netto a 5 sedute e tendenza."""
    old = {f"T{i}": "Leading" for i in range(40)} | {f"U{i}": "Mediocre" for i in range(20)} | {f"V{i}": "Lagging" for i in range(40)}
    new = dict(old) | {f"T{i}": "Mediocre" for i in range(6)} | {f"T{i}": "Lagging" for i in range(6, 8)} \
        | {f"U{i}": "Lagging" for i in range(3)} | {"V0": "Mediocre"}
    f = E.list_flow(old, new)
    assert f["net"] == -6 - 4 - 3 + 1 and f["two"] == 2 and f["up"] == 1 and f["down"] == 11
    # 4 giorni di vendite tra le liste: flusso -12% e tendenza in discesa, con feedback long negativo = SHORT
    days = [old]
    cur = dict(old)
    for k in range(4):
        cur = dict(cur) | {f"T{i}": "Mediocre" for i in range(k * 3, k * 3 + 3)}
        days.append(cur)
    mb = E.martin_breadth({}, {}, days[-1], days[0], [], {}, days[:-1])
    assert mb["flow5"]["pct"] == -12.0 and len(mb["flow_daily"]) == 4
    fb = {"long": dict(n=10, hit1r=1, fast_stop=8, sum_r=-8.0)}
    r = E.regime_martin(dict(mb, lead_above9_pct=None, leaders_n=0, mega_n=0), fb)
    assert r["bias"] == "SHORT" and any("flow trend down" in w for w in r["why"]), r
    up = E.martin_breadth({}, {}, days[0], days[-1], [], {}, list(reversed(days))[:-1])
    assert E.regime_martin(dict(up, lead_above9_pct=None, leaders_n=0, mega_n=0), {})["score"] >= 3


def test_regole_2026_10_17o_pool_di_martin():
    """Pool di Martin: 130 titoli; bias dal flusso del pool (Leading → Mediocre = -1) e dal feedback."""
    import numpy as np
    from jeffcoach import pool as PL
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2025-01-01", periods=420)
    daily = {}
    for i in range(220):
        r = rng.normal(0.0005 * (i % 7 - 3), 0.02 + 0.0002 * i, len(idx))
        c = 50 * np.exp(np.cumsum(r))
        daily[f"S{i}"] = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.98, "Close": c,
                                       "Volume": 2e6 * (1 + i % 11)}, index=idx)
    pb = PL.pool_breadth(daily, list(daily), idx)
    assert sum(pb["lists"].values()) == pb["n"] and len(pb["flow_daily"]) >= 4
    crash = dict(n=130, lists={"Leading": 28, "Mediocre": 66, "Lagging": 36}, share=43.8, flow5=-36.2,
                 flow_daily=[-3.8, -13.1, 2.3, -12.3], up_5d=6, down_5d=53)
    r = E.regime_pool(crash, {})
    assert r["bias"] == "SHORT" and r["score"] == -4, r                # livello -1, flusso -2, tendenza -1
    calm = dict(crash, share=72.0, flow5=4.0, flow_daily=[0.5, -0.4, 1.2, 0.3])
    assert E.regime_pool(calm, {})["bias"] == "MISTO"
    fb = {"long": dict(n=10, hit1r=6, fast_stop=2, sum_r=8.0)}
    assert E.regime_pool(calm, fb)["bias"] == "MISTO"                  # peso del feedback 0 dal 19/10a: solo contesto
    old, C.POOL_FB_WEIGHT = C.POOL_FB_WEIGHT, 2
    try:
        assert E.regime_pool(calm, fb)["bias"] == "LONG"
    finally:
        C.POOL_FB_WEIGHT = old


def test_regole_2026_10_19b_long_specchio_degli_short():
    """Long: chiusura sopra la EMA9 daily e weekly sano, come gli short sotto la 9 e con weekly non sano."""
    m = dict(list="Leading", dv5=6e8, close=124.0, adr=5.0, e9=139.9, e21=133.4, e21_slope=4.4, e50=117.7, e50_slope=5.3,
             ext9=-11.0, ext50_atr=1.0, trend_r2=0.8, w_close=124.0, ew9=126.0, ew9_slope=1.1, ew21=118.0,
             supports=[{"name": "EMA50", "price": 117.7}, {"name": "AVWAP swing low", "price": 118.5}])
    ok, info = E.long_candidate("P", m)
    assert not info["checks"]["above_ema9"] and info["checks"]["weekly_healthy"]   # caso P del 19/10: sotto 9 e 21
    ok, info = E.long_candidate("P", dict(m, close=141.0, w_close=141.0, ew21=150.0))
    assert info["checks"]["above_ema9"] and not info["checks"]["weekly_healthy"]


def test_regole_2026_10_20b_corsa_di_piu_giorni_e_sma50():
    """Niente long/short dopo 4+ sedute di fila nel verso del trade con 2+ ADR di movimento, salvo base; long entro 5 ATR."""
    m = dict(streak_up=4, streak_dn=0, streak_move_adr=2.5, range15_adr=5.0)
    assert E.streak_run(m, "long") and not E.streak_run(m, "short")
    assert not E.streak_run(dict(m, range15_adr=2.5), "long")          # ancora in una base: va bene
    assert not E.streak_run(dict(m, streak_move_adr=1.0), "long")      # movimento piccolo: va bene
    import numpy as np
    idx = pd.bdate_range("2025-01-01", periods=300)
    c = pd.Series(np.linspace(50, 80, 300), index=idx)
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e7})
    q = df.copy()
    mm = E.compute_metrics(df, q)
    assert mm["streak_up"] >= 4 and mm["streak_dn"] == 0
    assert C.CONFLUENCE_MIN == 3 and C.LONG_MAX_EXT_SMA50_ATR == 5.0



def test_regole_2026_10_20c_qqq_conferma_e_volume(monkeypatch):
    monkeypatch.setattr(C, "QQQ_GATE_LEVEL", True)     # parte "livello" spenta dal 20/10e: qui si prova la regola
    """Ingresso long solo con QQQ consonante e su un supporto; volume medio 10g >= 500k azioni."""
    from jeffcoach import alerts as A
    idx = pd.date_range("2026-10-20 09:30", periods=30, freq="1min", tz="America/New_York")
    qb = pd.DataFrame({"Open": 600.0, "High": 601.0, "Low": 599.2, "Close": 600.5, "Volume": 1e5}, index=idx)
    ctx = dict(adr=1.2, tf_long=True, tf_short=False, supports=[599.0], resistances=[620.0])
    assert A.qqq_gate("long", ctx, qb, None) is None                      # ha toccato 599 (entro 0,25 ADR) ed è vicino
    assert A.qqq_gate("short", ctx, qb, None).startswith("QQQ not at")
    assert A.qqq_gate("long", dict(ctx, supports=[590.0]), qb, None).startswith("QQQ not at")
    import numpy as np                                                    # trend a 60m: onda che sale (HH/HL)
    hi = pd.date_range("2026-10-01 09:30", periods=120, freq="60min", tz="America/New_York")
    base = 580 + np.arange(120) * 0.2 + 3 * np.sin(np.arange(120) / 3)
    qh = pd.DataFrame({"Open": base, "High": base + 0.5, "Low": base - 0.5, "Close": base, "Volume": 1e6}, index=hi)
    assert A.trend_60m(qh, float(base[-1]) + 1, "long") is True and A.trend_60m(qh, float(base[-1]), "short") is False
    # struttura degli swing: con QQQ_TREND_SWINGS i long vogliono anche massimi e minimi crescenti [20/10g]
    dip = base.copy(); dip[-10:] -= 8                       # ultimo tratto in ritracciamento: swing contrari al long
    qd = pd.DataFrame({"Open": dip, "High": dip + 0.5, "Low": dip - 0.5, "Close": dip, "Volume": 1e6}, index=hi)
    px = float(dip[-1])
    monkeypatch.setattr(C, "QQQ_TREND_SWINGS", True)
    assert A.trend_60m(qd, px, "long") is False             # prima del 20/10g: ritracciamento = niente long
    monkeypatch.setattr(C, "QQQ_TREND_SWINGS", False)       # ora decidono solo media e pendenza [20/10g]
    assert A.trend_60m(qd, px, "long") is True
    m = dict(list="Leading", dv5=6e8, vol10=3e5, close=50.0, adr=5.0)
    assert not E.long_candidate("X", dict(m, e9=49, e21=48, e21_slope=1, e50=45, e50_slope=1, ext9=2, ext50_atr=1,
                                           trend_r2=0.8, w_close=50, ew9=48, ew9_slope=1, ew21=45, supports=[]))[1]["checks"]["liquid"]


def test_regole_2026_10_20h_banda_ingresso(monkeypatch):
    """Banda d'ingresso [20/10h, Andrea]: si entra un po' prima del livello, mai sul livello o oltre."""
    assert C.ENTRY_BAND and C.ENTRY_DIST_MIN_PCT == 0.05 and C.ENTRY_DIST_MAX_PCT == 1.0
    lvl = 100.0
    def dist(price, side):
        return (lvl / price - 1) * 100 * (1 if side == "short" else -1)
    inb = lambda d: C.ENTRY_DIST_MIN_PCT <= d <= C.ENTRY_DIST_MAX_PCT
    assert inb(dist(99.5, "short")) and inb(dist(99.1, "short"))      # short sotto la resistenza: in banda
    assert not inb(dist(100.0, "short"))                              # sul livello: fuori
    assert not inb(dist(100.5, "short"))                              # oltre il livello: fuori
    assert not inb(dist(98.0, "short"))                               # troppo lontano: si aspetta
    assert inb(dist(100.5, "long")) and inb(dist(100.9, "long"))      # long sopra il supporto: in banda
    assert not inb(dist(100.0, "long")) and not inb(dist(99.5, "long")) and not inb(dist(102.0, "long"))


def _channel(n: int = 160, slope: float = 0.004, width: float = 0.06, period: int = 20, price: float = 50.0) -> pd.DataFrame:
    """Canale perfetto in scala log: minimi sulla linea di fondo, massimi sulla parallela (slope < 0 = canale ribassista)."""
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    t = np.arange(n)
    b = np.log(price) + slope * t
    osc = (1 - np.cos(2 * np.pi * t / period)) / 2
    lo, hi, cl = (np.exp(b + width * x) for x in (0.8 * osc, 0.2 + 0.8 * osc, 0.1 + 0.8 * osc))
    op = np.roll(cl, 1)
    op[0] = cl[0]
    op = np.clip(op, lo, hi)
    return pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": cl, "Volume": np.full(n, 2e6)}, index=idx)


def test_regole_2026_10_22b_trendline_e_canali(monkeypatch):
    """Trendline e canali paralleli sul daily [RONIN 22/10, Andrea: "in maniera corretta e coerente"]: la linea passa per
    gli swing, nessuna chiusura dall'altra parte, canale solo se la parallela tocca almeno 2 swing; una chiusura sotto la
    linea la invalida; il grafico degli alert disegna le stesse linee in scala log."""
    from jeffcoach import trendlines as TL
    import math
    df = _channel()
    adr = float(((df.High / df.Low - 1) * 100).iloc[-20:].mean())
    up = TL.find_lines(df, adr)["up"]
    assert up and up["touches"] >= 4 and up["slope_pct_day"] > 0
    assert abs(up["slope_pct_day"] - (math.exp(0.004) - 1) * 100) < 0.02          # inclinazione del canale vero
    assert up["value"] <= float(df.Close.iloc[-1])
    ch = up["channel"]
    assert ch and ch["touches"] >= 4 and 4.0 < ch["width_pct"] < (math.exp(0.06) - 1) * 100   # dentro il canale vero
    assert all(float(df.High.iloc[p]) <= TL.value_at(up, p, channel=True) * 1.001 for p in range(up["i0"], len(df)))
    assert 0 <= ch["position"] <= 1
    assert abs(TL.value_at(up, len(df) - 1) - up["value"]) < 1e-6
    dn = TL.find_lines(_channel(slope=-0.004), adr)["down"]                      # specchio: canale ribassista
    assert dn and dn["touches"] >= 4 and dn["slope_pct_day"] < 0 and dn["channel"]
    assert dn["value"] >= float(_channel(slope=-0.004).Close.iloc[-1])
    # chiusure sotto la linea: quella linea non vale più (se ne resta una, sta sotto il prezzo)
    br = df.copy()
    br.iloc[-4:, br.columns.get_loc("Close")] = br.Close.iloc[-5] * 0.85
    br.iloc[-4:, br.columns.get_loc("Low")] = br.Close.iloc[-5] * 0.84
    br.iloc[-4:, br.columns.get_loc("Open")] = br.Close.iloc[-5] * 0.86
    up2 = TL.find_lines(br, adr)["up"]
    assert up2 is None or up2["i0"] != up["i0"] or up2["value"] <= float(br.Close.iloc[-1]) * (1 + C.TL_TOL_ADR * adr / 100)
    from jeffcoach import chart as CH
    for tl_chart in (False, True):                          # Dua: grafico di prima; multi-edge: log con trendline
        monkeypatch.setattr(C, "TL_CHART", tl_chart)
        png = CH.alert_chart("TST", "long", None, 5, SESSION, level=float(up["value"]), title="test", daily=df)
        assert png and png[:4] == b"\x89PNG"


def test_regole_2026_10_22b_multi_edge(monkeypatch):
    """Multi-edge [RONIN 22/10, Andrea; J Law METS]: cinque edge per candidato, livelli pesati per timeframe, test del
    livello, MTF weekly+daily, RS a 1 settimana-1 mese con rotazione del gruppo; tutto serializzabile. Dua (regole di
    Martin) non li calcola: le metriche restano quelle di prima."""
    import json as _j
    from jeffcoach import edges as EDG
    daily, _, _ = fake_world()
    assert not C.META_EDGES and not C.META_RANK and not C.TL_CHART                  # Dua com'era
    m0 = E.compute_metrics(daily["T01"], daily["QQQ"])
    assert not {"edge_feat", "levels_x", "tl", "recent"} & set(m0)
    monkeypatch.setattr(C, "META_EDGES", True)
    m = E.compute_metrics(daily["T01"], daily["QQQ"])
    assert {"edge_feat", "levels_x", "tl", "recent"} <= set(m)
    assert all(x.get("lo", x["price"]) < m["close"] for x in m["levels_x"]["long"])     # aree: dal bordo
    assert all(x.get("hi", x["price"]) > m["close"] for x in m["levels_x"]["short"])
    row = {"side": "long", "level": m["close"] * 0.98, "tf_h": 1}
    ev = EDG.evaluate(row, m, "Improving", [{"name": "EMA50h", "price": m["close"] * 0.98}])
    assert 0 <= ev["n_edges"] <= 5 and set(ev["edges"]) <= set(EDG.EDGE_KEYS) and ev["n_edges"] == len(ev["edges"])
    _j.dumps(ev)
    assert "EMA50h" in ev["edge_detail"]["SR"]["why"]["levels"]
    # timeframe e pesi dei livelli [Andrea: più importanza a daily e weekly]
    assert [EDG.level_tf(x) for x in ("EMA21w", "weekly low 2026-09-18", "EMA50w", "EMA50h", "EMA150", "TL up", "gap")] == \
        ["W", "W", "W", "H", "D", "D", "D"]
    assert EDG.weighted_count(["EMA21", "EMA21w", "EMA50h", "EMA21"]) == 3.0
    # test del livello: tre discese dall'alto nella fascia = 3 test; le barre lontane non contano
    rec = {"lows": [105, 100.1, 104, 100.2, 106, 100.0, 107], "highs": [107] * 7, "closes": [106, 101, 105, 101, 107, 101, 108]}
    assert EDG.level_tests(100, "long", rec, 4.0) == 3
    rec2 = {"lows": [80, 82, 85, 88, 92, 95, 97], "highs": [90] * 7, "closes": [85, 86, 88, 90, 94, 97, 98]}
    assert EDG.level_tests(100, "long", rec2, 4.0) == 0
    ok, _, why = EDG.sr_edge(100, [{"name": n, "price": 100} for n in ("EMA21", "AVWAP swing low x", "swing high y")], 4.0,
                             "long", rec, [{"name": "EMA21w", "price": 100.5}])
    assert why["wsum"] == 4.5 and why["tests"] == 3 and not ok                      # zona forte ma testata troppo
    ok, _, why = EDG.sr_edge(100, [{"name": n, "price": 100} for n in ("EMA21", "AVWAP swing low x", "swing high y")], 4.0,
                             "long", rec2, [{"name": "EMA21w", "price": 100.5}])
    assert ok and why["tfs"] == "WD"
    ok, _, why = EDG.sr_edge(100, [{"name": n, "price": 100} for n in ("EMA21", "AVWAP swing low x", "swing high y", "gap")],
                             4.0, "long", rec2)
    assert why["wsum"] == 4.0 and why["tfs"] == "D" and not ok                      # solo daily: niente edge S&R
    # MTF: weekly e daily concordi
    mm = dict(m, w_close=110, ew9=105, ew21=100, ew9_slope=1, close=110, e9=108, e21=104, e21_slope=1)
    assert EDG.mtf_edge(mm, "long", 1)[0] and not EDG.mtf_edge(mm, "long", -1)[0]     # 1h e 1d obbligatori
    assert EDG.mtf_edge(dict(mm, ew9_slope=-1), "long", 1)[0]                        # il weekly non serve
    assert not EDG.mtf_edge(dict(mm, e21_slope=-1), "long", 1)[0]                    # il daily sì
    assert EDG.mtf_edge(mm, "long", None)[0] and not EDG.mtf_edge(mm, "short", 1)[0]  # senza 60m: daily + weekly
    ms = dict(mm, w_close=90, ew9=95, ew21=100, ew9_slope=-1, close=90, e9=92, e21=96, e21_slope=-1)
    assert EDG.mtf_edge(ms, "short", -1)[0]                                         # short [23/10a]: basta il daily
    assert EDG.mtf_edge(dict(ms, ew9_slope=1), "short", None)[0]
    assert not EDG.mtf_edge(dict(ms, e21_slope=1), "short", 1)[0]
    # RS a 1 settimana-1 mese e rotazione del gruppo
    ok, _, why = EDG.rs_edge(dict(m, rs5=3.0, rs21=-5.0), "long", "Improving")
    assert ok and why["rotation"]
    assert not EDG.rs_edge(dict(m, rs5=3.0, rs21=-5.0), "long", "Weak")[0]
    assert not EDG.rs_edge(dict(m, rs5=1.0, rs21=30.0), "long", "Strong")[0]      # oltre +21 a 1 mese non conta
    assert EDG.rs_edge(dict(m, rs5=-2.0, rs21=-6.0), "short", None)[0]
    # testi in inglese per card e alert
    r = dict(row, n_edges=3, edges=["MT", "SR", "RS"], tl={"value": 101.5, "touches": 3, "channel": True})
    assert EDG.edges_text(r) == "Edges `3/5`: M&T, S&R, RS"
    assert EDG.edges_text(r, compact=True) == "edges 3/5 (M&T S&R RS)"
    assert EDG.tl_text(r) == "Trendline up `101.50` (3 touches, channel)"


def test_regole_2026_10_22b_giornale_colonne_edge():
    """Colonne nuove del giornale (n_edges, edges, edge_score): il file vecchio si riscrive con l'intestazione nuova."""
    import csv as _csv
    p = TMP / "migrazione" / "trades.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = [f for f in J.TRADE_FIELDS if f not in ("n_edges", "edges", "edge_score")]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=old)
        w.writeheader()
        w.writerow({"id": "x1", "ticker": "AAA", "r_multiple": "1.5"})
    J._append(p, J.TRADE_FIELDS, {"id": "x2", "ticker": "BBB", "n_edges": 4, "edges": "MT SR MTF RS"})
    rows = J.read_csv(p)
    assert p.read_text(encoding="utf-8").splitlines()[0] == ",".join(J.TRADE_FIELDS)
    assert [r["id"] for r in rows] == ["x1", "x2"] and rows[0]["r_multiple"] == "1.5" and rows[0]["n_edges"] == ""
    assert rows[1]["n_edges"] == "4" and rows[1]["edges"] == "MT SR MTF RS"


def test_regole_2026_10_22b_lista_con_edge(monkeypatch):
    """La lista porta gli edge su candidati e "a un passo"; con META_FILTER in Focus solo i setup con almeno
    META_MIN_EDGES edge."""
    import json as _j
    monkeypatch.setattr(C, "META_EDGES", True)
    monkeypatch.setattr(C, "META_RANK", True)
    monkeypatch.setattr(C, "META_FILTER", True)
    test_daily_build()
    det = _j.loads((C.LISTS / f"work_{SESSION}" / "detail.json").read_text())
    assert all("n_edges" in r and "edge_detail" in r for r in det["candidates"] + det["near_misses"])
    assert all(r["n_edges"] >= C.META_MIN_EDGES for r in det["focus"] + det["counter_focus"])
    ks = [(0 if r.get("in_pool") else 1, -r["n_edges"], -r["score"]) for r in det["candidates"]]
    assert ks == sorted(ks)                                     # ordine: pool, numero di edge, punteggio
    monkeypatch.setattr(C, "META_RANK_MODE", "side")            # per lato: solo gli edge di META_SIDE_EDGES
    test_daily_build()
    det = _j.loads((C.LISTS / f"work_{SESSION}" / "detail.json").read_text())
    ks = [(0 if r.get("in_pool") else 1, -sum(k in r["edges"] for k in C.META_SIDE_EDGES[r["side"]]), -r["score"])
          for r in det["candidates"]]
    assert ks == sorted(ks)


def test_regole_2026_10_22b_istanza_multi_edge():
    """Istanza multi-edge al posto di Remy [RONIN 22/10, Andrea]: con JEFF_COACH_META=1 gli edge e le trendline si
    accendono e liste, giornale, alert, report e cache vanno in data/meta/; storico, breadth e temi restano quelli di Dua.
    [JEFF] In jeff-coach il multi-edge è l'unica istanza del repo: stessi interruttori, ma dati in data/ e storico scritto
    da lei; JEFF_COACH_META=0 torna alle regole di Dua."""
    import subprocess
    code = ("from jeffcoach import config as C; print(C.META_EDGES, C.META_RANK, C.TL_CHART, C.WRITE_HISTORY, "
            "C.LISTS.relative_to(C.HOME), C.JOURNAL.relative_to(C.HOME), C.ALERTS_STATE.relative_to(C.HOME), "
            "C.HISTORY.relative_to(C.HOME), C.RULES_VERSION.endswith('-meta'), C.META_RANK_MODE)")
    root = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ, JEFF_COACH_META="1", JEFF_COACH_JEFF="0")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True).stdout.split()
    assert out == ["True", "True", "True", "True", "lists", "journal", "alerts", "history", "True", "side"]   # [JEFF]
    env["JEFF_COACH_META"] = "0"                                                                             # [JEFF]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True).stdout.split()
    assert out == ["False", "False", "False", "True", "lists", "journal", "alerts", "history", "False", "count"]




def test_regole_2026_10_23a_orizzontali():
    """Supporti e resistenze orizzontali [RONIN 23/10, Andrea]: swing che si ripetono allo stesso prezzo (anche un
    vecchio massimo che diventa supporto) danno una linea; tocchi sparsi danno un'area con i due bordi; contano
    nell'edge S&R (con 3+ tocchi come un weekly) e si disegnano sul grafico multi-edge."""
    from jeffcoach import orizzontali as HZ, edges as EDG, chart as CH
    n = 220
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    t = np.arange(n)
    # oscillazione tra 100 (supporto, toccato a 99,6-100,4) e 120 (resistenza esatta), poi rottura sopra 120 e
    # ritorno sul vecchio massimo da sopra (cambio di ruolo)
    osc = (1 - np.cos(2 * np.pi * t / 20)) / 2
    mid = np.where(t < 160, 100 + 20 * osc, 135 - 15 * ((t - 160) % 20 < 10) * (1 - np.abs((t - 160) % 20 - 5) / 5))
    jitter = np.where(t % 40 < 20, -0.4, 0.4)
    lo = np.where(t < 160, np.where(osc < 0.02, 100 + jitter, mid - 0.8), mid - 1.0)
    hi = np.where(t < 160, np.where(osc > 0.98, 120.0, mid + 0.8), mid + 1.0)
    cl = (lo + hi) / 2
    df = pd.DataFrame({"Open": cl, "High": hi, "Low": lo, "Close": cl, "Volume": np.full(n, 1e6)}, index=idx)
    lv = HZ.find_levels(df, 3.0)
    sup = [x for x in lv if x["lo"] <= 101 and x["hi"] >= 99]
    res = [x for x in lv if x["lo"] <= 120.5 and x["hi"] >= 119.5]
    assert sup and sup[0]["touches"] >= 4 and sup[0]["lows"] >= 4
    assert res and res[0]["touches"] >= 4
    assert all(x["score"] >= C.HZ_MIN_SCORE for x in lv)
    gap = 1 + C.HZ_GAP_ADR * 3.0 / 100                 # livelli significativi e distanti almeno 1 ADR [Andrea 23/10]
    assert all(a["lo"] > b["hi"] * gap or b["lo"] > a["hi"] * gap for i, a in enumerate(lv) for b in lv[i + 1:])
    for x in lv:                                       # aree con i bordi ordinati, linee con lo = hi = prezzo
        assert x["lo"] <= x["price"] <= x["hi"] and (x["kind"] == "zone") == (x["hi"] > x["lo"])
    z = dict(kind="zone", price=100.0, lo=99.6, hi=100.4, touches=5)
    assert HZ.name(z) == "HZ 99.60-100.40 x5" and HZ.touches_of(HZ.name(z)) == 5 and EDG.level_tf(HZ.name(z)) == "W"
    zw = dict(z, tf="W", kind="line", touches=2)          # livello weekly (mesi e anni prima): pesa come un weekly
    assert HZ.name(zw) == "HLW 100.00 x2" and EDG.level_tf(HZ.name(zw)) == "W" and HZ.touches_of(HZ.name(zw)) == 2
    assert all(x["tf"] in ("D", "W") for x in lv)
    assert not C.META_INSTANCE and C.DAILY_HISTORY_DAYS == 620 and C.CHART_DAILY_DAYS == 420     # Dua com'era
    assert EDG.level_tf(HZ.name(dict(z, kind="line", touches=2))) == "D"
    sl = HZ.as_levels([z], 101.0)
    assert sl["long"] and not sl["short"]
    assert HZ.as_levels([z], 100.0)["short"]          # close dentro l'area: vale per i due lati
    assert HZ.near([z], 101.5, 3.0)["lo"] == 99.6 and HZ.near([z], 110.0, 3.0) is None
    # nell'edge S&R un'area conta se il livello d'ingresso è entro 0,5 ADR dal suo bordo
    ok, _, why = EDG.sr_edge(101.0, [{"name": n, "price": 101.0} for n in ("EMA21", "AVWAP swing low x", "gap")], 3.0,
                             "long", {}, HZ.as_levels([z], 102.0)["long"])
    assert HZ.name(z) in why["levels"] and "W" in why["tfs"] and ok
    monkeypatch_png = CH.alert_chart("TST", "long", None, 5, SESSION, title="test", daily=df)
    assert monkeypatch_png and monkeypatch_png[:4] == b"\x89PNG"
    C.HZ_CHART, old = True, C.HZ_CHART
    try:
        png = CH.alert_chart("TST", "long", None, 5, SESSION, title="test", daily=df)
    finally:
        C.HZ_CHART = old
    assert png and png[:4] == b"\x89PNG"


def test_regole_2026_10_27_liste_in_percentuale_e_sedute_a_meta():
    """Card [RONIN 27/10, Andrea]: linea con la % del pool (e dell'universo liquido) in Leading / Mediocre / Lagging nel
    grafico del regime; il Market Monitor nostro non scrive una seduta con i dati a metà (26/10: 409 titoli su 5.594)."""
    from jeffcoach import pool as PL, breadth_chart as BC, breadth as B
    rng = np.random.default_rng(1)
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=420)
    daily = {}
    for i in range(220):
        r = rng.normal(0.0005 * (i % 7 - 3), 0.02 + 0.0002 * i, len(idx))
        c = 50 * np.exp(np.cumsum(r))
        daily[f"S{i}"] = pd.DataFrame({"Open": c, "High": c * 1.03, "Low": c * 0.97, "Close": c,
                                       "Volume": 3e6 * (1 + i % 11) * rng.uniform(0.5, 1.5, len(idx))}, index=idx)
    pb = PL.pool_breadth(daily, list(daily), idx)
    lh = pb["lists_hist"]
    assert len(lh) == C.LISTS_CHART_DAYS and lh[-1]["date"] == AS_OF.isoformat() and lh[-1]["n"] == pb["n"]
    last = lh[-1]
    assert abs(last["L"] + last["M"] + last["G"] - 100) < 0.5 and abs(last["uL"] + last["uM"] + last["uG"] - 100) < 0.5
    assert round(last["L"]) == round(pb["lists"]["Leading"] / pb["n"] * 100)
    own = [dict(date=str(d.date()), up4=100, down4=90, t2108=40, up20w=20, down20w=10, nh=50, nl=20) for d in idx[-130:]]
    h = BC.mm_history([], own, AS_OF)
    png = BC.render(h, 200, 200, lists_hist=lh)
    assert png and png[:4] == b"\x89PNG"
    assert len(png) > len(BC.render(h, 200, 200))                     # un pannello in più
    # seduta con i dati a metà: la riga non si scrive (resta quella dell'archivio, la rifà il calcolo dopo)
    full = {s: daily[s] for s in list(daily)[:120]}
    cut = {s: (df if j < 20 else df.iloc[:-1]) for j, (s, df) in enumerate(full.items())}
    rows = B.own_rows(cut)
    assert rows and rows[0]["date"] != AS_OF.isoformat()
    assert B.own_rows(full)[0]["date"] == AS_OF.isoformat()


def test_regole_2026_10_28a_gruppo_etf():
    """Gruppo del titolo dal suo ETF [RONIN 28/10a, Andrea]: ETF dalla lista di prima dei basket (il più liquido del
    tema, prima quelli con azioni), preferenza per la forza contro la media del gruppo, niente short con l'ETF in trend
    su, long solo con l'ETF vicino a un suo supporto con 2+ livelli; grafico degli alert con l'ETF in una seconda immagine."""
    from jeffcoach import gruppo as GR, chart as CH, discord as DS
    mp = {"theme_etfs": {"Semiconductors": ["SMH", "XSD"], "Bitcoin": ["IBIT", "WGMI"], "Retail": ["XRT"]},
          "proxy_etfs": {"Bitcoin": ["IBIT"]},
          "tickers": {"MU": {"primary": "Semiconductors", "themes": ["Semiconductors"]},
                      "MARA": {"primary": "Bitcoin", "themes": ["Bitcoin"]},
                      "BURL": {"primary": None, "themes": ["Retail", "ESG"]}, "XYZ": {"primary": None, "themes": ["ESG"]}}}
    dv = {"SMH": 2e9, "XSD": 5e7, "IBIT": 3e9, "WGMI": 2e7, "XRT": 4e8}
    g = GR.assign(["MU", "MARA", "BURL", "XYZ"], mp, dv)
    assert g["MU"]["etf"] == "SMH" and g["MARA"]["etf"] == "WGMI" and g["BURL"]["etf"] == "XRT" and "XYZ" not in g
    grp = {"tickers": {"MU": dict(g["MU"], rs_group=2.5)},
           "etfs": {"SMH": dict(adr=2.0, close=100.0, up=False, dn=True,
                                areas={"long": [dict(lo=95.0, hi=96.0, n=2), dict(lo=90.0, hi=91.0, n=1)], "short": []})}}
    rl, rs = GR.row_fields("MU", "long", grp), GR.row_fields("MU", "short", grp)
    assert rl["group_fav"] == 1 and rs["group_fav"] == -1 and rl["group_sup"] == [[95.0, 96.0, 2]] and "group_sup" not in rs
    idx = pd.date_range("2026-10-28 09:30", periods=30, freq="1min", tz=ET)
    near = pd.DataFrame({"Open": 97.0, "High": 97.5, "Low": 96.3, "Close": 97.2, "Volume": 1e5}, index=idx)
    far = near.assign(Low=98.0, Close=98.5)
    broke = near.assign(Low=94.0, Close=94.0)
    assert GR.long_near_support(rl, near) is None                 # minimo entro 0,25 ADR (0,5$) dal bordo alto 96
    assert GR.long_near_support(rl, far) and GR.long_near_support(rl, broke)
    assert GR.long_near_support(rl, None) is None and GR.long_near_support({}, far) is None   # senza dati: passa
    n = 200
    di = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=n)
    c = 100 + np.sin(np.arange(n) / 9) * 5
    df = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=di)
    p1 = CH.alert_chart("TST", "long", near, 5, SESSION, title="t", daily=df, panel=False, areas=[(95.0, 96.0)])
    p2 = CH.alert_chart("TST", "long", near, 5, SESSION, title="t", daily=df)
    assert p1 and p1[:4] == b"\x89PNG" and p2 and len(p1) != len(p2)
    assert DS.send_alert("t", "b", dry_run=True, image=p1, image2=p1)["sent"]


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


def test_regole_2026_10_28b_card_senza_classifica_e_grafici_dei_focus():
    """[ANDREA 28/10] Messaggio dei temi senza classifica (restano i grafici RS); multi-edge: grafico di ogni Focus
    sotto il suo riquadro, in gallerie da 4 (stesso url), card divisa in più messaggi entro i limiti di Discord."""
    from jeffcoach import output as O, discord as DS
    assert C.CARD_THEMES_RANKING is False
    rows = [dict(ticker=f"L{i}", side="long", level=10.0 + i) for i in range(6)] + \
           [dict(ticker=f"S{i}", side="short", level=20.0 + i) for i in range(3)]
    emb = [{"description": "head", "color": 1, "image": {"url": "attachment://breadth.png"}},
           {"description": "**FOCUS LONG**", "color": 2, "_rows": [r["ticker"] for r in rows[:6]]},
           {"description": "**FOCUS SHORT**", "color": 3, "_rows": [r["ticker"] for r in rows[6:]]}]
    charts = {r["ticker"]: f"focus_{r['ticker']}.png" for r in rows if r["ticker"] != "L5"}
    out = O.with_focus_charts([dict(e) for e in emb], charts)
    assert not any("_rows" in e for e in out)
    lg = out[1:6]                                   # testo long + L1..L3 nella galleria, poi L4 (gruppo 2)
    assert lg[0]["description"] == "**FOCUS LONG**" and lg[0]["image"]["url"] == "attachment://focus_L0.png"
    assert len({e["url"] for e in lg[:4]}) == 1 and lg[4]["url"] != lg[0]["url"] and "description" not in lg[4]
    assert out[6]["description"] == "**FOCUS SHORT**" and out[6]["image"]["url"] == "attachment://focus_S0.png"
    assert len(out) == 1 + 5 + 3
    assert O.with_focus_charts([dict(e) for e in emb], {}) == [{k: v for k, v in e.items() if k != "_rows"} for e in emb]
    msgs = DS.split_card(out)
    assert sum(len(m) for m in msgs) == len(out) and all(len(m) <= 10 for m in msgs)
    files = lambda m: sum(1 for e in m if "attachment://" in str(e.get("image")))
    assert files(msgs[0]) + 1 <= 10 and all(files(m) <= 10 for m in msgs[1:])
    assert msgs[0][0]["description"] == "head" and msgs[-1][-1]["image"]["url"] == "attachment://focus_S2.png"
    big = [{"description": "x"}] + [{"url": "u", "image": {"url": f"attachment://f{i}.png"}} for i in range(15)]
    assert [len(m) for m in DS.split_card(big)] == [10, 6]
    assert DS.split_card([{"description": "a"}, {"description": "b"}]) == [[{"description": "a"}, {"description": "b"}]]
