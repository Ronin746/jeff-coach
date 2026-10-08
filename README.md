# jeff-coach

Watchlist Focus/Stalk sul metodo di Jeff Sun (@jfsrev), costruita ogni giorno di borsa sulla chiusura RTH della seduta precedente, con le regole chiuse da Ronin. Il metodo completo è in [METODOLOGIA_UNIFICATA.md](METODOLOGIA_UNIFICATA.md), il motivo del motore unico in [ANALISI_ERRORI.md](ANALISI_ERRORI.md).

> Non è un consiglio finanziario e non piazza ordini: è uno strumento di preparazione della watchlist.

## Come gira

| Quando (Roma) | Dove | Cosa |
|---|---|---|
| lun–ven, ~08:00–09:00 | GitHub Actions: `lista.yml` | Calcola la lista: universo Yahoo, gate, doppia lettura del pattern, utili. Fa commit in `data/`. |
| lun–ven, ~10:15 | Attività programmata di Claude ([REVISIONE.md](REVISIONE.md)) | Revisione a occhio dei Focus: può solo declassare. Push di `review.json` e riepilogo a Ronin. |
| subito dopo | GitHub Actions: `card.yml` | Applica la revisione e pubblica la card Discord con il txt TradingView (POST la prima volta, poi PATCH). Se la revisione non arriva, la card parte comunque verso le 12:30–13:30. |
| lunedì, ~09:00 | GitHub Actions: `weekly.yml` | Weekly sul close del venerdì, niente Discord. |
| in seduta USA | PC di Ronin ([cartella locale](#parte-locale)) | Alert di ingresso (30m ORH) e RVOL, più lo scanner di Remy |

I cron di GitHub sono in UTC e possono partire con qualche minuto di ritardo. Per questo ogni workflow ha due orari (ora legale e ora solare) e il secondo esce subito se il lavoro è già fatto.

## Dati

```
data/coach-agreed/today.json          lista pubblica del giorno (la leggono gli alert)
data/coach-agreed/YYYY-MM-DD.json     storico
data/coach-agreed/watchlist_*.txt     import TradingView (###FOCUS,...,###STALK,...)
data/watchlists/focus_YYYY-MM-DD.json dettaglio: ogni gate di ogni nome, metriche, letture A/B
data/state/daily_YYYY-MM-DD/          card.json, summary_it.md, earnings.json, review.json, discord_post.json
data/coach-agreed/weekly_*.json       weekly
```

## Segreti

Va impostato un solo segreto: **Settings → Secrets and variables → Actions → New repository secret**.
- `COACH_CARD_DISCORD_WEBHOOK_URL`: il webhook del canale della card (quello di Dua).

I webhook degli alert e di Remy restano solo sul PC, nel file `.env`.

## Comandi a mano

- **Rifare la lista:** Actions → "Lista Focus/Stalk del mattino" → Run workflow, con `force` spuntato.
- **Ripubblicare la card:** Actions → "Card Discord" → Run workflow. Fa PATCH sullo stesso messaggio del giorno.
- **In locale:** `python -m jeffcoach.daily --dry-run` (le variabili `JEFF_COACH_HOME` e simili decidono dove scrive).

## Parte locale

La cartella `JeffCoach-locale` (alert, scanner di Remy, sync delle watchlist) non sta in questo repo perché contiene configurazioni personali. Ha il suo `LEGGIMI.md`.

## Alert in cloud (Sydney e Remy)

`.github/workflows/alert.yml` fa in cloud quello che `avvia.py` fa sul PC: alert di Sydney, scanner di Remy ogni
barra da 5 minuti e sync delle watchlist di Remy alle 15:00 di Roma. Parte ogni giorno di borsa alle 15:05 di Roma
(14:05 con l'ora solare USA) e lavora in due turni, perché un lavoro GitHub dura al massimo 6 ore: il primo turno,
dopo 335 minuti, fa partire il secondo e gli passa lo stato. Il secondo finisce 5 minuti dopo la chiusura.

- **In prova** (finché la variabile del repo `CLOUD_ALERT_LIVE` non vale `true`): i messaggi vanno a un finto
  Discord interno (`cloud/sink.py`) e finiscono in `data/cloud/AAAA-MM-GG.jsonl`, così si confrontano con il PC.
- **Dal vivo**: secrets `COACH_ALERT_DISCORD_WEBHOOK_URL` (Sydney) e `REMY_DISCORD_WEBHOOK_URL` (Remy), variabile
  `CLOUD_ALERT_LIVE=true`, e il PC spento (FERMA-ALERT), altrimenti ogni alert arriva due volte.
- Un giro di prova a mercato chiuso: cambiare `cloud/prova.txt` e fare push.
