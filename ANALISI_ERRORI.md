# Analisi: perché Dua e Sydney davano liste diverse

Analisi dell'8 ottobre 2026 su:
- i due backup completi;
- METODOLOGIA e MEMORIA;
- lo storico chat dal 3 all'8/10;
- il playbook di Jeff (hard rules, correzioni di Ronin, checklist);
- gli script dei giorni 06, 07 e 08/10.

Le differenze di lista vengono quasi tutte da **come** sono costruite le liste, non dalle regole. Le regole erano già state chiuse da Ronin.

---

## 1. Le liste sono scritte a mano ogni giorno (causa principale)

Tutte e due le coach copiano gli script del giorno prima e cambiano le date. Poi **scrivono Focus e Stalk dentro il codice** come elenchi fissi:
- **Dua**, `build.py`: `F={'SIMO': ..., 'PLTR': ...}` e `S={'NBIS': ..., ...}`.
- **Sydney**, `build.py`: `FOCUS=[...]`, `STALK=[...]` e `SKIP=[...]`.

Gli script calcolano i numeri, ma la decisione finale è un elenco digitato. Conseguenze:

| Problema | Esempio |
|---|---|
| Un nome che passa i gate ma non viene "scelto" non entra da nessuna parte. | Dua 08/10: lo Stalk viene da una lista scritta a mano più i near-miss stampati, non da una regola. |
| Calcoli fatti solo sui nomi scritti a mano. | Dua 08/10: la SMA30 65m è calcolata su `redo_s7.csv` più 19 ticker digitati (`sma65.py`). Gli utili su 38 ticker digitati (`earn_check.py`). Un nome nuovo resta senza controllo. |
| Date fisse nel codice. | `CUT='2026-10-07'`, finestra utili `'2026-10-08'<=e<='2026-10-14'`, 65m `>= '2026-10-01'`. Se un giorno l'aggiornamento salta, i conti sono sbagliati senza errori visibili. |
| "Pattern a occhio" senza traccia. | Le frasi dei Focus sono scritte a mano. Non si può ricostruire perché un nome è passato. |

## 2. Universi diversi

| | Dua | Sydney |
|---|---|---|
| Fonte | Screener Yahoo **fotografato il 2–3/10** (`focus_universe_meta.json`, 1355 nomi) | Cache daily di **Remy** (`/workspace/tv-scanner/cache/daily`, circa 1364 simboli), più le liste precedenti |
| Market cap | Ferma al 2–3/10 | yfinance `info`, fresca |
| Utili per l'universo | Data nel meta, ferma al 2–3/10 | yfinance calendar solo sui nomi con ≤2 fail |
| Biotech | Esclusi Biotechnology **e Drug Manufacturers** (dallo screener) | Solo industry = Biotechnology |

Un nome presente in un solo universo finisce automaticamente nello **Stalk pubblico**, come "nome che ha una sola". Lo Stalk si gonfia e il Focus perde nomi validi.

## 3. Stessa regola, codice diverso

| Regola di Ronin | Dua | Sydney | Effetto |
|---|---|---|---|
| Medie corte (06/10, poi 08/10: basta la EMA 9, la EMA 21 è contesto) | close > EMA9 ed entro 1,5 ATR | close > EMA9 **e > EMA21**, entro 1,5 ATR | Sydney escludeva nomi sopra la 9 ma sotto la 21 |
| ≥2 giorni di compressione (hard rule 15) | VCP ≤25 oggi **e** ieri | ≥2 giorni su 5 con range < ADR20 | Definizioni diverse: un nome è Focus per una e Stalk per l'altra |
| Atr Ext ≤ ~4× | `ext <= 4.2` | `ext > 4.0` = fail | SMCI 4,02×: Focus per Dua, Stalk per Sydney |
| Tetto ~5% | dalla SMA5 daily | dalla SMA30 65m | Piccole differenze sui nomi al limite |
| Utili entro 5 sedute | finestra 08–14/10 | finestra **fino al 15/10** (`min(v)<='2026-10-15'`) | Sydney toglieva nomi con utili alla 6ª seduta, che per Jeff vanno bene |
| SMA200 non in calo | SMA200 ≥ quella di 5 barre fa | SMA200 > quella di 5 barre fa | Differenza solo con la 200 piatta |
| RS | pine_replay | pine_replay (dal 06/10, prima percentile: PLTR 78 contro 88) | Allineato |

## 4. Lo Stalk non seguiva la regola

Regola di Ronin: lo Stalk è chi passa universo e tema ma ha un gate Focus aperto (estensione oltre ~4×, pattern largo, eccetera).

| Coach | Cosa faceva |
|---|---|
| Sydney | Metteva in `SKIP` (fuori lista) nomi con un solo gate aperto: AMD, OKTA e SMTC per l'estensione; VEEV, ELF e THC per il pattern. |
| Dua | Filtrava l'estensione **prima** di costruire lo Stalk: chi era oltre 4,2× spariva, salvo aggiunte a mano (FTNT). |

Ognuna, insomma, aveva il suo Stalk e l'unione dei due era casuale.

## 5. Pattern: due letture diverse, nessuna scritta

Quasi tutti i disaccordi dell'08/10 sono qui:

| Nome | Dua | Sydney |
|---|---|---|
| SN, BE, VRNS | Stalk: range 10 sedute 2,8× ADR (tetto 2,5×) | Focus |
| CLMT | Focus | Stalk: ancora in trend |
| VEEV | Focus | Fuori: base dopo un pullback di 4,3 ATR |
| ELF | Focus | Fuori: nessuna spinta fresca |

Tutte e due avevano ragione secondo il proprio metro. Il problema era che il metro non era scritto da nessuna parte, quindi non era ripetibile.

## 6. Bug negli alert (loop di Sydney)

1. **Ora legale.** La finestra è fissa a 15:10–21:55 di Roma.
   - Dal **26 al 30 ottobre 2026** l'Europa torna all'ora solare prima degli USA e l'apertura è alle **14:30** di Roma.
   - Il loop sarebbe partito con 40 minuti di ritardo, perdendo gli alert RVOL della prima ora e i primi break dell'ORH.
   - Lo stesso succede a marzo.
   - Anche il cron (`*/5 15-21`) non copriva le 14:xx.
2. **Gate rifatti sui dati live.** Il loop ricalcolava l'ATR% (≥2,8) e l'adv$ includendo la barra di oggi ancora in corso.
   - Un Focus concordato con ATR% vicino a 2,8 poteva essere bloccato in silenzio.
   - Ronin aveva chiesto che il volume non bloccasse nulla.
3. **2–3 chiamate Yahoo per nome ogni 90 secondi** (`history` daily, `history` 5m, `info`): con oltre 40 nomi c'è rischio di errore 429 e di cicli più lenti di 90 secondi.
4. **Docstring contraddittoria:** dice "premarket included" sull'RVOL, ma il codice usa `prepost=False`.
5. **Nessun controllo sull'inseguimento.** L'ingresso parte la prima volta che il prezzo è ≥ ORH, anche alle 20:00 e molto sopra.
   - Il nuovo loop ha l'opzione `CHASE_MAX_ATR_ABOVE_ORH`, **spenta**: Ronin non l'ha chiesta.

## 7. Memoria vecchia rimasta attiva

- **Memoria di Sydney:** "VARS uptick = Focus". Il VARS è stato sostituito dall'RS Rating il 04/10.
- **Metodologia di Sydney:** "card con ATR% ed estensione". Ronin il 04/10 ha detto Atr Ext, niente ATR%.
- **Weekly del 05/10:** usava ancora il vecchio gap EMA 9/21 settimanali e un tetto 8 Focus / 15 Stalk.

## 8. Processo

- Due coach più un confronto alle 10:15 vuol dire due punti di guasto. Se Sydney è in ritardo, non si pubblica niente.
- Le correzioni dopo il confronto (il top-11 del 06/10, i rifacimenti) hanno generato PATCH multipli e messaggi intermedi a Ronin.

---

## Cosa cambia con il bot unico

| Problema | Soluzione |
|---|---|
| Liste a mano | Un solo motore Python (`jeffcoach/`). Ogni nome dell'universo passa dagli stessi gate, nello stesso ordine, ogni giorno. Il file di dettaglio dice **per ogni nome** quale gate passa e quale no. |
| Universi diversi | Screener Yahoo rinnovato ogni settimana (mcap > 500M, NMS/NYQ/ASE/NGM/NCM) **più** la cache di Remy **più** i nomi del giorno prima. Market cap, tipo e industria freschi (`info`) su ogni nome che entra in lista. |
| Regole implementate in modo diverso | Una sola definizione in `config.py`, con la fonte accanto. Le scelte di Ronin dell'08/10: EMA 21 solo contesto; compressione = almeno 2 delle ultime 3 barre sotto l'ADR20 più VCP ≤25; esclusa solo l'industria Biotechnology. |
| Stalk casuale | Regola scritta (vedi METODOLOGIA_UNIFICATA §5). |
| Pattern | Le due letture, quella di Dua (range su ADR) e quella di Sydney (spinta, contrazione e trend in ATR), sono codificate tutte e due. **Focus solo se lo danno stretto entrambe**; se una dice largo, il nome va in Stalk e il riepilogo dice perché. È la regola "se non siete d'accordo va in Stalk", applicata in automatico. |
| Occhio del bot | Il bot può solo **declassare** un Focus a Stalk (con motivo) o cambiare la frase. Non può promuovere né aggiungere nomi. |
| Utili | Finestra di 5 **sedute NYSE** vere (festività comprese), su tutti i nomi in lista. Due fonti yfinance più lo screener: basta una fonte nella finestra per togliere il nome. |
| Alert | Orari in ora di New York, nessun gate ricalcolato live, un download per ciclo. Stessi messaggi di prima. |

## Verifica sul close del 07/10 (lista dell'08/10)

Rifatta da zero con il motore unico, senza guardare le liste di Dua e Sydney:
- **Focus: SIMO, PLTR, SIG.** È identico al Focus pubblico concordato quel giorno.
- **Disaccordi segnalati:** SN, BE, VRNS, CLMT, VEEV, ELF e THC. Sono esattamente i disaccordi reali Dua/Sydney di quel giorno, e restano in Stalk.
- **Valori numerici:** RS, VCP, SMA30 65m e Atr Ext coincidono con quelli di Dua al centesimo (es. SIMO RS 98 VCP 11,95; CAKE 106,99 contro SMA30 65m 107,97).
- **Stalk:** 37 nomi, di cui 35 tra i 41 Stalk pubblici. Restano fuori:
  - ETN e MRVL, che hanno 3 gate aperti;
  - FROG, HPQ, PI e QLYS: nessuna delle due letture vede un pattern. Finiscono nella riga "numeri ok ma senza pattern" del riepilogo, insieme ai nomi che Sydney metteva in SKIP (DINO, PARR, TEAM, ZETA…).
