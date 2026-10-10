# Remy RTH LONG rules (updated 2026-10-06, Europe/Rome)

## Live alert mode (Ronin 2026-10-06 11:12)

**Only alert:** **30m pivot** (break + cross, rules in §6) on **TradingView
watchlist 323848747 "Main"** — and nothing else.
**Universe:** `UNIVERSE_MODE = "wl323848747"` → `pivot_wl_323848747.txt`
(97 names at sync 2026-10-06; WL is read-only shared — **never modify it on
TV**). Focus `symbols.txt`/`watchlist.json` (318147906), Sydney top 50,
`day_monitor.txt` and `pivot30_list.txt` are **not read** in this mode (files
kept; `UNIVERSE_MODE = "legacy"` restores the old union).
**Suspended (code kept, flags off):** day_monitor EMA 6/20 extras
(`ENABLE_DAY_MONITOR_EMA = False`), Daily EMA 9/21 pullback
(`ENABLE_DAILY_EMA_PULLBACK = False`), 5 MA Daily / SMA30 65m pullback
(`ENABLE_SMA30_PULLBACK = False`), VWAP (`ENABLE_VWAP_CROSS = False`).
Discord: only the separate `30 minute pivot` embed is posted (main embed has
no sections → omitted). ETFs are never scanned (user cannot trade ETFs).

## Triggers

1. **EMA 6/20 cross (+ MACD)** — **SUSPENDED 2026-10-06**
   (`ENABLE_DAY_MONITOR_EMA = False`; day_monitor.txt not read in wl mode).
   Spec retained for re-enable:
   - File: `/workspace/tv-scanner/day_monitor.txt`
   - Valid only for the stamped Rome calendar day; empty/expired = no alerts.
   - Gate: EMA6 crosses above EMA20 on last closed 5m + MACD line > signal.
   - **No** SMA30 filter on day-monitor extras (they fire regardless of trend vs SMA30).
   - Set: `printf 'date: %s\nNASDAQ:AMD\nNVDA\n' "$(TZ=Europe/Rome date +%F)" > day_monitor.txt`

2. **Daily EMA pullback** — **SUSPENDED** (`ENABLE_DAILY_EMA_PULLBACK = False`)
   — EMA9 + EMA21 only (EMA50 dropped); flip flag True to restore.
   - ARM only when that RTH session opened strictly above the specific EMA
     (`session_open > EMA`), then sticky ≤1% from above or session cross-down
     through that daily EMA.
   - FIRE later same session: EMA6 crosses above EMA20 + MACD bull.
   - **5 MA priority:** when `SMA30(65m) < Daily EMA9`, skip EMA9 for that
     ticker. EMA21 remains eligible as before unless the 5 MA pullback is also
     armed that session; when both are relevant, consider/alert only 5 MA.
   - Discord: first fire only per ticker + EMA (EMA9/EMA21) for the Rome calendar day.
   - Universe: Focus WL ∪ Sydney ranked **top 50**.

3. **SMA30 65m pullback ≤ 2%** — **SUSPENDED** (`ENABLE_SMA30_PULLBACK = False`);
   flip flag True to restore. Spec below retained for re-enable:
   - `sma30` = mean of last 30 complete 65m closes (from RTH 5m buckets).
   - ARM only when the RTH session open is strictly above SMA30
     (`session_open > sma30`), then sticky when
     `|price - sma30| / sma30 <= 0.02` (within 2%, either side).
   - FIRE later same session: EMA6 > EMA20 cross + MACD bull.
   - Discord: first fire only per ticker + SMA30 setup for the Rome calendar day.
   - **Not** the old hard filter `price > SMA30`.
   - Same universe: Focus ∪ Sydney top 50.
   - This is Remy’s **5 MA Daily** setup. If it is armed while below Daily
     EMA9, it has priority over both Daily EMA alerts for that ticker.

4. **MA math / source (TradingView ribbon parity)**
   - All MAs use `source=close`; do not substitute ribbon periods 20/50/100/200.
   - Daily: EMA9 and EMA21 via `ta.ema(close, length)`.
   - 5 MA Daily: SMA30 on complete reconstructed 65m closes via
     `ta.sma(close, 30)`.
   - Intraday: EMA6/EMA20 on closed RTH 5m closes; MACD is EMA6 − EMA20
     with signal EMA9 (`6/20/9`). EMA uses Pine’s first-close seed and
     `alpha=2/(length+1)`; SMA is the rolling mean of the last `length` closes.

5. **VWAP cross** — suspended (`ENABLE_VWAP_CROSS = False`).

6. **30m pivot** — `ENABLE_30M_PIVOT = True`
   - Build 30-minute RTH candles from the cached 5m RTH bars (`prepost=False`),
     anchored to 09:30 ET (09:30–10:00, 10:00–10:30, … 15:30–16:00). Only
     completed 30m candles count. Multi-day history from the 10d 5m cache.
   - Red = close < open; green = close > open.
   - Pattern: at least `PIVOT30_MIN_REDS` (2) consecutive red 30m candles **on
     the same US/Eastern session day**, immediately followed by the FIRST green
     30m that same day. Prior-day / weekend reds do not count.
   - **ATR size gate (Ronin):** drop is measured from a daily reference down to
     the **min low** of same-day 30m bars from session open through the reds
     before the green. Reference:
       - if today's RTH open < prior-day close (**gap down**) → prior-day close
       - if today's RTH open ≥ prior-day close (**gap up / flat**) → today's
         RTH open
     Prior close = last closed daily before that session (fallback: last RTH
     5m close of the prior session). Qualify if drop ≥ `PIVOT30_ATR_MULT`
     (0.5) × daily ATR(14) (Wilder/RMA on closed dailies; today's forming
     excluded). Missing ATR/ref → no pivot alert.
   - That green candle's high = pivot trigger; its low = pivot stop. Pivot is
     ACTIVE until stop is hit. Signal may carry `pivot_drop` / `pivot_atr` /
     `pivot_ref` / `pivot_ref_kind` (`gap_down`|`gap_up`) (info; Discord text
     unchanged).
   - While ACTIVE, fire on the most recent closed 5m for either:
     - **break:** 5m high > pivot high (intrabar; do not wait for 30m close).
       Report price = that 5m close. Re-breaks: after any break alert, if a
       closed 5m closes back below pivot high without trading below pivot low,
       a later 5m high > pivot high fires again (n = 2, 3). **Max 3 break
       alerts per pivot** (1st, 2°, 3°); no further breaks after the 3rd.
       A `break + cross` row counts as a break toward the cap. Cross alerts
       while the pivot is still active are **not** capped by this limit.
     - **cross:** EMA6 crosses above EMA20 on last closed 5m + MACD 6/20/9
       line > signal (same gate as day-monitor EMA 6/20). No day_monitor
       requirement, no SMA30 gate. Applies to the full scan universe.
     - Same bar with both → one row, `pivot_kind = break + cross`.
   - Invalidation: if price trades below the green candle's low at any point,
     the pivot is dead (no further break or cross alerts). A later new ATR-
     qualified red run + first green creates a new pivot. Only the most recent
     valid pivot per symbol matters for live detection.
   - Only fire on the most recent closed 5m (no late-fire on earlier bars).
   - Dedupe (`signal_state.json`):
     - break / re-break: ticker + green_t + alert number n
     - cross: ticker + green_t + cross bar_t
   - Discord: **own embed** (not a section of the main Remy embed).
     Title exactly `30 minute pivot • HH:MM Close` (HH:MM = 5m close Rome).
     Color `#5DADE2`; plain text body = aligned rows only (no `• 30m pivot:`
     header, no ANSI, no fence, no content field, no mentions).
     Row: `TICKER  @ price  [ (n°)]  kind  H x.xx / L y.yy  RS nn` where kind is
     `break` / `cross` / `break + cross`. Payload embeds = `[main, pivot]`
     when both exist; only one embed when only one type fires.
   - Break has no MACD/SMA/EMA gate. Cross uses EMA6/20 + MACD only.
     EMA 8 and EMA 40 on 30m closes (Pine `ta.ema`) are info in logs /
     `last_signals.md` only — not Discord filters.
   - **RS Rating gate (Ronin):** both break and cross require Fred6724
     RS Rating: **no gate since 2026-10-06** (`RS_MIN_30M_PIVOT = None`, Ronin: non escludere nulla per RS dalla watchlist); RS shown as info only, missing RS still allowed. Computed once per scan per symbol
     from daily closes vs Yahoo `^GSPC` (Pine `SP:SPX`), using the last
     **completed** daily close (today's forming bar is excluded while RTH is
     open — RS is a daily measure). Missing/insufficient daily data → no
     pivot alert (logged). Embed row ends with `RS n`
     (`… H x / L y  RS 92`). Thresholds: 7 score cutoffs at percentiles
     98/89/69/49/29/9/1 = Pine replay defaults, local only (Ronin
     2026-10-05: no RSRATING.csv / rs_stocks.csv download); written to
     `cache/rs_thresholds.json`. Names with too little daily history for RS
     (e.g. recent IPOs) → RS None → no pivot alert until history suffices.
   - Universe: TV WL 323848747 only (`pivot_wl_323848747.txt`).

## Universe sources

**Live (`UNIVERSE_MODE = "wl323848747"`):**
- `/workspace/tv-scanner/pivot_wl_323848747.txt` — one `EXCHANGE:TICKER` per
  line; `#` lines ignored (ETFs are written as `# EXCLUDED_ETF …`).
  `UNIVERSE_EXCLUDE` in scanner.py = manual ticker override list.
- Same list is the yfinance fetch set (5m/10d + 1d/2y) and the scan set.

**Re-sync the watchlist** (WL changes on TV → local file; never write to TV):
1. Fetch WL 323848747 via TradingView MCP (`mcp-watchlist-get-watchlist`,
   read-only) and save the raw output (text or JSON) e.g. to
   `mcp_inbox/wl_323848747.json`.
2. `cd /workspace/tv-scanner && .venv/bin/python sync_pivot_wl.py --from-file mcp_inbox/wl_323848747.json`
   (or pass symbols as args / via stdin; `--dry-run` to preview).
   It extracts all `EXCHANGE:TICKER`, checks yfinance `quoteType` (non-EQUITY
   → commented out as ETF) and 5m/daily data, backs up the old file
   (`.bak_YYYYmmdd_HHMMSS`), writes the new one and prints added/removed/ETF/no-data.
3. Next loop run picks it up (scanner re-imports each scan); verify with
   `.venv/bin/python scanner.py --print-universes`.

**Legacy (`UNIVERSE_MODE = "legacy"`, not live):**
- Focus: `watchlist.json` / `symbols.txt` (TV id `318147906`)
- Sydney top 50: `/workspace/sydney-scanner/watchlist_ranked.json` → first 50 by rank
- day_monitor.txt (EMA 6/20 extras) and pivot30_list.txt (pivot-only extras)

## Daily/5-MA precedence summary

For each ticker on each scan: first compare Daily EMA9 (forming-today
included, TV-aligned) with the 65m SMA30. If `SMA30 < EMA9`, EMA9 is ineligible.
If the SMA30 pullback is armed (`session_open > SMA30` and within the 2% band),
SMA30 is the sole pullback setup considered; otherwise EMA21 may still fire as
normal. Same-day dedupe remains unchanged (one fire per ticker/setup/Rome day).

## Discord

- Main embed title: `🦅 HH:MM Close` (embed title, not inside a code block)
- Plain text body, no ANSI and no ``` fence, so the push notification matches the opened message
- Light-blue border `#5DADE2`; main sections only when non-empty: Ema 6/20 →
  (Vwap if on) → Daily EMA9/21 → `5 MA Daily`. Live (all off) → main embed
  never posted; only the 30m pivot embed.
- 30m pivot: **separate** embed, title `30 minute pivot • HH:MM Close`; body = rows only
- Payload: `[main, pivot]` when both; single embed when only one type
- Remy webhook only (does not touch Sydney Discord)

## Dry-run

```bash
cd /workspace/tv-scanner
.venv/bin/python scanner.py --print-universes
.venv/bin/python scanner.py --dry-run          # warm cache; no Discord
.venv/bin/python refresh_yfinance.py --scan --dry-run
```

## 30m pivot extra list (Dua Focus+Stalk RS 80+) — LEGACY, not read in wl mode

- File: `/workspace/tv-scanner/pivot30_list.txt`, same format as day_monitor (`date: YYYY-MM-DD`, one ticker per line); expires next Rome day.
- Names there get **only** the 30m pivot (break/cross, RS ≥ 80 gate still applies). No generic EMA 6/20, no Daily EMA / 5 MA pullbacks unless they are already in Focus ∪ Sydney top 50.
- Bare tickers are mapped onto the existing universe symbol (e.g. `MRVL` → `NASDAQ:MRVL`) so a name is scanned once. Same mapping for day_monitor.
- Dua sends the list after the morning comparison.

## 2026-10-06 13:36 — Universe = TWO watchlists (Ronin: "fai entrambe")
- `pivot_wl_323848747.txt` (TV WL 323848747 "Main", 97) **+** `pivot_wl_318147906.txt` (TV WL 318147906 "Focus", 15 at sync; `###TRACKING` header skipped).
- Union deduped by ticker → 108 symbols. `PIVOT_WL_PATHS` in scanner.py. Both WLs read-only on TV; re-sync via TradingView MCP into the files.
- Alerts: 30m pivot only (break + crossback), no RS gate.

## 30M PIVOT — filtro qualità (dal 2026-10-09, Ronin)

Backtest su 58 sedute (21/07–09/10/2026), 362 titoli con RS ≥ 80 il giorno del segnale (WL di Remy + universo
Jeff Coach), ~9.000 crossback EMA6/20 + MACD sui 5m. Esito: ingresso al close della 5m del segnale, stop sotto il
minimo del pivot, conta se arriva prima +2R o lo stop (entro la seduta dopo). Script: `backtest/pivot30_backtest.py`.

- Regola vecchia: ~56 segnali al giorno sulle WL di Remy, risultato atteso +0,12R a segnale, stop prima di 1R ~50%.
- Nessun singolo fattore (livelli daily, VWAP, ora, volume, mercato) separa bene; un modello statistico non
  generalizza. Regge in tutti e tre i periodi provati la combinazione qui sotto:
  - **almeno 3 candele 30m rosse** prima del pivot (`PIVOT30_MIN_REDS = 3`, era 2; il gap down conta ancora come una);
  - **filtro qualità** (`PIVOT30_QUALITY = True`), tutto in ATR(14) daily:
    - close di ieri non oltre 4 ATR sopra la SMA50 (`PIVOT30_MAX_EXT50_ATR`);
    - discesa prima del pivot ≤ 1,5 ATR (`PIVOT30_MAX_DROP_ATR`);
    - rischio = prezzo del segnale − minimo del pivot ≤ 0,3 ATR (`PIVOT30_MAX_RISK_ATR`);
    - apertura non sotto la chiusura di ieri di oltre 0,5 ATR (`PIVOT30_MIN_GAP_ATR`);
    - minimo del pivot non oltre 1 ATR sotto la chiusura di ieri e non oltre 1 ATR sotto la EMA21 a 30m.
- Con il filtro: ~12 segnali al giorno sulle WL di Remy, risultato atteso +0,26R a segnale (per periodo:
  +0,20 / +0,16 / +0,35 contro +0,13 / +0,07 / +0,15). Gli esempi di @1ChartMaster (LITE 28/09, MRVL 28/09,
  STX 28–29/09) restano segnalati.
- Ingresso sulla rottura del massimo del pivot invece del crossback: risultati simili (+0,28R con il filtro).
  Resta il crossback, come deciso il 06/10.

## 30M PIVOT — solo tre versioni (Ronin 09/10)

Remy manda un pivot (crossback EMA6/20 + MACD sui 5m, filtro qualità del 09/10) **solo** se è di una di
queste versioni; la versione è nel titolo dell'embed (`30 minute pivot · <versione> • HH:MM Close`),
un embed per versione. Se un pivot rientra in più versioni vale la prima.

| Versione | Regola (daily fino a ieri) |
|---|---|
| `DTL break + EMA9` | trendline discendente daily rotta da <=10 sedute con volume >= 1,5x (o conferma entro 3 giorni), close non oltre 1 ATR sotto la linea, e minimo del pivot a ±0,25 ATR dalla EMA9 daily in salita |
| `DTL break 5d` | trendline rotta da <=5 sedute con volume, non fallita |
| `EMA9 undercut` | minimo del pivot tra −0,25 e 0 ATR sotto la EMA9 daily in salita (buca appena e richiude sopra) |

Estensione massima dalla SMA50 portata da 4 a **5,5 ATR** (`PIVOT30_MAX_EXT50_ATR`): su 3 anni di 60m i segnali
tra 4 e 5,5 ATR rendono come gli altri. Spegnere le versioni: `PIVOT30_VERSIONS_ONLY = False`.

Backtest (tenuta swing, stop fisso al minimo del pivot): 5m 58 sedute, 5 sedute, 7R/10R —
V1 +2,0/+2,1R (14 segnali), V2 +0,35/+0,61 (54), V3 +0,68/+0,82 (152). Su 3 anni di 60m (ingresso sulla
rottura del massimo del pivot), 10 sedute: V1 +0,51/+0,65 (136), V2 +0,34/+0,40 (563), V3 +0,23/+0,24 (1819).
Script: `backtest/pivot30_livelli_target.py`, `backtest/pivot_rottura_swing.py`.

### Titoli in più oltre le watchlist
`universo_auto.py` (lanciato da avvia.py con il sync delle 15:00 di Roma; il turno B in cloud lo fa all'avvio
se manca) scrive `pivot_wl_auto.txt` con `date: AAAA-MM-GG`: azioni USA mcap > 1 mld, adv$ (media 50 giorni
di volume × close) >= 50M, RS >= 80, non oltre 5,5 ATR sopra la SMA50, e candidate a una versione (trendline
rotta <=10 giorni con volume, oppure EMA9 in salita con il close non oltre 3 ATR sopra). Lo scanner lo legge
solo nella seduta di quella data. Le daily dei titoli si scaricano una volta al giorno (cache del giorno).
