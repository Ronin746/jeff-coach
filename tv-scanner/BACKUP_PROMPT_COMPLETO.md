# BACKUP COMPLETO — Scanner Remy (tv-scanner) — stato live al 2026-10-08

> Questo file è la **fonte di verità** per ripristinare lo scanner.
> Se qualcosa negli altri .md (es. `RULES_RTH_LONG.md`, `FAST_PATH.md`) è in conflitto
> con questo file, **vale questo file** (gli altri contengono anche storia vecchia).
>
> ⚠️ **Il webhook Discord di Remy è un SEGRETO e NON è in questo archivio.**
> Non scriverlo mai in file, chat, log o commit. Al ripristino va chiesto all'utente
> con un **input segreto mascherato** (vedi §6).

---

## 1. Cosa fa, in una frase

Ogni 5 minuti durante la sessione USA, lo scanner scarica i dati da yfinance per i titoli
delle due watchlist TradingView di Ronin e manda su Discord (canale Remy) **solo** un tipo
di alert: il **crossback sul pivot a 30 minuti** (30m pivot crossback).

Nient'altro: niente break del massimo del pivot, niente Daily EMA, niente 5MA/SMA30,
niente VWAP, niente extra del day_monitor.

---

## 2. Universo (quali titoli)

| Watchlist TradingView | ID | File locale | Simboli (08-10) |
|---|---|---|---|
| **Main** | 323848747 | `pivot_wl_323848747.txt` | 97 |
| **Focus** | 318147906 | `pivot_wl_318147906.txt` | 65 |

- Universo = unione delle due liste (≈132 titoli unici), **ETF esclusi**
  (scritti come righe `# EXCLUDED_ETF ...`, lo scanner li ignora).
- Entrambe le watchlist sono **condivise in sola lettura su TradingView:
  NON modificarle MAI su TradingView.** Si aggiornano solo i file locali.
- **Sync giornaliero alle 15:00 Rome** (routine dell'agente, non cron del box):
  legge le watchlist TV e riscrive i file locali con `sync_pivot_wl.py`
  (fa un backup del file precedente e controlla gli ETF con yfinance).
  ```bash
  cd /workspace/tv-scanner
  .venv/bin/python sync_pivot_wl.py --from-file <dump_watchlist.json>             # Main
  .venv/bin/python sync_pivot_wl.py --from-file <dump.json> --out pivot_wl_318147906.txt  # Focus
  ```
- In `scanner.py`: `UNIVERSE_MODE = "wl323848747"`,
  `PIVOT_WL_PATHS = [pivot_wl_323848747.txt, pivot_wl_318147906.txt]`.
- `symbols.txt` / `watchlist.json` = copia Focus (legacy, tenuti per compatibilità).
  `pivot30_list.txt`, `day_monitor.txt` = **non usati** in questa modalità.

---

## 3. Regole dell'alert (30m pivot crossback)

**Barre**
1. Barre **30 minuti RTH** ricostruite dalle 5m, ancorate alle **09:30 ET**
   (09:30, 10:00, … 15:30 ET). Rossa = close < open, verde = close > open.
2. Solo barre della **stessa sessione** (stesso giorno ET).

**Pivot**
3. Servono **≥ 2 rosse consecutive** della stessa sessione, poi la **prima verde**.
4. **Gap down conta come una rossa**: se l'apertura RTH < chiusura del giorno prima,
   basta **1 rossa** prima della verde.
5. Pivot = la verde: **massimo verde = trigger**, **minimo verde = stop**.

**Ampiezza del pullback (filtro ATR)**
6. Riferimento (ref):
   - senza gap down → **massimo di sessione prima delle rosse** (fino alla verde esclusa);
   - con gap down → **max(chiusura giorno prima, massimo di sessione)**.
   - Il massimo del giorno prima **NON** si usa più.
7. drop = ref − minimo più basso prima della verde.
8. Deve valere **drop ≥ 0.55 × ATR14 giornaliero** (Wilder/RMA sulle daily chiuse;
   la daily di oggi in formazione è esclusa). ATR o ref mancanti → nessun alert.

**Quando parte l'alert (crossback)**
9. Sulla **5m appena chiusa**: **EMA6 incrocia sopra EMA20** **e** linea **MACD(6,20,9) > signal**.
10. Il pivot deve essere **ancora valido**: se una 5m dopo la verde va **sotto il minimo
    della verde** (stop), il pivot è morto → niente più alert su quel pivot.
11. **Solo pivot della sessione di oggi** (niente pivot dei giorni precedenti).
12. **Massimo 1 crossback per pivot**.
13. Può scattare **solo l'ultima 5m chiusa** (nessun alert in ritardo/stale).
14. **Nessun filtro RS**: l'RS Rating (Fred6724 vs ^GSPC) è mostrato solo come info.
15. Dedupe in `signal_state.json` (chiave `TICKER|30M PIVOT|green_t|cross|bar_t`).

**Calibrazione (riferimenti @1ChartMaster)** con la ref attuale:
NBIS 10-05 11:30 = 0.65, LITE 09-28 11:30 = 1.11, STX 09-29 13:00 = 0.79,
MRVL 09-28 11:30 = 0.99, CRDO 09-30 11:30 = 0.55 → tutti passano a **0.55**.
Esempio gap down: TXG 10-07 (chiusura 80.66 → minimo 73.00 = 7.66 / ATR 6.51 = 1.18×).

---

## 4. Flag e costanti chiave in `scanner.py`

| Costante | Valore live | Significato |
|---|---|---|
| `UNIVERSE_MODE` | `"wl323848747"` | universo = file `pivot_wl_*.txt` |
| `PIVOT_WL_PATHS` | Main + Focus | file dell'universo |
| `ENABLE_30M_PIVOT` | `True` | alert 30m pivot attivo |
| `ENABLE_30M_PIVOT_BREAK` | `False` | **niente** alert sul break del massimo |
| `ENABLE_DAY_MONITOR_EMA` | `False` | extra day_monitor spenti |
| `ENABLE_DAILY_EMA_PULLBACK` | `False` | Daily EMA spento |
| `ENABLE_SMA30_PULLBACK` | `False` | 5MA/SMA30 65m spento |
| `ENABLE_VWAP_CROSS` | `False` | VWAP spento |
| `BARS_PER_30M` | `6` | 6 barre 5m = 1 barra 30m |
| `PIVOT30_MIN_REDS` | `2` | rosse minime prima della verde |
| `PIVOT30_GAP_DOWN_COUNTS_AS_RED` | `True` | gap down = 1 rossa |
| `PIVOT30_DROP_MODE` | `"high_ref"` | ref = massimo di sessione / chiusura precedente su gap down |
| `PIVOT30_ATR_MULT` | `0.55` | soglia drop in × ATR14 |
| `PIVOT30_SAME_SESSION_ONLY` | `True` | solo pivot di oggi |
| `PIVOT30_MAX_CROSSES` | `1` | 1 crossback per pivot (`None` = illimitati) |
| `RS_MIN_30M_PIVOT` | `None` | nessun filtro RS |
| `EMA_FAST` / `EMA_SLOW` | `6` / `20` | EMA del crossback (5m) |
| `MACD_FAST/SLOW/SIGNAL` | `6/20/9` | MACD del crossback |
| `MAX_30M_PIVOT_BREAKS` | `3` | usato solo se i break venissero riattivati |

Nota: il commento sopra `PIVOT30_DROP_MODE` nel codice cita ancora il "prior-day high"
(storico). Il codice reale usa la regola del §3 punto 6.

---

## 5. Come gira (runtime)

- **Loop**: `rth_scan_loop_30s.sh` lancia `refresh_yfinance.py --scan` **~20 s dopo
  ogni chiusura 5m**, solo **lun–ven 15:10–21:55 Rome**. Usa `flock` per non sovrapporsi.
  - PID: `/tmp/tv-scanner-rth-loop.pid` — Log: `/tmp/tv-scanner-rth.log`
    (ogni giro scrive `START …` e `END rc=0`).
- **Cron** (tiene vivo il loop; lo ferma fuori finestra):
  ```
  SHELL=/bin/bash
  TZ=Europe/Rome
  */5 15-21 * * 1-5 /workspace/tv-scanner/ensure_rth_loop.sh
  ```
  ⚠️ Nel crontab c'è anche la riga di **jeff-coach** (`/workspace/jeff-coach-alerts/...`):
  è un altro progetto, **non toccarla**.
- **Dati**: yfinance — 5m ultimi 10 giorni (RTH, `prepost=False`) in `cache/*.json`,
  daily 2 anni in `cache/daily/*.json` (incluso `^GSPC` per l'RS).
  La cache si ricrea da sola al primo giro.
- **File di output** (rigenerati, non nel backup): `signal_state.json` (dedupe),
  `last_scan_summary.json`, `last_signals.md`.

---

## 6. Discord

- Il webhook di Remy si legge, in quest'ordine, da:
  1. variabile d'ambiente `DISCORD_WEBHOOK_URL`, oppure
  2. secret del box (`/home/box/agent-data/box-secrets.json`, chiave `DISCORD_WEBHOOK_URL`).
- **È un SEGRETO**: al ripristino chiederlo a Ronin **con input segreto mascherato**
  (nome `DISCORD_WEBHOOK_URL`). Mai incollarlo in chat, file, log o archivi.
  Dettagli: `DISCORD_WEBHOOK_SETUP.md`.
- Verifica senza stampare l'URL: `.venv/bin/python discord_notify.py --check`
  → `webhook_ok` (oppure `webhook_missing`).
- **Formato messaggio**: embed separato con titolo
  **`30 minute pivot • HH:MM Close`** (HH:MM = chiusura della 5m, ora di Roma),
  colore **#5DADE2**, testo semplice: **niente ANSI, niente code fence**.
  Si invia solo se ci sono alert nuovi (niente sezioni vuote).

---

## 7. Ripristino passo-passo (box nuovo)

1. **Estrai l'archivio** in `/workspace`:
   ```bash
   cd /workspace && tar -xzf tv-scanner-backup-2026-10-08.tar.gz
   cd /workspace/tv-scanner
   ```
2. **Crea il virtualenv** e installa le librerie:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -U pip
   .venv/bin/pip install -r requirements.txt   # yfinance, pandas, numpy, requests, pytest
   ```
3. **Rendi eseguibili gli script**:
   ```bash
   chmod +x *.sh *.py
   ```
4. **Test** (devono passare tutti):
   ```bash
   .venv/bin/python -m pytest -q test_30m_pivot.py
   ```
5. **Webhook Discord**: chiedilo a Ronin con **input segreto mascherato**
   (`DISCORD_WEBHOOK_URL`), poi `.venv/bin/python discord_notify.py --check` → `webhook_ok`.
6. **Aggiorna le watchlist** (opzionale se i file sono recenti): leggi le WL TV 323848747 e
   318147906 (sola lettura!) e lancia `sync_pivot_wl.py` come al §2.
7. **Prova a vuoto** (scarica dati, nessun Discord, `signal_state.json` intatto):
   ```bash
   .venv/bin/python refresh_yfinance.py --scan --dry-run
   ```
8. **Installa il cron** (aggiungi la riga **senza cancellare** le altre, es. jeff-coach):
   ```bash
   (crontab -l 2>/dev/null; echo '*/5 15-21 * * 1-5 /workspace/tv-scanner/ensure_rth_loop.sh') | crontab -
   crontab -l   # controlla che ci siano SHELL=/bin/bash e TZ=Europe/Rome in testa
   ```
9. **Controllo in orario di mercato** (dopo le 15:10 Rome):
   ```bash
   kill -0 $(cat /tmp/tv-scanner-rth-loop.pid) && echo loop vivo
   tail -5 /tmp/tv-scanner-rth.log    # deve comparire "END rc=0"
   ```
10. **Ripristina la routine delle 15:00** (sync watchlist) nell'agente, se persa.

---

## 8. Regole operative per l'AI che lo gestisce

- Prima di modificare `scanner.py`: **backup** `scanner.py.bak_AAAAMMGG_<motivo>`,
  modifica una **copia**, lancia i test, poi sposta al suo posto (il codice live deve
  restare sempre importabile: il loop lo ricarica a ogni giro).
- Prove = `--dry-run` (niente Discord, niente `signal_state.json`).
- Mai modificare le watchlist su TradingView. Mai esporre il webhook.
- Orari sempre in ora di Roma, con etichetta.

---

## 9. Contenuto dell'archivio

- Codice: `scanner.py` (logica), `refresh_yfinance.py` (dati + scan),
  `discord_notify.py` (Discord), `rs_rating.py` (RS info), `sync_pivot_wl.py` (watchlist),
  altri `.py` di servizio/legacy (`run_scan.py`, `verify_indicators.py`, `tv_fetch.py`, …).
- Script: `rth_scan_loop_30s.sh`, `ensure_rth_loop.sh`, `cron_rth_scan.sh` (legacy).
- Test: `test_30m_pivot.py`.
- Liste: `pivot_wl_323848747.txt`, `pivot_wl_318147906.txt`, `symbols.txt`,
  `watchlist.json`, `day_monitor.txt`, `pivot30_list.txt`, `missing.txt`.
- Docs: questo file, `DISCORD_WEBHOOK_SETUP.md`, `RULES_RTH_LONG.md` (in parte storico),
  `FAST_PATH.md`, `OPTION_B_READY.md`, `verify-yahoo-vs-alerts.md`, `requirements.txt`.
- **Esclusi**: `.venv/`, `cache/`, `__pycache__/`, backup `*.bak*`, vecchi `.tar.gz`,
  `results/`, `mcp_inbox/`, `backup/`, `shard_*`, `signal_state*.json`, log e output.
