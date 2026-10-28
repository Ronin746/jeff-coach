# jeff-coach

**Jeff Coach multi-edge**: la base del bot di Martin Luk nella versione multi-edge (Ronin746/Martin-coach, main @062aae2,
regole `2026-10-28b-meta`) con sopra la parte del metodo di Jeff Sun (@jfsrev) scelta da Andrea il 28/10: universo e
filtri, gli 8 gate del Focus (compressione 2 su 3 compresa), la lista PEG delayed reaction. Solo long, su Discord come
**Sydney**. Le regole sono in [METODOLOGIA.md](METODOLOGIA.md), i numeri in `jeffcoach/config.py`.

> Non è un consiglio finanziario e non piazza ordini: prepara la lista, manda gli alert e tiene un giornale di trade
> **simulati** (equity virtuale 100.000) per misurare le regole.

## Come gira (ora di Roma, server Oracle)

| Quando | Cosa |
|---|---|
| lun–ven 08:00 | Lista: universo di Jeff, candidati long di Martin, 8 gate di Jeff, edge, regime, temi, PEG. Commit in `data/lists/` e `data/history/`. |
| lun–ven 10:45 | Card di Sydney su Discord con il txt TradingView (POST la prima volta, poi PATCH) e i grafici dei Focus e dei PEG. |
| 08:50 New York | Gap-up pre-market aggiunti alla card (PATCH). |
| in seduta USA | `jeffcoach-alert`: alert di Sydney (livello toccato, trigger a 5 minuti, uscite) e gestione intraday dei trade simulati, Focus e PEG. |
| lun–ven 22:35 | Chiusura: regole sulla chiusura daily, equity, `data/reports/giornale_<data>.md`. |
| lunedì 08:20 | Report di performance (mensile il primo lunedì del mese). |
| lunedì 01:10 | Basket di Lone Stock Trader (copia della lettura di Dua in `~/.lst`). |
| mar–sab 01:45 / 06:45 | Market Monitor nostro sull'universo completo (studio 20%, T2108, grafico della card). |
| lun–ven 13:30 | Salvataggio dei dati, codice nuovo da GitHub, riavvio degli alert. |

I workflow di GitHub Actions sono gli stessi di Martin, con i cron sospesi: si lanciano a mano (Run workflow).

## Dati
```
data/lists/today.json, <SEDUTA>.json        lista pubblica (la leggono gli alert): Focus, lato opposto, PEG
data/lists/watchlist_<SEDUTA>.txt           import TradingView (###FOCUS LONG, ###TOP QUALITY LONG, ###PEG, ###TRACKING LONG)
data/lists/work_<SEDUTA>/                   detail.json, card.json, summary_it.md, review.json, premarket.json, discord_post.json, grafici
data/history/                               liste, potent e ranghi dei temi per seduta (partito dallo storico di Martin al 27/10)
data/journal/                               giornale: positions.json, trades.csv, events.csv, equity.csv
data/reports/ data/alerts/ data/breadth/ data/themes/
data/coach-agreed/ data/watchlists/ data/state/daily_*   storico del JeffCoach di prima (non si tocca)
```

## Installazione sul server (al posto del JeffCoach di prima)
```bash
cd ~/jeff-coach && git pull            # con questo codice su main
bash server/installa.sh                 # la prima volta crea .env ed esce
nano .env                               # COACH_ALERT_DISCORD_WEBHOOK_URL (Sydney) e GITHUB_TOKEN
bash server/installa.sh                 # servizi jeffcoach-* e orari (l'alert non lancia più avvia.py)
.venv/bin/python -m jeffcoach.discord test   # messaggio di prova nel canale di Sydney
```
I servizi di Martin (`martincoach-*`, `martinmeta-*`) non si toccano. Il servizio dati comune `datahub`, se c'è, si
aggancia da solo.

## Comandi
| Cosa | Comando |
|---|---|
| Lista senza pubblicare | `python -m jeffcoach.daily --dry-run` |
| Card (solo se cambiata) | `python -m jeffcoach.discord card --if-changed` |
| Un giro di alert senza invio | `python -m jeffcoach.alerts --once --dry-run --force-window` |
| Chiusura del giornale | `python -m jeffcoach.chiusura` |
| Report | `python -m jeffcoach.report weekly` / `monthly` |
| Prove della parte di Jeff (configurazione vera) | `python tests/test_jeff.py` |
| Prove della base (le stesse di Martin) | `python tests/test_offline.py` |
| La base è ancora quella di Martin? | `python strumenti/identita_base.py /percorso/martin-coach` |
| Prova con dati veri | crea o cambia `prova.txt` su main e fai push (risultato in `data/prove/`) |
| Alert di prova su Discord / rifare la lista di oggi | crea o cambia `prova_alert.txt` / `rifai_oggi.txt` su main (o Run workflow) |

I file `prova.txt`, `prova_alert.txt`, `rifai_oggi.txt` e `mm_storico.txt` non sono nel repo apposta: così il merge del
codice nuovo su main non lancia da solo un alert di prova, la lista rifatta con la card su Discord o lo storico del
Market Monitor. I workflow che li usano partono solo da main.

## Allineamento con Martin
Il codice della base ha gli stessi file di `martincoach/` con il nome `jeffcoach/`; ogni riga cambiata porta `[JEFF]`.
Per portare qui una modifica della base: stessa modifica nel file con lo stesso nome, poi
`python strumenti/identita_base.py <martin-coach>` (deve dire "BASE IDENTICA") e le due serie di prove.
