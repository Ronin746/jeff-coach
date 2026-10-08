# Verify Yahoo cache bars vs alerts

Date: 2026-09-29. Cache files contain raw OHLCV only (`t`, `o`, `h`, `l`, `c`, `v`); indicators are not stored and were recomputed with `/workspace/tv-scanner/scanner.py`. Timestamps below are bar **open** times.

## Unix timestamp decoding

- `1790689800` → 2026-09-29 09:50:00 EDT / 2026-09-29 15:50:00 CEST.
- `1790691000` (the `last_routine_report.json` `bar_t`) → 2026-09-29 10:10:00 EDT / 2026-09-29 16:10:00 CEST.

## Exact alert bars and neighboring 5m bars

Each row is the previous, target, or next 5m bar around the alert bar. OHLCV values are copied from the cache JSON.

| Symbol | Alert | Position | Unix `t` | ET | Rome | O | H | L | C | V |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| NASDAQ:FORM |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 134.690002 | 135.345001 | 134.470001 | 134.580002 | 17543 |
| NASDAQ:FORM | Trigger A | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 134.500000 | 135.490005 | 134.500000 | 135.074997 | 24089 |
| NASDAQ:FORM |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 135.089996 | 135.660004 | 135.089996 | 135.449997 | 18503 |
| NASDAQ:PENG |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 55.520000 | 55.520000 | 55.169998 | 55.169998 | 2935 |
| NASDAQ:PENG | Trigger A | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 55.250000 | 55.810001 | 55.145000 | 55.810001 | 9741 |
| NASDAQ:PENG |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 55.825001 | 56.316898 | 55.595001 | 55.595001 | 18745 |
| NYSE:BFLY |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 9.630000 | 9.789900 | 9.630000 | 9.706000 | 68732 |
| NYSE:BFLY | Trigger A (cache exchange) | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 9.702500 | 9.785000 | 9.690100 | 9.755000 | 48330 |
| NYSE:BFLY |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 9.756000 | 9.830000 | 9.544300 | 9.570000 | 236184 |
| NASDAQ:SIMO |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 276.065002 | 277.079987 | 276.065002 | 277.079987 | 3391 |
| NASDAQ:SIMO | Trigger A + B | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 278.000000 | 280.500000 | 277.859985 | 279.755005 | 7405 |
| NASDAQ:SIMO |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 280.548798 | 282.520599 | 280.548798 | 281.378998 | 12542 |
| NASDAQ:CAKE |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 106.934998 | 106.945000 | 106.309998 | 106.724998 | 11457 |
| NASDAQ:CAKE | Trigger A | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 106.720001 | 106.760002 | 106.330002 | 106.750000 | 8189 |
| NASDAQ:CAKE |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 106.750000 | 107.199997 | 106.650002 | 106.941399 | 119805 |
| NYSE:ASX |  | −1 | 1790689500 | 2026-09-29 09:45:00 EDT | 2026-09-29 15:45:00 CEST | 43.945000 | 44.119999 | 43.900002 | 43.970001 | 87799 |
| NYSE:ASX | Trigger B | target | 1790689800 | 2026-09-29 09:50:00 EDT | 2026-09-29 15:50:00 CEST | 44.014999 | 44.230000 | 44.009998 | 44.171001 | 88014 |
| NYSE:ASX |  | +1 | 1790690100 | 2026-09-29 09:55:00 EDT | 2026-09-29 15:55:00 CEST | 44.189999 | 44.418598 | 44.185001 | 44.369999 | 140781 |
| NASDAQ:MRVL |  | −1 | 1790690700 | 2026-09-29 10:05:00 EDT | 2026-09-29 16:05:00 CEST | 260.929993 | 261.219910 | 259.790009 | 260.079987 | 199021 |
| NASDAQ:MRVL | Trigger A | target | 1790691000 | 2026-09-29 10:10:00 EDT | 2026-09-29 16:10:00 CEST | 260.149994 | 260.734192 | 258.899994 | 260.484985 | 280120 |
| NASDAQ:MRVL |  | +1 | 1790691300 | 2026-09-29 10:15:00 EDT | 2026-09-29 16:15:00 CEST | 260.380005 | 260.450012 | 259.500000 | 259.500000 | 35555 |
| NASDAQ:AEHR |  | −1 | 1790690700 | 2026-09-29 10:05:00 EDT | 2026-09-29 16:05:00 CEST | 104.584999 | 105.169899 | 103.599998 | 103.650002 | 46546 |
| NASDAQ:AEHR | Trigger A | target | 1790691000 | 2026-09-29 10:10:00 EDT | 2026-09-29 16:10:00 CEST | 103.745003 | 104.809898 | 103.290001 | 104.559998 | 30359 |
| NASDAQ:AEHR |  | +1 | 1790691300 | 2026-09-29 10:15:00 EDT | 2026-09-29 16:15:00 CEST | 104.239998 | 104.510002 | 104.099998 | 104.099998 | 2898 |

## Helper recomputation at the 09:50 ET target bar

> **EMA6 update (2026-09-29):** scanner now uses price **EMA6/EMA20** (`EMA_FAST=6`), matching the chart. Rows below were computed under the previous EMA5 lead; re-run dry recompute for current A/B.


`compute_indicators()` was evaluated on each cache series through the target bar, with `detect_triggers()` (including the scanner trend filter `price > SMA30(65m)`). EMA5 is the scanner helper field named `ema6` for historical compatibility; MACD is the line `EMA6 − EMA20` (not the signal line).

| Symbol | Close | Session VWAP | EMA5 | EMA20 | MACD 6/20 | SMA30 65m | Trigger A | Trigger B |
|---|---:|---:|---:|---:|---:|---:|---|---|
| NASDAQ:FORM | 135.074997 | 134.902391 | 134.364912 | 132.154215 | 1.967779 | 127.634668 | True | False |
| NYSE:ASX | 44.171001 | 43.871829 | 43.958888 | 43.903375 | 0.037681 | 43.971916 | False | True |

- FORM: Trigger A true (VWAP cross + MACD > 0); Trigger B false.
- ASX: Trigger A false; Trigger B true (EMA5/20 cross + MACD > 0).
- The cache filename is `NYSE_BFLY.json` and its embedded symbol is `NYSE:BFLY`; that is the exchange used above despite the shorthand grouping in the alert description.


## Update 2026-09-29 evening — RTH-only indicator series

`compute_indicators()` now builds EMA6/EMA20/MACD/Session VWAP on **closed RTH-only**
5m bars (`closed_rth_5m`), not all closed bars. With current `prepost=False` caches the
numeric FORM/ASX rows above are unchanged; the fix prevents AH pollution if extended
bars ever appear. Recompute: `python verify_indicators.py`. Yahoo≠TV OHLC caveat: §5b in
`backup/SCANNER_PROMPT_IT.md`.
