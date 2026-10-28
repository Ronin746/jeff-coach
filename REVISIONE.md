# Revisione del mattino (facoltativa)

[JEFF 28/10] Stesso meccanismo della base di Martin. Per jeff-coach oggi **nessuna attività programmata la usa**: la
revisione a occhio della lista di JeffCoach è stata tolta da Andrea il 13/10 e la card esce comunque alle 10:45. Se Andrea
la vuole di nuovo, un'attività programmata di Claude (lun–ven, prima delle 10:45) segue questi passi.

## Passi

1. **Repo.** Clona o aggiorna `Ronin746/jeff-coach` (branch `main`). OGGI = data di Roma.
   Se oggi la borsa USA è chiusa (`python -c "from jeffcoach.calendar_us import *; print(is_session(today_rome()))"`) rispondi solo "Borsa USA chiusa oggi".
2. **Aspetta la lista.** Serve `data/lists/OGGI.json`; se manca controlla ogni 5 minuti fino alle 11:45 (`git pull`). Se manca ancora: "Lista di oggi non pronta". Non inventare la lista.
3. **Leggi** `data/lists/work_OGGI/summary_it.md`, i Focus e i PEG in `data/lists/work_OGGI/detail.json` (`focus`, `counter_focus`, `peg_watch`: livello, livelli che lo compongono, distanza, ADR, edge, Jeff RS, VCP).
4. **Revisione** sul grafico daily (connettore TradingView, solo lettura; mai modificare grafici, layout o watchlist). Per ogni Focus e PEG con livello chiediti:
   - il livello si vede in 30 secondi? è davvero una confluenza (EMA, AVWAP, vecchio massimo/minimo, gap)?
   - trend sano (9 > 21 in salita), nessun breakout fallito recente, nessuna distribuzione evidente (candele enormi in alto con volumi record);
   - per i PEG: il gap sugli utili tiene, la base è stretta dentro il range del giorno del gap.
   Voto: **A** (da manuale), **B** (buono), **C** (debole). Se non regge, declassalo.
5. **Scrivi `data/lists/work_OGGI/review.json`, commit e push** (anche `{}`): il push fa ripartire la card.
   ```json
   {"TICKER": {"grade": "A", "note": "first pullback to rising 21 + AVWAP"},
    "TICKER2": {"demote": "failed breakout last week"}}
   ```
   Vietato: aggiungere nomi, promuovere, cambiare soglie o qualunque altro file. Commit `Revisione OGGI`, poi `git pull --rebase && git push`.
6. **Riepilogo ad Andrea** (un solo messaggio, italiano, breve): Bias, Focus, PEG, Tracking, temi, righe della revisione ("TICKER → declassato (motivo)", voti).

## Vincoli
- Il bot non piazza ordini. Solo azioni come idee (gli ETF sono contesto). Solo long.
- Non stampare né scrivere mai webhook o token.
- Tutto quello che va su Discord è in inglese: la `note` di review.json va scritta in inglese, breve.
- Le soglie (`jeffcoach/config.py`) cambiano solo su indicazione esplicita di Andrea, con la riga nel registro di `METODOLOGIA.md`.
