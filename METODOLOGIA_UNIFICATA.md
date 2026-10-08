# Metodologia del bot unico: Focus/Stalk alla Jeff Sun per Ronin

Stato all'**8 ottobre 2026**. Sostituisce le due metodologie di Dua e di Sydney.

- Le regole sono quelle chiuse da Ronin fino al 06/10, più le tre decisioni dell'08/10 (§13).
- Ogni numero sta in `jeffcoach/config.py`, con la fonte accanto. Questo documento e il codice devono sempre dire la stessa cosa.

Principi di metodo:
- Non si inventano soglie.
- Non si taglia sul numero.
- Nessuna lista si scrive a mano: ogni nome passa dagli stessi gate e ogni esclusione ha il suo motivo scritto.
- Prima uno screen largo, poi i gate.

Fonte del metodo: Jeff Sun (@jfsrev), Complete Traders' Guide, post X, Hub FAQ e il PDF di Ronin (`MATERIALE/jeff-sun-playbook/`). **Non si copiano i ticker di Jeff da X.**

---

## 0. In una frase

Ogni giorno di borsa, sulla **chiusura daily RTH** della seduta precedente, il motore costruisce la lista delle azioni USA forti (RS ≥ 80) che stanno facendo un **pattern di continuation long già stretto** vicino alle medie corte.

- **Focus:** chi chiude tutti i gate.
- **Stalk:** chi ha il pattern ma ancora un gate aperto.

L'ingresso è la rottura del **massimo dei primi 30 minuti** (30m ORH). Gli alert partono dallo stesso bot.

## 1. Universo (gate duri)

| Gate | Regola | Fonte |
|---|---|---|
| Market cap | > $500M | [RONIN 04/10] |
| Liquidità | adv$ = `sma(volume[1]*close[1],50)` ≥ $50M | [RONIN] |
| Volatilità | ATR% = Wilder ATR14 / close × 100 ≥ 2,8 | [RONIN 04/10] |
| Strumenti | Solo azioni (quoteType EQUITY). Mai ETF. | [RONIN 01/10] |
| Biotech | Esclusa l'industria Yahoo **Biotechnology** (più la lista manuale: ADPT). Il pharma resta. | [JS hard 3] [RONIN 08/10] |
| Prezzi | Solo chiusure daily RTH completate, `auto_adjust=False`. Mai pre o after-market. | [RONIN 01/10] |

**Da dove escono i nomi.** Lo screener Yahoo (mcap > 500M, borse NMS/NYQ/ASE/NGM/NCM) si rinnova ogni 6 giorni. A questo si aggiungono:
- i simboli della cache daily di Remy, letta e non modificata;
- i nomi della lista del giorno prima.

**Verifiche fresche.** Market cap, tipo e industria vengono da yfinance `info`, controllati su **ogni** nome che entra in lista.

## 2. Utili

- **Fuori dalla lista** chi ha utili nelle prossime **5 sedute NYSE**, compresa quella della lista. Esempio: lista dell'08/10, finestra 08–14/10. Dalla sesta seduta va bene. [JS] [RONIN]
- **Fonti:** yfinance `calendar`, yfinance `get_earnings_dates` e la data dello screener. Basta **una** fonte nella finestra per togliere il nome (caso AEHR, 06/10).
- **Data mancante:** non è un fail, ma va scritta nel riepilogo.
- **Utili nel giorno del close di riferimento:** segnalati, perché potrebbero essere dopo la chiusura.

## 3. RS Rating

- **Indicatore:** Fred6724 contro SP:SPX (^GSPC), scala 1–99, calcolato **in locale** con le soglie pine_replay (195.93, 117.11, 99.04, 91.66, 80.96, 53.64, 24.86). Mai csv scaricati. [RONIN 04–06/10]
- **Formula:** `0.4·C/C63 + 0.2·C/C126 + 0.2·C/C189 + 0.2·C/C252` (IPO: `min(bar_index, N)`), poi `rs/rs_SPX×100` e la mappa a 7 soglie.
- **Focus** con RS ≥ 80. Più è alto, meglio è. Non è un veto sugli alert.
- **Verificato:** stessi numeri di `compute_rs.py` e `rs_rating.py` (SIMO 98, PLTR 91, SIG 85 sul close del 07/10).

## 4. Gate Focus sulla daily (tutti obbligatori)

| # | Gate | Regola esatta nel codice | Fonte |
|---|---|---|---|
| 1 | RS | ≥ 80 | [RONIN 04/10] |
| 2 | SMA200 | close > SMA200 **e** SMA200 oggi ≥ SMA200 di 5 barre fa | [JS hard 7] [RONIN 01/10] |
| 3 | Atr Ext | `((close−SMA50)/SMA50×100)/ATR%` ≤ 4,0 | [RONIN 01/10] |
| 4 | Tetto 5% | \|close/SMA5 − 1\| ≤ 5% (tetto, non fascia) | [RONIN 04/10] |
| 5 | SMA30 65m | close daily **sopra** la SMA30 delle barre a 65 minuti RTH (§7) | [RONIN 06/10] |
| 6 | EMA 9 | `0 < (close − EMA9)/ATR14 ≤ 1,5`. **La EMA 21 è solo contesto.** | [RONIN 06/10, 08/10] |
| 7 | VCP | VCP Tightness ≤ 25 (script 5/20/50) | [RONIN 04/10] |
| 8 | Compressione | almeno **2 delle ultime 3** barre con range% < ADR20% (un solo giorno largo non azzera i precedenti, caso PLTR) | [JS hard 15] [RONIN 08/10] |
| 9 | Pattern | continuation long già stretto: le **due letture** (§6) devono dirlo **tutte e due** | [RONIN 04/10] |

- **Nessun taglio sul numero:** tutti i nomi che chiudono i 9 gate sono Focus. [RONIN 06/10]
- **Distanza dai massimi a 52 settimane:** solo nota, non decide. [RONIN 01/10]
- **Contrazione:** si misura con ATR, ADR e VCP, non con il range del giorno prima. [RONIN 04/10]

## 5. Stalk

Un nome entra in Stalk se:
- passa universo, utili e RS ≥ 80;
- sta **sopra la SMA200** (anche se la 200 scende: in quel caso è Stalk, mai Focus);
- ha almeno un gate Focus aperto;
- e vale una di queste condizioni:
  - **nome nuovo:** al massimo **1 gate numerico** aperto (gate 1–8) e almeno **una** delle due letture vede un pattern stretto. In pratica: il pattern c'è, manca un gate;
  - **nome già in lista ieri:** resta in Stalk finché ha al massimo **2 gate numerici** aperti. Con 3 o più esce;
  - **RS 70–79** con tutti gli altri gate chiusi: è il tema forte con RS appena sotto. [RONIN 04/10]

**Scadenza (dal 09/10).** Un nome che resta in Stalk solo per la regola "già in lista" (cioè come nome nuovo non entrerebbe) ha un contatore di sedute (`carry_days` nella lista pubblica). Dopo **5 sedute di fila** così esce, con il motivo "stale Stalk". Se nel frattempo torna a soddisfare la regola dei nomi nuovi (1 gate aperto più un pattern stretto), il contatore torna a zero. Serve a tenere la lista corta: senza scadenza i nomi entrati una volta restano finché non aprono 3 gate. La soglia è `STALK_CARRY_MAX_SESSIONS` in `config.py`.

**Chi resta fuori:**
- **Sotto la SMA200:** mai in lista, finché non la riprende e ricostruisce la struttura. [RONIN 01/10]
- **Numeri ok ma nessuna delle due letture vede un pattern di continuation** (ancora in trend, senza spinta, base dopo un pullback profondo): fuori lista, ma **elencati nel riepilogo** perché Ronin li veda.

**Come si legge lo Stalk sulla card:**
- ogni riga ha i gate aperti in inglese (es. `under 65m SMA30 (-0.9%)`, `loose VCP`, `extended`, `1 tight day`);
- ordine per RS decrescente, poi per ticker.

*(Calibrazione, 08/10: con queste regole lo Stalk dell'08/10 viene di 37 nomi, 35 dei quali erano nello Stalk pubblico di Dua e Sydney.)*

## 6. Pattern: lista chiusa e doppia lettura

**Ammessi (continuation long):**
- flag: il canale stretto dopo la spinta, il mini flag di Jeff;
- pennant: linee che convergono;
- box o rettangolo rialzista con range che si riducono;
- falling wedge di continuazione;
- base o trendline ascendente (il triangolo ascendente è questa);
- VCP.

**Fuori:**
- rising wedge, rettangolo e pennant ribassisti, triangolo discendente;
- tutta la riga Reversal e il falling wedge da fondo;
- la ripresa a V senza base.

La trendline discendente singola non è un ingresso. Non si usano entry, stop e target del foglio. [RONIN 04/10]

"Pattern già stretto" si misura con due letture indipendenti, quelle che usavano Dua e Sydney, scritte in `config.py` (implementazione, non gate nuovi):

| Lettura A (ex Dua, su ADR20) | Lettura B (ex Sydney, in ATR) |
|---|---|
| range 10 sedute ≤ 2,5× ADR | spinta: rally dei close in 20 barre ≥ 3 ATR |
| close entro 6% dal massimo a 20 giorni | range 5 sedute ≤ 2 ATR |
| ultima barra ≤ 1,3× ADR | close entro 1 ATR dal massimo a 10 giorni |
| escursione dei close a 5 giorni ≤ 1,3× ADR | pullback dal massimo della spinta ≤ 3,5 ATR (oltre è una base di pullback) |
| spinta ≥ 15% nelle ultime 60 barre | non ancora in trend: pendenze di massimi e minimi a 8 barre non entrambe ≥ 0,25 ATR/barra |
| | niente barra di espansione ieri (≥ 1,5 ATR e ≥ +3%: l'ORH inseguirebbe) |

- **Focus** solo se A **e** B sono strette.
- **Se non concordano**, il nome va in Stalk e il riepilogo lo scrive ("A tight / B no fresh thrust"). È la regola "se non siete d'accordo lo mettete in stalk che li guardo io" [RONIN 04/10], applicata in automatico.

### Lettura C: trendline (dal 09/10, per ora solo mostrata)

Una terza lettura, scritta in `jeffcoach/patterns.py`, guarda il grafico come lo si guarda a mano. Le fonti sono il setup "breakout" di Qullamaggie, il ciclo del prezzo di Kell (Base n' Break, EMA crossback, 2B), le trendline di Monis e il failed breakdown di Mancini.

1. **Spinta:** il massimo della spinta e il minimo da cui è partita nei 1–3 mesi prima. Deve valere almeno **+25%** oppure **6 ATR**.
2. **Base:** dal massimo a oggi.
   - Se il massimo è di 1–3 giorni fa, la base è la pausa stretta sui massimi: la finestra più lunga con range ≤ 2,5 ATR. È il caso tipico dei Focus di Jeff, come PLTR, SIG e SIMO l'08/10.
   - La base non deve restituire più di metà della spinta, né scendere più del 30%.
3. **Trendline:**
   - linea alta sui pivot massimi, rispettando il picco;
   - linea bassa sull'ultimo pivot minimo e su uno precedente;
   - dalle due pendenze viene la forma: flag, pennant, base piatta, base ascendente, falling wedge, canale stretto che sale.
   - Sono fuori, come nella lista chiusa: rising wedge, triangolo discendente, canale largo, allargamento.
4. **Stretto:**
   - le due linee distano al massimo 3,5 ATR;
   - il range a 5 giorni è ≤ 2,5 ATR, oppure ATR5/ATR20 ≤ 0,8.
5. **Posizione:**
   - close entro 1,5 ATR sotto la linea alta, e non già oltre di 0,5 ATR;
   - sopra la EMA20;
   - la SMA50 si può toccare, ma non perdere.
6. **Informazioni in più** (non bloccano):
   - "undercut & reclaim", cioè un minimo sotto il supporto recuperato (2B / failed breakdown);
   - "volume drying up";
   - il **livello della trendline per la seduta dopo** (`trendline_next`), utile come alert su TradingView.

Il modo è in `PATTERN_MODE`:
- `AB`: decidono A e B come prima, C è solo mostrata. È il modo attivo.
- `C`: decide C da sola.
- `C+1`: Focus se C è stretta e almeno una tra A e B è d'accordo.

Sull'08/10:
- `AB` dà 3 Focus (SIMO, PLTR, SIG);
- `C+1` dà 7 Focus;
- `C` ne dà 16.

Si sceglie con Ronin dopo qualche settimana di confronto. Il riepilogo ogni giorno elenca dove C non è d'accordo con la decisione.

### Lettura D: canale rialzista, si compra nella parte bassa (dal 09/10, lista a parte) [RONIN 08/10]

Imparata dai grafici di Ronin dell'08/10 (XLK, NET, CRWD, FTNT, RNG, RBRK, SMCI). Codice: `jeffcoach/channel.py`, soglie in `config.CHANNEL`.

- Canale = due linee **parallele** tracciate sui pivot (massimi/minimi su 3 barre per lato) in una finestra da 50 a 150 sedute. Ogni linea ha almeno 2 tocchi (6 in totale), i tocchi coprono almeno il 35% della durata, le barre possono bucare la linea di 0,75 ATR (al massimo 2 spike di più). Larghezza 1,8-8 ATR. Il prezzo è salito nel canale di almeno 1,2 volte la larghezza (scalini, non laterale), pendenza almeno 0,03 ATR per seduta.
- Stati: **parte bassa** (sotto il 40% del range o a meno di 1,2 ATR dalla linea bassa), **pullback sulle EMA** (minimo sulla EMA21 e prezzo nella metà bassa), **backtest della linea rotta** (rotto il bordo alto, torna sulla linea); poi a metà, bordo alto (esteso, non si compra), breakout, esteso sopra, rottura fallita (XLK).
- Zona d'acquisto = i primi tre stati, con EMA21 > SMA50 > SMA200, close sopra la SMA50 e RS >= 80.
- **Lista canale** (`channel_watch` in `today.json`, riga "Canale rialzista" nel riepilogo): i nomi in zona d'acquisto con SMA30 65m ed EMA9. Si segnala anche chi ha **recuperato la SMA30 65m pur essendo ancora sotto la EMA9** [RONIN 08/10].
- **Alert Sydney "· Channel"**: per i nomi della lista che hanno chiuso **sotto** la SMA30 65m, un alert (una volta per nome al giorno) quando in seduta il prezzo torna sopra la SMA30 65m calcolata con il bucket in corso, anche se è ancora sotto la EMA9. È un "guardalo", non un ingresso Focus. Spegnibile con `CHANNEL_ALERT = False`.
- Non cambia Focus/Stalk: escono gli stessi nomi di prima. Gli utili e i gate di universo valgono anche per la lista canale; gli Stalk scaduti possono restarci (spesso sono proprio i pullback nel canale).

## 6b. Forza del gruppo (dal 09/10, per ora solo mostrata)

- **Gruppo:** l'industria Yahoo, circa 145 gruppi. La mappa titolo → industria si rinnova una volta a settimana in `state/industry_map.json`, con uno screener per industria.
- **Forza:** la mediana dell'RS dei titoli del gruppo nell'universo, messa in percentile tra i gruppi (100 = il più forte). I gruppi con meno di 3 titoli usano il percentile del settore.
- **Leader alla Qullamaggie:** il titolo è nel top 2% dell'universo per rendimento a 1, 3 o 6 mesi (`leader` nella lista pubblica).

Il riepilogo mostra i gruppi più forti con i nomi in lista e il percentile del gruppo di ogni Focus.

C'è un gate pronto ma spento: `GROUP_FOCUS_MIN_PCTL` (es. 40), che non farebbe essere Focus un nome di un gruppo debole (resta Stalk). Va acceso solo dopo averlo visto sui dati. Sull'08/10 avrebbe tolto SIG, che è in un gruppo al 10° percentile ed era un Focus di Jeff.

**Revisione a occhio del bot (opzionale).** Dopo il calcolo il bot può guardare i Focus. Se uno non è un pattern ammesso, lo **declassa** a Stalk con un motivo in inglese (`state/daily_<data>/review.json`). Il bot:
- **non può** promuovere un nome;
- **non può** aggiungerne;
- **non può** toccare i gate.

Può anche dare il nome al pattern (flag, pennant, box…) e riscrivere la frase.

## 7. Misure (formule)

- **ATR:** `ta.atr(14)`, Wilder RMA del True Range. `ATR% = ATR/close×100`.
- **Volume:** `avg_vol = sma(volume[1],50)`; `adv$ = sma(volume[1]×close[1],50)`.
- **Medie:**
  - SMA5, SMA25 e SMA50/200 come `ta.sma`;
  - EMA9 ed EMA21 come `ewm(span, adjust=False)`;
  - la SMA200 "non in calo" si confronta con 5 barre fa.
- **VCP Tightness:**
  - `range% = (H−L)/L×100`, `ADR = SMA20(range%)`;
  - spread di close e di massimi/minimi su 5 barre, ciascuno diviso per l'ADR, e poi la media dei due;
  - normalizzazione min/max sulle ultime 50 barre.
  - Se lo storico non riempie la baseline, il punteggio è n/a e la finestra non si accorcia. Verificato identico a `score.py`.
- **SMA30 65m:**
  - barre 5 minuti RTH da yfinance (`prepost=False`), in ora di New York;
  - 6 bucket al giorno (09:30, 10:35, 11:40, 12:45, 13:50, 14:55);
  - close del bucket = ultima barra da 5 minuti disponibile;
  - SMA = media degli ultimi 30 close di bucket. Il gate è close daily > SMA.

## 8. Ingresso, gestione e alert

- **Ingresso:** buy stop sul **massimo dei primi 30 minuti** (09:30–10:00 New York, di solito 16:00 di Roma; 15:00 nelle settimane di cambio ora).
  - Nessun ingresso nei primi 30 minuti.
  - Solo nomi **Focus**. [JS] [RONIN 01/10, 04/10]
- **Alert d'ingresso:** quando il prezzo è ≥ ORH, una volta per nome. Il messaggio contiene:
  - `30m high`;
  - `Price`;
  - `RVOL now`;
  - `RVOL first 30m`.
  - Niente PDH, il volume non blocca. [RONIN 04/10]
- **Alert RVOL:** Focus e Stalk, una volta per nome, quando il volume RTH cumulato arriva al **30% della media a 50 giorni**, solo nella prima ora. Non è un ingresso. [RONIN 30/09]
- **Calcolati ma non bloccano:**
  - LoD 0,7 ATR (si dice in coaching);
  - mega-liquidi con adv$ ≥ $2B (RVOL soft).
- **Gestione:**
  - stop al massimo 1 ATR;
  - al massimo 3 posizioni nuove a seduta;
  - rischio di partenza 0,15%.
- **Finestra:** il loop parte dal cron ogni 5 minuti (14:00–22:55 di Roma) ed è attivo solo durante la seduta NYSE calcolata in ora di New York. Copre festività, chiusure anticipate e le settimane di ora legale sfasata.
- **Condizione di partenza:** se `coach-agreed/today.json` non è della seduta di oggi, non parte nulla.

## 9. Ritmo giornaliero (Europe/Rome, giorni di borsa USA)

| Ora | Dove | Cosa |
|---|---|---|
| ~08:00–09:00 | GitHub Actions (`lista.yml`) | Calcolo completo della lista; commit in `data/` |
| ~10:15 | Attività programmata di Claude (`REVISIONE.md`) | Revisione dei Focus (solo declassare), push di `review.json`, riepilogo a Ronin |
| subito dopo | GitHub Actions (`card.yml`) | Card Discord con il txt TradingView. Se la revisione non arriva: card di riserva alle 12:30–13:30 |
| lunedì ~09:00 | GitHub Actions (`weekly.yml`) | Weekly, niente Discord |
| in seduta USA | PC di Ronin (`JeffCoach-locale`) | Alert d'ingresso e RVOL, scanner di Remy |

**Correzioni nello stesso giorno:** si rilancia "Lista" con `force`, poi "Card Discord", che fa PATCH sullo stesso messaggio. Tutto va fatto prima dell'apertura USA.

## 10. Card Discord

**Struttura:**
- un solo messaggio e un solo embed;
- niente `content`, niente menzioni (`allowed_mentions.parse=[]`), niente code fence;
- colore 15105570, username "Dua" (cambiabile con `COACH_NAME`).

**Testo:**
```
**WATCHLIST — YYYY-MM-DD**

**FOCUS**
• **TICKER** — RS 98 · VCP 12.0 · +1.4% SMA5 · Atr Ext 2.02× · short reason in English

**STALK**
• **TICKER** — RS … · VCP … · ±x.x% SMA5 · Atr Ext …× · open gates
```
- Niente ATR%, niente PDH.
- Oltre 4096 caratteri si accorciano le frasi dello Stalk; i nomi non si tolgono mai.

**Allegato:** `watchlist_<data>.txt` in una riga sola: `###FOCUS,NASDAQ:SIMO,...,###STALK,...`. Borse: NMS/NGM/NCM → NASDAQ, NYQ → NYSE, ASE/PCX → AMEX. `MOG-A` diventa `MOG.A`.

**Webhook:**
- la card usa `COACH_CARD_DISCORD_WEBHOOK_URL`, un segreto del repo GitHub;
- gli alert usano `COACH_ALERT_DISCORD_WEBHOOK_URL`, che sta nel file `.env` del PC;
- mai quelli di Remy, mai stampati.

## 11. Handoff a Remy

`data/remy/pivot30_list.txt` nel repo:
- `date: YYYY-MM-DD`, poi un ticker per riga;
- contiene tutti i Focus e gli Stalk con RS ≥ 80, nello stesso ordine della lista;
- scrittura atomica.
- **Nota:** lo scanner di Remy oggi **non** legge questo file. Il suo universo sono le watchlist TradingView Main e Focus, sincronizzate alle 15:00. Il file resta per riferimento.

## 12. Weekly (lunedì 09:08, sul close del venerdì)

Stessi gate e stessa regola dello Stalk della daily, con queste differenze [RONIN 06/10]:
- pattern, VCP (5/20/50), compressione ed EMA 9 su **barre settimanali** (W-FRI);
- close entro **1,5 ATR settimanali dalla EMA 9 settimanale**; lo scarto 9/21 è irrilevante;
- al posto della SMA30 65m: close entro **~5% dalla SMA 25 giornaliera**;
- **RS daily** ≥ 80; universo, Atr Ext daily, SMA200 e utili come la daily.

**Uscita:** riepilogo nel messaggio della revisione del lunedì; niente Discord, niente alert. File: `data/coach-agreed/weekly_<lunedì>.json`.

**Nota:** le soglie delle due letture del pattern sono calibrate sulle barre daily. Sulla weekly vanno riviste con Ronin dopo le prime weekly regolari. Con `WEEKLY_PATTERN_REQUIRE_BOTH=False` basta una lettura.

## 13. Decisioni dell'08/10 (bot unico)

| Punto | Decisione |
|---|---|
| Struttura | Un bot unico: motore deterministico più revisione a occhio che può solo declassare |
| EMA 21 | Solo contesto. Gate = close sopra la EMA 9 ed entro 1,5 ATR |
| Compressione | Almeno 2 delle ultime 3 barre sotto l'ADR20, più VCP ≤ 25 |
| Biotech | Esclusa solo l'industria Biotechnology (il pharma resta) |
| Confronto Dua/Sydney | Sostituito dalla doppia lettura del pattern nel codice: il disaccordo va in Stalk |
| Stalk portati avanti | Scadenza dopo 5 sedute solo "per inerzia" |
| Forza del gruppo | Calcolata e mostrata, gate spento |
| Lettura C (trendline) | Calcolata e mostrata, modo `AB` finché Ronin non sceglie |

## 14. Regole superate (per non riaprirle)

| Vecchia regola | Sostituita da | Data |
|---|---|---|
| EMA 5 ±5% | Tetto ~5% dalla SMA5 più close sopra la SMA30 65m | 03–06/10 |
| SMA10/SMA20, poi EMA 9 e 21 "ristrette" | Solo entro 1,5 ATR dalla EMA 9 (EMA 21 contesto) | 04/10, 06/10, 08/10 |
| VARS / proxy RS 21–63 | RS Rating Fred6724 ≥ 80, in locale | 04/10 |
| RS da csv scaricati o percentile | pine_replay locale | 05–06/10 |
| Due liste più confronto alle 10:15 | Motore unico con doppia lettura del pattern | 08/10 |
| Top-11 Focus | Nessun taglio | 06/10 |
| LoD ≤ 0,60 ATR come veto | LoD 0,7 ATR, non blocca | 04/10 |
| Gap EMA 9/21 settimanali | Solo 1,5 ATR settimanali dalla EMA 9 settimanale | 06/10 |
| Drug Manufacturers esclusi (Dua) | Solo Biotechnology | 08/10 |
| Copiare i Focus di Jeff da X, controllo abbonati | Lista costruita dal processo; controllo FERMO | 04–05/10 |
