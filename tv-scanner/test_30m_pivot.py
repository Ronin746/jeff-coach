#!/usr/bin/env python3
"""Unit tests for 30m pivot (break / re-break / cross / Discord embeds)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner import (
    Indicators,
    TRIGGER_30M_PIVOT,
    RS_MIN_30M_PIVOT,
    PIVOT30_ATR_MULT,
    PIVOT30_MIN_REDS,
    already_emitted,
    detect_30m_pivot,
    rebuild_30m_bars,
    closed_rth_5m,
    refine_30m_pivot_signal,
    _pivot30_state_keys,
    daily_atr14,
)
from rs_rating import (
    attribute_percentile,
    score_to_rating,
    PINE_REPLAY_DEFAULTS,
)
from discord_notify import (
    format_discord_body,
    format_pivot30_body,
    build_discord_embeds,
    send_discord,
    _split_buckets,
)

ETZ = ZoneInfo("America/New_York")


def _ts(y, m, d, hh, mm) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=ETZ).timestamp())


def _5m(t: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> dict:
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def _fill_30m(start_t: int, o: float, h: float, l: float, c: float) -> list[dict]:
    bars = []
    for i in range(6):
        t = start_t + i * 300
        if i == 0:
            bo, bh, bl, bc = o, max(o, h), min(o, l), o
        elif i == 5:
            bo, bh, bl, bc = o if o == c else (o + c) / 2, h, l, c
        else:
            mid = (o + c) / 2
            bo, bh, bl, bc = mid, h, l, mid
        bh = max(bh, bo, bc, h)
        bl = min(bl, bo, bc, l)
        bars.append(_5m(t, bo, bh, bl, bc))
    return bars


def _ind(
    bar_t: int,
    price: float = 100.0,
    *,
    ema6: float = 101.0,
    ema20: float = 100.0,
    prev_ema6: float = 99.0,
    prev_ema20: float = 100.0,
    macd: float = 1.0,
    signal: float = 0.5,
) -> Indicators:
    return Indicators(
        price=price,
        ema6=ema6,
        ema20=ema20,
        vwap=price,
        macd=macd,
        signal=signal,
        hist=macd - signal,
        prev_close=price,
        prev_vwap=price,
        prev_ema6=prev_ema6,
        prev_ema20=prev_ema20,
        bar_t=bar_t,
    )



def _daily_atr(
    atr: float,
    n: int = 40,
    last_day=(2026, 9, 25),
    close: float = 100.0,
) -> list[dict]:
    """Synthetic closed dailies with constant TR=atr → Wilder ATR(14) ≈ atr.

    Bars end on ``last_day`` (UTC midnight) so drop_forming_daily keeps them
    for any RTH ``now`` on a later session date. ``close`` is the prior-day
    close used by the gap-ref drop gate.
    """
    end = datetime(last_day[0], last_day[1], last_day[2], 0, 0, tzinfo=ZoneInfo("UTC"))
    bars = []
    c = float(close)
    half = atr / 2.0
    for i in range(n):
        dt = end - timedelta(days=(n - 1 - i))
        bars.append({
            "t": int(dt.timestamp()),
            "o": c,
            "h": c + half,
            "l": c - half,
            "c": c,
            "v": 1_000_000.0,
        })
    return bars


# Default: prior close=100; _session_base open=120 → gap_up ref=120,
# min_low=105 → drop=15; ATR=10 → 0.5*10=5 → qualifies
_D_ATR10 = _daily_atr(10.0)


def _session_base() -> list[dict]:
    """Mon 2026-09-28: 3 red 30m + green 11:00 (H=110, L=100)."""
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 120, 121, 114, 115)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 115, 116, 110, 111)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 111, 112, 105, 106)
    bars += _fill_30m(_ts(2026, 9, 28, 11, 0), 106, 110, 100, 108)
    return bars


def test_rebuild_30m_colors():
    bars = _session_base()
    m30 = rebuild_30m_bars(closed_rth_5m(bars, now=_ts(2026, 9, 28, 11, 35)))
    assert len(m30) == 4
    assert m30[3]["h"] == 110 and m30[3]["l"] == 100


def test_break_fires_once():
    bars = _session_base()
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    now = t_break + 300
    # no EMA cross (prev already above)
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=now, daily_bars=_D_ATR10)
    assert sig is not None and sig.pivot_kind == "break" and sig.pivot_alert_n == 1
    emitted = {}
    for k in _pivot30_state_keys(sig):
        emitted[k] = {"symbol": sig.symbol}
    assert already_emitted(emitted, sig) is True


def test_three_tiny_reds_below_atr_no_fire():
    """3 consecutive reds but gap-ref drop < 0.5×ATR → no pivot."""
    # gap_up ref=open≈100.3, min_low=99.7 → drop≈0.6; ATR=10 → need ≥5 → fail
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 100.3, 100.4, 100.0, 100.1)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 100.1, 100.2, 99.9, 100.0)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 100.0, 100.1, 99.7, 99.8)
    bars += _fill_30m(_ts(2026, 9, 28, 11, 0), 99.8, 101.0, 99.6, 100.5)  # green
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 100.5, 101.5, 100.2, 101.2))
    now = t_break + 300
    ind = _ind(t_break, 101.2, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=now, daily_bars=_daily_atr(10.0),
    )
    assert sig is None


def test_two_reds_atr_qualified_fires():
    """2 reds with gap-ref drop ≥ 0.5×ATR + green → break fires."""
    # prior close=100, open=120 → gap_up ref=120; min_low=105 → drop=15
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 120, 121, 114, 115)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 115, 116, 105, 111)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 111, 118, 110, 116)  # green
    t_break = _ts(2026, 9, 28, 11, 0)
    bars.append(_5m(t_break, 116, 119, 115, 118))
    now = t_break + 300
    ind = _ind(t_break, 118, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=now, daily_bars=_D_ATR10,
    )
    assert sig is not None and sig.pivot_kind == "break" and sig.pivot_alert_n == 1
    assert sig.pivot_drop == 15.0
    assert abs(sig.pivot_atr - 10.0) < 1e-6
    assert sig.pivot_ref == 120.0 and sig.pivot_ref_kind == "gap_up"
    assert PIVOT30_MIN_REDS == 2 and __import__("scanner").PIVOT30_ATR_MULT == 0.5


def test_gap_down_uses_prior_close():
    """Gap-down: RTH open < prior close → ref = prior close."""
    # prior close=130, open=120 → gap_down; min_low=105 → drop=25; ATR=10 → OK
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 120, 121, 114, 115)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 115, 116, 105, 111)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 111, 118, 110, 116)  # green
    t_break = _ts(2026, 9, 28, 11, 0)
    bars.append(_5m(t_break, 116, 119, 115, 118))
    now = t_break + 300
    ind = _ind(t_break, 118, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    daily = _daily_atr(10.0, close=130.0)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=now, daily_bars=daily,
    )
    assert sig is not None and sig.pivot_kind == "break"
    assert sig.pivot_ref == 130.0 and sig.pivot_ref_kind == "gap_down"
    assert sig.pivot_drop == 25.0  # 130 - 105


def test_gap_up_uses_session_open():
    """Gap-up/flat: RTH open >= prior close → ref = RTH open."""
    # prior=100, open=120 → gap_up; already covered by two_reds but assert kind
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 120, 121, 114, 115)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 115, 116, 110, 111)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 111, 112, 105, 106)
    bars += _fill_30m(_ts(2026, 9, 28, 11, 0), 106, 110, 100, 108)  # green
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    now = t_break + 300
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=now, daily_bars=_D_ATR10,
    )
    assert sig is not None
    assert sig.pivot_ref_kind == "gap_up" and sig.pivot_ref == 120.0
    assert sig.pivot_drop == 15.0  # 120 - 105


def test_reds_must_be_same_session_day():
    """Fri reds + only 1 Mon red before Mon green → no pivot."""
    flat = []
    for chunk in [
        _fill_30m(_ts(2026, 10, 2, 15, 0), 110, 110.5, 108, 109),   # Fri R
        _fill_30m(_ts(2026, 10, 2, 15, 30), 109, 109.5, 107, 108),  # Fri R
        _fill_30m(_ts(2026, 10, 5, 9, 30), 108, 109, 105, 106),     # Mon R
        _fill_30m(_ts(2026, 10, 5, 10, 0), 106, 110, 105.5, 109),   # Mon G
        _fill_30m(_ts(2026, 10, 5, 10, 30), 109, 112, 108, 111),    # break bar
    ]:
        flat.extend(chunk)
    now = _ts(2026, 10, 5, 11, 0)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", flat, _ind(_ts(2026, 10, 5, 10, 55), 111), now=now, daily_bars=_daily_atr(10.0, last_day=(2026, 10, 2)))
    assert sig is None, sig


def test_three_same_day_reds_still_fire():
    """3 Mon reds + Mon green → break fires."""
    flat = []
    for chunk in [
        _fill_30m(_ts(2026, 10, 5, 9, 30), 110, 110.5, 108, 109),
        _fill_30m(_ts(2026, 10, 5, 10, 0), 109, 109.5, 107, 108),
        _fill_30m(_ts(2026, 10, 5, 10, 30), 108, 108.5, 106, 107),
        _fill_30m(_ts(2026, 10, 5, 11, 0), 107, 112, 106.5, 111),
    ]:
        flat.extend(chunk)
    t_break = _ts(2026, 10, 5, 11, 30)
    flat.append(_5m(t_break, 111, 113, 110, 112.5))
    now = t_break + 300
    ind = _ind(t_break, 112.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", flat, ind, now=now, daily_bars=_daily_atr(5.0, last_day=(2026, 10, 2)))
    assert sig is not None and sig.pivot_kind == "break" and sig.pivot_alert_n == 1
    assert sig.pivot_high == 112



def test_stop_before_break_no_fire():
    bars = _session_base()
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 109, 99, 101))
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 101, 112, 100.5, 111))
    now = t2 + 300
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _ind(t2, 111), now=now, daily_bars=_D_ATR10)
    assert sig is None


def test_rebreak_second_and_third():
    bars = _session_base()
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 111, 107, 110.5))
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 110, 110.2, 108, 109))
    t3 = _ts(2026, 9, 28, 11, 40)
    bars.append(_5m(t3, 109, 111.5, 108.5, 111))
    ind = _ind(t3, 111, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig2 = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t3 + 300, daily_bars=_D_ATR10)
    assert sig2 is not None and sig2.pivot_alert_n == 2 and sig2.pivot_kind == "break"

    t4 = _ts(2026, 9, 28, 11, 45)
    bars.append(_5m(t4, 111, 111.2, 109, 109.5))
    t5 = _ts(2026, 9, 28, 11, 50)
    bars.append(_5m(t5, 109.5, 112, 109, 111.8))
    ind3 = _ind(t5, 111.8, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig3 = detect_30m_pivot("NASDAQ:TEST", bars, ind3, now=t5 + 300, daily_bars=_D_ATR10)
    assert sig3 is not None and sig3.pivot_alert_n == 3
    body = format_pivot30_body([{
        "symbol": sig3.symbol, "trigger": TRIGGER_30M_PIVOT,
        "price": sig3.price, "bar_t": sig3.bar_t, "pivot_alert_n": 3,
        "pivot_high": sig3.pivot_high, "pivot_low": sig3.pivot_low,
        "pivot_kind": "break",
    }])
    assert "(3°)" in body and "H 110.00" in body and "L 100.00" in body


def test_rebreak_after_stop_none():
    bars = _session_base()
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 111, 107, 110.5))
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 110, 110.2, 99, 109))
    t3 = _ts(2026, 9, 28, 11, 40)
    bars.append(_5m(t3, 109, 112, 108, 111))
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _ind(t3, 111), now=t3 + 300, daily_bars=_D_ATR10)
    assert sig is None


def test_no_late_fire():
    bars = _session_base()
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 111, 107, 110.5))
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 110.5, 110.8, 110, 110.6))
    ind = _ind(t2, 110.6, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t2 + 300, daily_bars=_D_ATR10)
    assert sig is None



def test_fourth_break_capped():
    """Max 3 break alerts; 4th re-break after dip -> no break alert."""
    bars = _session_base()
    # break 1
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 111, 107, 110.5))
    # dip
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 110, 110.2, 108, 109))
    # break 2
    t3 = _ts(2026, 9, 28, 11, 40)
    bars.append(_5m(t3, 109, 111.5, 108.5, 111))
    # dip
    t4 = _ts(2026, 9, 28, 11, 45)
    bars.append(_5m(t4, 111, 111.2, 109, 109.5))
    # break 3
    t5 = _ts(2026, 9, 28, 11, 50)
    bars.append(_5m(t5, 109.5, 112, 109, 111.8))
    ind3 = _ind(t5, 111.8, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig3 = detect_30m_pivot("NASDAQ:TEST", bars, ind3, now=t5 + 300, daily_bars=_D_ATR10)
    assert sig3 is not None and sig3.pivot_alert_n == 3 and sig3.pivot_kind == "break"
    # dip again
    t6 = _ts(2026, 9, 28, 11, 55)
    # 11:55 is last RTH 5m of... wait 11:55 is fine
    bars.append(_5m(t6, 111, 111.1, 109, 109.2))
    # would-be break 4 — use next day morning or continue afternoon
    t7 = _ts(2026, 9, 28, 12, 0)
    bars.append(_5m(t7, 109.2, 113, 109, 112))
    ind4 = _ind(t7, 112, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig4 = detect_30m_pivot("NASDAQ:TEST", bars, ind4, now=t7 + 300, daily_bars=_D_ATR10)
    assert sig4 is None, f"4th break should be capped, got {sig4}"


def test_cross_after_three_breaks_still_fires():
    """After 3 breaks (capped), EMA cross while pivot still active still fires."""
    bars = _session_base()
    seq = [
        (_ts(2026, 9, 28, 11, 30), 108, 111, 107, 110.5),   # break 1
        (_ts(2026, 9, 28, 11, 35), 110, 110.2, 108, 109),   # dip
        (_ts(2026, 9, 28, 11, 40), 109, 111.5, 108.5, 111), # break 2
        (_ts(2026, 9, 28, 11, 45), 111, 111.2, 109, 109.5), # dip
        (_ts(2026, 9, 28, 11, 50), 109.5, 112, 109, 111.8), # break 3
        (_ts(2026, 9, 28, 11, 55), 111, 111.1, 109, 109.2), # quiet / below H
    ]
    for t, o, h, l, c in seq:
        bars.append(_5m(t, o, h, l, c))
    # cross bar: no break (high <= 110), EMA cross + MACD
    t = _ts(2026, 9, 28, 12, 0)
    bars.append(_5m(t, 109, 109.8, 108.5, 109.5))
    ind = _ind(t, 109.5, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100, macd=1, signal=0.5)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10)
    assert sig is not None and sig.pivot_kind == "cross", sig
    assert sig.pivot_alert_n is None


def test_cross_while_active():
    bars = _session_base()
    # quiet bar after green — no break (high <= 110)
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 109.5, 107, 109))
    # EMA cross + MACD bull
    ind = _ind(t, 109, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100, macd=1, signal=0.5)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10)
    assert sig is not None, "cross while active should fire"
    assert sig.pivot_kind == "cross"
    assert sig.pivot_alert_n is None
    assert sig.pivot_high == 110 and sig.pivot_low == 100


def test_cross_after_stop_none():
    bars = _session_base()
    t1 = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t1, 108, 109, 99, 101))  # stop
    t2 = _ts(2026, 9, 28, 11, 35)
    bars.append(_5m(t2, 101, 105, 100.5, 104))
    ind = _ind(t2, 104, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t2 + 300, daily_bars=_D_ATR10)
    assert sig is None


def test_same_bar_break_and_cross():
    bars = _session_base()
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 111, 107, 110.5))  # break
    ind = _ind(t, 110.5, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10)
    assert sig is not None
    assert sig.pivot_kind == "break + cross"
    assert sig.pivot_alert_n == 1
    keys = _pivot30_state_keys(sig)
    assert len(keys) == 2
    assert any("|break|1" in k for k in keys)
    assert any("|cross|" in k for k in keys)


def test_discord_bucket_not_ema():
    sigs = [
        {"symbol": "NASDAQ:A", "trigger": "EMA 6/20 CROSS", "price": 1, "bar_t": 1},
        {
            "symbol": "NASDAQ:B", "trigger": "30M PIVOT", "price": 2, "bar_t": 1,
            "pivot_alert_n": 2, "pivot_high": 10.5, "pivot_low": 9.25, "pivot_kind": "break",
        },
    ]
    ema, vwap, daily, sma30, pivot30 = _split_buckets(sigs)
    assert len(ema) == 1 and len(pivot30) == 1
    main = format_discord_body(sigs)
    assert "• 30m pivot:" not in main
    assert "Ema 6/20" in main
    piv = format_pivot30_body(sigs)
    assert "(2°)" in piv and "H 10.50 / L 9.25" in piv


def test_discord_two_embeds_main_and_pivot():
    sigs = [
        {"symbol": "NASDAQ:AMD", "trigger": "EMA 6/20 CROSS", "price": 160.0, "bar_t": 1790689800},
        {
            "symbol": "NASDAQ:CRDO", "trigger": "30M PIVOT", "price": 195.4, "bar_t": 1790689800,
            "pivot_alert_n": 1, "pivot_high": 194.79, "pivot_low": 188.82, "pivot_kind": "break",
        },
    ]
    embeds = build_discord_embeds(sigs)
    assert len(embeds) == 2
    assert embeds[0]["title"].startswith("🦅")
    assert embeds[1]["title"].startswith("30 minute pivot •")
    assert "• 30m pivot:" not in embeds[1]["description"]
    assert "H 194.79 / L 188.82" in embeds[1]["description"]
    dry = send_discord(sigs, dry_run=True)
    assert dry["reason"] == "dry_run"
    assert len(dry["embeds"]) == 2
    assert "payload" in dry and len(dry["payload"]["embeds"]) == 2


def test_discord_only_pivot_one_embed():
    sigs = [{
        "symbol": "NASDAQ:CRDO", "trigger": "30M PIVOT", "price": 195.4, "bar_t": 1790689800,
        "pivot_alert_n": 1, "pivot_high": 194.79, "pivot_low": 188.82, "pivot_kind": "cross",
    }]
    embeds = build_discord_embeds(sigs)
    assert len(embeds) == 1
    assert embeds[0]["title"] == "30 minute pivot • 15:55 Close"
    assert "cross" in embeds[0]["description"]
    assert format_discord_body(sigs) == ""


def test_discord_pivot_range_aligned():
    body = format_pivot30_body([
        {
            "symbol": "NASDAQ:CRDO", "trigger": TRIGGER_30M_PIVOT,
            "price": 195.4, "bar_t": 1, "pivot_alert_n": 1,
            "pivot_high": 194.79, "pivot_low": 188.82, "pivot_kind": "break",
        },
        {
            "symbol": "NASDAQ:LITE", "trigger": TRIGGER_30M_PIVOT,
            "price": 910.0, "bar_t": 1, "pivot_alert_n": 2,
            "pivot_high": 893.45, "pivot_low": 883.43, "pivot_kind": "break",
        },
        {
            "symbol": "NASDAQ:MRVL", "trigger": TRIGGER_30M_PIVOT,
            "price": 260.5, "bar_t": 1, "pivot_alert_n": None,
            "pivot_high": 259.29, "pivot_low": 257.42, "pivot_kind": "cross",
        },
        {
            "symbol": "NASDAQ:STX", "trigger": TRIGGER_30M_PIVOT,
            "price": 906.89, "bar_t": 1, "pivot_alert_n": 3,
            "pivot_high": 906.17, "pivot_low": 900.96, "pivot_kind": "break + cross",
        },
    ])
    assert "H 194.79 / L 188.82" in body
    assert "(2°)" in body and "(3°)" in body
    assert "break + cross" in body and "cross" in body


def test_refine_partial_dedupe():
    """If break already emitted, same-bar break+cross becomes cross-only."""
    bars = _session_base()
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 111, 107, 110.5))
    ind = _ind(t, 110.5, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100)
    sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10)
    assert sig and sig.pivot_kind == "break + cross"
    emitted = {_pivot30_state_keys(sig)[0]: {"symbol": sig.symbol}}  # break key only
    refined = refine_30m_pivot_signal(emitted, sig)
    assert refined is not None and refined.pivot_kind == "cross"


def test_rs_gate_79_no_alert():
    bars = _session_base()
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=t_break + 300,
        rs_rating=79, min_rs=80,
        daily_bars=_D_ATR10)
    assert sig is None  # gate logic still works when a min is set


def test_rs_gate_off_low_rs_still_alerts():
    # 2026-10-06: live RS_MIN_30M_PIVOT=None -> RS 18 or missing still fires
    assert RS_MIN_30M_PIVOT is None
    bars = _session_base()
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    for rr in (18, None):
        sig = detect_30m_pivot(
            "NASDAQ:TEST", bars, ind, now=t_break + 300,
            rs_rating=rr, min_rs=RS_MIN_30M_PIVOT,
            daily_bars=_D_ATR10)
        assert sig is not None and sig.pivot_kind == "break"


def test_rs_gate_80_alert():
    bars = _session_base()
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    # no EMA cross — isolate break + RS gate
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=t_break + 300,
        rs_rating=80, min_rs=RS_MIN_30M_PIVOT,
        daily_bars=_D_ATR10)
    assert sig is not None and sig.pivot_kind == "break"
    assert sig.rs_rating == 80


def test_rs_mapping_function():
    """Unit test Fred6724 score→rating with pine replay defaults."""
    th = PINE_REPLAY_DEFAULTS
    first, scnd, thrd, frth, ffth, sxth, svth = th
    assert score_to_rating(first, th) == 99
    assert score_to_rating(first + 10, th) == 99
    assert score_to_rating(svth, th) == 1
    assert score_to_rating(svth - 1, th) == 1
    # weight-0 band [frth, thrd): score at frth → near dn=50
    r_lo = attribute_percentile(frth, thrd, frth, 69, 50, 0)
    assert 50 <= r_lo <= 69
    assert score_to_rating(frth, th) == int(round(r_lo))
    # mid of [ffth, frth)
    mid = (ffth + frth) / 2
    r_mid = attribute_percentile(mid, frth, ffth, 49, 30, 0)
    assert 30 <= r_mid <= 49
    assert score_to_rating(mid, th) == int(round(r_mid))
    # top band with weight 0.33
    just_below_first = first - 0.01
    r_hi = attribute_percentile(just_below_first, first, scnd, 98, 90, 0.33)
    assert 90 <= r_hi <= 98
    assert score_to_rating(just_below_first, th) == int(round(r_hi))


def test_discord_pivot_shows_rs():
    body = format_pivot30_body([
        {
            "symbol": "NASDAQ:CRDO", "trigger": TRIGGER_30M_PIVOT,
            "price": 195.4, "bar_t": 1, "pivot_alert_n": 1,
            "pivot_high": 194.79, "pivot_low": 188.82, "pivot_kind": "break",
            "rs_rating": 92,
        },
    ])
    assert "RS 92" in body
    assert "H 194.79 / L 188.82" in body



def test_universe_wl_mode_only_wl(tmp_path=None):
    """UNIVERSE_MODE wl323848747: universe = WL file only; legacy sources unused."""
    import tempfile
    import scanner as sc
    assert sc.UNIVERSE_MODE == "wl323848747"
    assert sc.ENABLE_DAY_MONITOR_EMA is False
    assert sc.ENABLE_DAILY_EMA_PULLBACK is False and sc.ENABLE_SMA30_PULLBACK is False
    assert sc.ENABLE_VWAP_CROSS is False and sc.ENABLE_30M_PIVOT is True
    d = Path(tempfile.mkdtemp())
    wl = d / "wl.txt"
    wl.write_text("# header\nNASDAQ:AMD\nNYSE:DELL  # note\n# EXCLUDED_ETF NASDAQ:QQQ\nNASDAQ:AMD\n")
    old_path, old_excl = sc.PIVOT_WL_PATH, set(sc.UNIVERSE_EXCLUDE)
    old_paths = list(sc.PIVOT_WL_PATHS)
    called = []
    orig = (sc.load_focus_symbols, sc.load_sydney_top, sc.load_day_monitor)
    try:
        sc.PIVOT_WL_PATH = wl
        sc.PIVOT_WL_PATHS = [wl]
        sc.load_focus_symbols = lambda *a, **k: called.append("focus") or ["NASDAQ:XXX"]
        sc.load_sydney_top = lambda *a, **k: called.append("sydney") or ["NASDAQ:YYY"]
        sc.load_day_monitor = lambda *a, **k: called.append("day") or ["NASDAQ:ZZZ"]
        uni = sc.build_scan_universes()
        assert uni["fetch"] == ["NASDAQ:AMD", "NYSE:DELL"], uni["fetch"]
        assert uni["pivot30"] == ["NASDAQ:AMD", "NYSE:DELL"]
        assert uni["focus"] == [] and uni["sydney_top50"] == [] and uni["day_monitor"] == []
        assert uni["union"] == [] and called == [], called
        sc.UNIVERSE_EXCLUDE = {"DELL"}
        assert sc.build_scan_universes()["fetch"] == ["NASDAQ:AMD"]
    finally:
        sc.PIVOT_WL_PATH, sc.UNIVERSE_EXCLUDE = old_path, old_excl
        sc.PIVOT_WL_PATHS = old_paths
        sc.load_focus_symbols, sc.load_sydney_top, sc.load_day_monitor = orig


def test_day_monitor_ema_disabled_no_ema_signal():
    """enable_ema_cross=True still yields no EMA 6/20 signal (master flag off)."""
    import scanner as sc
    bars = _session_base()
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 109.5, 107, 109))  # no break
    sigs, _reason = sc.scan_symbol(
        "NASDAQ:TEST", bars=bars, now=t + 300, daily_bars=_D_ATR10,
        enable_ema_cross=True, enable_daily_pullback=True,
        enable_sma30_pullback=True, enable_30m_pivot=False,
    )
    assert all(s.trigger == TRIGGER_30M_PIVOT for s in sigs), [s.trigger for s in sigs]


def test_sync_extract_symbols():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sync_pivot_wl", str(Path(__file__).resolve().parent / "sync_pivot_wl.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    js = '{"symbols": ["NASDAQ:AMD", "NYSE:P", "nyse:s", "NASDAQ:AMD"], "name": "Main"}'
    assert m.extract_symbols(js) == ["NASDAQ:AMD", "NYSE:P", "NYSE:S"]
    assert m.extract_symbols("NYSE:RNG NASDAQ:SPCX,NYSE:DOCN") == [
        "NYSE:RNG", "NASDAQ:SPCX", "NYSE:DOCN"]


def main():
    tests = [
        test_rebuild_30m_colors,
        test_break_fires_once,
        test_three_tiny_reds_below_atr_no_fire,
        test_two_reds_atr_qualified_fires,
        test_gap_down_uses_prior_close,
        test_gap_up_uses_session_open,
        test_reds_must_be_same_session_day,
        test_three_same_day_reds_still_fire,
        test_stop_before_break_no_fire,
        test_rebreak_second_and_third,
        test_rebreak_after_stop_none,
        test_no_late_fire,
        test_fourth_break_capped,
        test_cross_after_three_breaks_still_fires,
        test_cross_while_active,
        test_cross_after_stop_none,
        test_same_bar_break_and_cross,
        test_discord_bucket_not_ema,
        test_discord_two_embeds_main_and_pivot,
        test_discord_only_pivot_one_embed,
        test_discord_pivot_range_aligned,
        test_refine_partial_dedupe,
        test_rs_gate_79_no_alert,
        test_rs_gate_80_alert,
        test_rs_mapping_function,
        test_discord_pivot_shows_rs,
        test_universe_wl_mode_only_wl,
        test_day_monitor_ema_disabled_no_ema_signal,
        test_sync_extract_symbols,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print(f"All {len(tests)} tests passed")


if __name__ == "__main__":
    main()



# --- 2026-10-06 19:11: live = crossback only (ENABLE_30M_PIVOT_BREAK=False) ---
import pytest as _pytest
import scanner as _sc_mod


@_pytest.fixture(autouse=True)
def _break_logic_on_for_legacy_tests(request):
    """Legacy tests exercise break logic; run them with breaks on. Live default is off."""
    if request.node.name.startswith("test_live_"):
        yield
        return
    old = _sc_mod.ENABLE_30M_PIVOT_BREAK
    _sc_mod.ENABLE_30M_PIVOT_BREAK = True
    # Legacy tests were written for gap-ref 0.5×ATR, multi-day pivots, no cross cap.
    legacy = {
        "PIVOT30_DROP_MODE": "gap_ref",
        "PIVOT30_ATR_MULT": 0.5,
        "PIVOT30_SAME_SESSION_ONLY": False,
        "PIVOT30_MAX_CROSSES": None,
    }
    saved = {k: getattr(_sc_mod, k) for k in legacy if hasattr(_sc_mod, k)}
    for k, v in legacy.items():
        if hasattr(_sc_mod, k):
            setattr(_sc_mod, k, v)
    try:
        yield
    finally:
        _sc_mod.ENABLE_30M_PIVOT_BREAK = old
        for k, v in saved.items():
            setattr(_sc_mod, k, v)


def test_live_cross_only_default_off():
    assert _sc_mod.ENABLE_30M_PIVOT_BREAK is False


def test_live_cross_only_break_without_cross_silent():
    bars = _session_base()
    t_break = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t_break, 108, 111, 107, 110.5))
    ind = _ind(t_break, 110.5, ema6=102, ema20=100, prev_ema6=101, prev_ema20=100)
    sig = detect_30m_pivot(
        "NASDAQ:TEST", bars, ind, now=t_break + 300,
        rs_rating=90, min_rs=None, daily_bars=_D_ATR10)
    assert sig is None


# --- 2026-10-06 proposed: high-ref drop ≥0.75×ATR, same-session pivots, 1 cross/pivot ---
import math as _math
from scanner import compute_indicators as _compute_indicators


def _cross_ind(t, price):
    """Synthetic indicators with a fresh EMA6/20 cross + MACD bull on bar t."""
    return _ind(t, price, ema6=101, ema20=100, prev_ema6=99, prev_ema20=100, macd=1, signal=0.5)


def test_live_proposed_defaults():
    assert _sc_mod.PIVOT30_DROP_MODE == "high_ref"
    assert _sc_mod.PIVOT30_ATR_MULT == 0.55
    assert _sc_mod.PIVOT30_SAME_SESSION_ONLY is True
    assert _sc_mod.PIVOT30_MAX_CROSSES == 1
    assert _sc_mod.ENABLE_30M_PIVOT_BREAK is False


def test_live_proposed_small_dip_no_cross():
    """3 tiny reds: high-ref drop ≈0.7 < 0.75×ATR(10) → no cross alert."""
    bars: list[dict] = []
    bars += _fill_30m(_ts(2026, 9, 28, 9, 30), 100.3, 100.4, 100.0, 100.1)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 100.1, 100.2, 99.9, 100.0)
    bars += _fill_30m(_ts(2026, 9, 28, 10, 30), 100.0, 100.1, 99.7, 99.8)
    bars += _fill_30m(_ts(2026, 9, 28, 11, 0), 99.8, 101.0, 99.75, 100.5)  # green
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 100.5, 100.9, 100.2, 100.6))
    daily = _daily_atr(10.0, close=100.0)  # PDH = 105 → would qualify via PDH...
    for b in daily:  # ...so cap prior-day high near the open for this test
        b["h"] = 100.2
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 100.6), now=t + 300, daily_bars=daily)
    assert sig is None


def test_live_proposed_session_high_ref_cross_fires():
    """Session high 121 − min low 105 = 16 ≥ 7.5 (ATR 10) → cross fires, ref session_high."""
    bars = _session_base()
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 109.5, 107, 109))
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 109), now=t + 300, daily_bars=_D_ATR10)
    assert sig is not None and sig.pivot_kind == "cross"
    assert sig.pivot_ref_kind == "session_high" and sig.pivot_ref == 121.0
    assert sig.pivot_drop == 16.0


def test_live_proposed_prior_high_ref():
    """Gap-down: prior close 130 > session high 121 → ref = prior close, drop = 25."""
    bars = _session_base()
    t = _ts(2026, 9, 28, 11, 30)
    bars.append(_5m(t, 108, 109.5, 107, 109))
    daily = _daily_atr(10.0, close=130.0)  # h = 135
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 109), now=t + 300, daily_bars=daily)
    assert sig is not None
    assert sig.pivot_ref_kind == "prior_close" and sig.pivot_ref == 130.0
    assert sig.pivot_drop == 25.0


def test_live_proposed_previous_day_pivot_no_cross():
    """Pivot from Mon 09-28; cross on Tue 09-29 → silent when same-session only."""
    bars = _session_base()
    t = _ts(2026, 9, 29, 9, 30)
    bars.append(_5m(t, 108, 109.5, 107, 109))
    ind = _cross_ind(t, 109)
    assert detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10) is None
    old = _sc_mod.PIVOT30_SAME_SESSION_ONLY
    try:
        _sc_mod.PIVOT30_SAME_SESSION_ONLY = False
        sig = detect_30m_pivot("NASDAQ:TEST", bars, ind, now=t + 300, daily_bars=_D_ATR10)
        assert sig is not None and sig.pivot_kind == "cross"
    finally:
        _sc_mod.PIVOT30_SAME_SESSION_ONLY = old


def _wave_session():
    """Mon 10-05 flat prior day + Tue 10-06: 2 reds, green 10:30, then a sine wave
    of 5m closes that crosses EMA6/20 repeatedly while staying above the pivot low."""
    bars: list[dict] = []
    t0 = _ts(2026, 10, 5, 9, 30)
    for i in range(78):
        c = 100 + 0.3 * _math.sin(i / 3.0)
        bars.append(_5m(t0 + i * 300, c, c + 0.1, c - 0.1, c))
    bars += _fill_30m(_ts(2026, 10, 6, 9, 30), 100.0, 100.2, 97.9, 98.0)   # red
    bars += _fill_30m(_ts(2026, 10, 6, 10, 0), 98.0, 98.1, 95.8, 96.0)     # red
    bars += _fill_30m(_ts(2026, 10, 6, 10, 30), 96.0, 97.8, 95.9, 97.5)    # green (L 95.9)
    ts = _ts(2026, 10, 6, 11, 0)
    prev = 97.5
    for k in range(40):
        # cos phase → 30m buckets alternate green/red (never 2 reds → no new pivot)
        c = 97.0 - 0.8 * _math.cos(2 * _math.pi * k / 12.0)
        bars.append(_5m(ts + k * 300, prev, max(prev, c) + 0.05, min(prev, c) - 0.05, c))
        prev = c
    return bars


def test_live_proposed_cross_count_matches_indicators():
    """_pivot30_prior_cross_count == brute force via compute_indicators per bar."""
    bars = _wave_session()
    green_end = _ts(2026, 10, 6, 11, 0)
    cross_bars = []
    for b in bars:
        t = int(b["t"])
        if t < green_end:
            continue
        ind = _compute_indicators(bars, now=t + 300)
        if ind and ind.prev_ema6 <= ind.prev_ema20 and ind.ema6 > ind.ema20 and ind.macd > ind.signal:
            cross_bars.append(t)
    assert len(cross_bars) >= 2, cross_bars
    last = int(bars[-1]["t"])
    expect = sum(1 for t in cross_bars if t < last)
    assert _sc_mod._pivot30_prior_cross_count(
        closed_rth_5m(bars, now=last + 300), green_end, last) == expect


def test_live_proposed_second_cross_capped():
    """First crossback after the green alerts; the second is capped (MAX_CROSSES=1)."""
    bars = _wave_session()
    green_end = _ts(2026, 10, 6, 11, 0)
    daily = _daily_atr(2.0, last_day=(2026, 10, 2), close=100.0)
    crosses = []
    for b in bars:
        t = int(b["t"])
        if t < green_end:
            continue
        ind = _compute_indicators(bars, now=t + 300)
        if ind and ind.prev_ema6 <= ind.prev_ema20 and ind.ema6 > ind.ema20 and ind.macd > ind.signal:
            crosses.append((t, ind))
    assert len(crosses) >= 2
    (t1, i1), (t2, i2) = crosses[0], crosses[1]
    upto1 = [b for b in bars if int(b["t"]) <= t1]
    upto2 = [b for b in bars if int(b["t"]) <= t2]
    s1 = detect_30m_pivot("NASDAQ:TEST", upto1, i1, now=t1 + 300, daily_bars=daily)
    assert s1 is not None and s1.pivot_kind == "cross" and s1.pivot_low == 95.9
    assert detect_30m_pivot("NASDAQ:TEST", upto2, i2, now=t2 + 300, daily_bars=daily) is None
    old = _sc_mod.PIVOT30_MAX_CROSSES
    try:
        _sc_mod.PIVOT30_MAX_CROSSES = None
        s2 = detect_30m_pivot("NASDAQ:TEST", upto2, i2, now=t2 + 300, daily_bars=daily)
        assert s2 is not None and s2.pivot_kind == "cross"
    finally:
        _sc_mod.PIVOT30_MAX_CROSSES = old


def _one_red_session():
    bars = _fill_30m(_ts(2026, 9, 28, 9, 30), 95.0, 95.5, 85.0, 86.0)    # red
    bars += _fill_30m(_ts(2026, 9, 28, 10, 0), 86.0, 88.0, 85.5, 87.5)  # green
    t = _ts(2026, 9, 28, 10, 30)
    bars.append(_5m(t, 87.5, 87.9, 87.0, 87.8))
    return bars, t


def test_live_gap_down_one_red_fires():
    """Gap down (open 95 < prior close 100): 1 red + green qualifies; ref = prior close."""
    import scanner
    assert scanner.PIVOT30_GAP_DOWN_COUNTS_AS_RED is True
    bars, t = _one_red_session()
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 87.8), now=t + 300,
                           daily_bars=_daily_atr(10.0, close=100.0))
    assert sig is not None and sig.pivot_kind == "cross"
    assert sig.pivot_ref_kind == "prior_close" and sig.pivot_ref == 100.0
    assert sig.pivot_drop == 15.0


def test_live_no_gap_one_red_no_alert():
    """No gap down (open 95 > prior close 94): 1 red is not enough (drop 10.5 ≥ 7 though)."""
    bars, t = _one_red_session()
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 87.8), now=t + 300,
                           daily_bars=_daily_atr(10.0, close=94.0))
    assert sig is None


def test_live_gap_down_flag_off_one_red_no_alert(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, "PIVOT30_GAP_DOWN_COUNTS_AS_RED", False)
    bars, t = _one_red_session()
    sig = detect_30m_pivot("NASDAQ:TEST", bars, _cross_ind(t, 87.8), now=t + 300,
                           daily_bars=_daily_atr(10.0, close=100.0))
    assert sig is None
