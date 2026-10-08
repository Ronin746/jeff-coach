# Option B ready — box cron RTH scan

Parent action required:

1. **Pause / disable** Grok Bot routine `rth-5m-long-scan` so it does **not**
   double-fire alongside the box crontab (Discord would still dedupe NEW keys,
   but you would burn agent wake + duplicate work every 5m).
2. **Keep** the Sync watchlist routine (cron does not refresh the symbol list).
3. **Chat alerts** will **not** auto-forward to the agent chat unless the parent
   adds a light poller on `last_scan_summary.json` / `last_signals.md`.
   **Discord is primary** — posts come from Python alone via the existing
   webhook path (unchanged; never print the URL).

## What was installed

| Item | Path / value |
|------|----------------|
| Wrapper | `/workspace/tv-scanner/cron_rth_scan.sh` |
| Log | `/tmp/tv-scanner-rth.log` |
| Command | `.venv/bin/python refresh_yfinance.py --scan` |
| Window | Mon–Fri 15:10–21:55 Europe/Rome (wrapper gate) |
| Crontab | `CRON_TZ=Europe/Rome` + minutes `0,5,…,55` hours `15-21` dow `1-5` |

Crontab line:

```cron
0,5,10,15,20,25,30,35,40,45,50,55 15-21 * * 1-5 /workspace/tv-scanner/cron_rth_scan.sh
```

Docs: `FAST_PATH.md` § Option B — box cron.
