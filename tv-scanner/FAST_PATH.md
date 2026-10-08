# Fast path — RTH refresh + scan (one process)

## Preferred command

```bash
cd /workspace/tv-scanner && .venv/bin/python refresh_yfinance.py --scan
```

Single Python process: parallel Yahoo download (`prepost=False`) → write `cache/` →
`scanner.scan_all` on **in-memory** bars → Discord **only** on NEW signals
(`symbol|trigger|bar_t` dedup). No TradingView browser. No multi-step agent chain.

## Measured wall time (this box)

| Run | When (Rome) | Symbols | Fetch | Scan | **Total wall** |
|-----|-------------|---------|-------|------|----------------|
| Full refresh+scan | 2026-09-29 ~18:12 CEST | 88/88 ok | 3.828 s | 0.613 s | **~4.6 s** (`WALL_SEC=4.573`) |

Re-measure anytime:

```bash
.venv/bin/python -c "import time,subprocess,sys; t=time.perf_counter();
subprocess.run([sys.executable,'refresh_yfinance.py','--scan']);
print(f'WALL_SEC={time.perf_counter()-t:.3f}')"
```

Scan-only (warm cache) is sub-second to ~1 s via `run_scan.py`, but the routine
should prefer `--scan` so bars are fresh.

## Parent / routine prompt suggestion

Prefer this **low-effort** path every RTH tick:

1. Run `refresh_yfinance.py --scan` immediately (shell, one shot).
2. Discord is handled inside the script (silence if zero NEW).
3. Handoff to the parent agent **only if** `scan_new` is non-empty (read
   `last_scan_summary.json` / stdout) — do **not** chain MCP TV browser,
   multi-agent verify, or separate fetch→scan→notify steps for the happy path.

Do **not** resume/pause cron routines from this doc; parent owns install.

## Indicator correctness (pre-req for trusting speed)

- 5m VWAP / EMA6 / EMA20 / MACD use **RTH-only** closed bars (AH never seeds MAs).
- Session VWAP resets 09:30 ET; typical `(H+L+C)/3` × volume.
- Crosses on last **closed** RTH 5m only; 65m SMA30 stays categorical RTH buckets.
- Yahoo OHLC can ≠ TV Cboe → occasional false vs chart accepted; see
  `backup/SCANNER_PROMPT_IT.md` §5b and `verify_indicators.py`.

## Option B — box cron

Run the fast path on a **user crontab** so Discord posts from Python alone —
no Grok Bot RTH wake every 5m.

### Wrapper

`/workspace/tv-scanner/cron_rth_scan.sh`

- `cd /workspace/tv-scanner`
- `.venv/bin/python refresh_yfinance.py --scan`
- Appends stdout/stderr to `/tmp/tv-scanner-rth.log` with Rome timestamps
- Gates Mon–Fri **15:10–21:55** `Europe/Rome` (skips otherwise, exit 0)
- Always exits **0** (even if scan finds zero NEW / soft errors)

### Crontab (installed)

```cron
CRON_TZ=Europe/Rome
# tv-scanner Option B: RTH every 5m; wrapper gates 15:10–21:55 Rome weekdays
0,5,10,15,20,25,30,35,40,45,50,55 15-21 * * 1-5 /workspace/tv-scanner/cron_rth_scan.sh
```

Verify: `crontab -l`

### Ops notes

- **Pause/disable** Grok routine `rth-5m-long-scan` so it does not double-fire with cron.
- Keep the Sync watchlist routine.
- Chat alerts will **not** auto-forward unless the parent adds a light poller;
  **Discord is primary** (webhook path unchanged; do not log/print the URL).
- Manual one-shot: `/workspace/tv-scanner/cron_rth_scan.sh`
- See also `OPTION_B_READY.md`.


## Rules note (2026-09-30)

See `RULES_RTH_LONG.md`. Summary:

- Generic Focus EMA6/20 **suspended** → `day_monitor.txt` (Rome day) only.
- Daily EMA pullback: **EMA9 + EMA21** (EMA50 dropped), only after session open > the specific EMA.
- **SMA30 65m ≤2%** pullback arm/fire on Focus ∪ Sydney top 50, only after session open > SMA30 (not hard `price>SMA30` thereafter).
- VWAP still suspended. Discord title `🦅 HH:MM Close` unchanged.
