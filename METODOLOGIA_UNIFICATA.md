# Metodologia del bot unico: Focus/Stalk alla Jeff Sun per Ronin

Stato al **13 ottobre 2026**. Sostituisce le due metodologie di Dua e di Sydney.

- Le regole sono quelle chiuse da Ronin fino al 06/10, più le decisioni dell'08/10 e del 13/10 (§13).
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
| Market cap | > $1 mld | [RONIN 10/10] (era $500M) |
| Liquidità | adv$ = `sma(volume[1]*close[1],50)` ≥ $50M | [RONIN] |
| Volatilità | ATR% = Wilder ATR14 / close × 100 ≥ 2,8 | [RONIN 04/10] |
| Strumenti | Solo azioni (quoteType EQUITY). Mai ETF. | [RONIN 01/10] |
| Biotech | Esclusa l'industria Yahoo **Biotechnology** (più la lista manuale: ADPT). Il pharma resta. | [JS hard 3] [RONIN 08/10] |
| Prezzi | Solo chiusure daily RTH completate, `auto_adjust=False`. Mai pre o after-market. | [RONIN 01/10] |

**Da dove escono i nomi.** Lo screener Yahoo (mcap > 1 mld, borse NMS/NYQ/ASE/NGM/NCM) si rinnova ogni 6 giorni. A questo si aggiungono:
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
| 9 | Pattern | continuation long ammesso e già stretto secondo la **lettura unica** (§6): esito `tight` | [RONIN 13/10] |

- **Nessun taglio sul numero:** tutti i nomi che chiudono i 9 gate sono Focus. [RONIN 06/10]
- **Distanza dai massimi a 52 settimane:** solo nota, non decide. [RONIN 01/10]
- **Contrazione:** si misura con ATR, ADR e VCP, non con il range del giorno prima. [RONIN 04/10]

## 5. Stalk

Un nome entra in Stalk se:
- passa universo, utili e RS ≥ 80;
- sta **sopra la SMA200** (anche se la 200 scende: in quel caso è Stalk, mai Focus);
- ha almeno un gate Focus aperto;
- e vale una di queste condizioni:
  - **nome nuovo:** al massimo **1 gate numerico** aperto (gate 1–8) e un pattern **ammesso** per la lettura unica (`tight` o `forming`). In pratica: il pattern c'è, anche se non è ancora pronto, e manca al massimo un gate;
  - **nome già in lista ieri:** resta in Stalk finché ha al massimo **2 gate numerici** aperti. Con 3 o più esce;
  - **RS 70–79** con tutti gli altri gate chiusi: è il tema forte con RS appena sotto. [RONIN 04/10]

**Scadenza (dal 09/10).** Un nome che resta in Stalk solo per la regola "già in lista" (cioè come nome nuovo non entrerebbe) ha un contatore di sedute (`carry_days` nella lista pubblica). Dopo **5 sedute di fila** così esce, con il motivo "stale Stalk". Se nel frattempo torna a soddisfare la regola dei nomi nuovi (1 gate aperto più un pattern ammesso), il contatore torna a zero. Serve a tenere la lista corta: senza scadenza i nomi entrati una volta restano finché non aprono 3 gate. La soglia è `STALK_CARRY_MAX_SESSIONS` in `config.py`.

**Chi resta fuori:**
- **Sotto la SMA200:** mai in lista, finché non la riprende e ricostruisce la struttura. [RONIN 01/10]
- **Numeri ok ma nessun pattern di continuation ammesso** (ancora in corsa, senza spinta, base dopo un pullback profondo, forma esclusa, SMA50 persa): fuori lista, ma **elencati nel riepilogo** perché Ronin li veda.

**Come si legge lo Stalk sulla card:**
- ogni riga ha i gate aperti in inglese (es. `under 65m SMA30 (-0.9%)`, `loose VCP`, `extended`, `1 tight day`);
- ordine per RS decrescente, poi per ticker.

*(Calibrazione, 08/10: con queste regole lo Stalk dell'08/10 viene di 37 nomi, 35 dei quali erano nello Stalk pubblico di Dua e Sydney.)*

## 6. Pattern: lista chiusa e lettura unica [RONIN 13/10]

**Ammessi (continuation long):**
- flag: il canale stretto dopo la spinta, il mini flag di Jeff;
- pennant: linee che convergono;
- box o rettangolo rialzista con range che si riducono (base piatta);
- falling wedge di continuazione;
- base o trendline ascendente (il triangolo ascendente è questa);
- canale stretto che sale a gradini (le due linee entro 2,5 ATR);
- VCP.

**Fuori:**
- rising wedge, rettangolo e pennant ribassisti, triangolo discendente, allargamento, canale largo che sale;
- tutta la riga Reversal e il falling wedge da fondo;
- la ripresa a V senza base.

La trendline discendente singola non è un ingresso. Non si usano entry, stop e target del foglio. [RONIN 04/10]

### Un solo metodo al posto di due letture

Fino al 12/10 "pattern già stretto" voleva dire che lo dicevano **due letture** insieme: A (ex Dua, ampiezze in ADR) e B (ex Sydney, in ATR). Non concordavano su un nome su tre (17 nomi in disaccordo il 13/10) per due motivi di costruzione, non di giudizio:
- **A** misurava il range di 10 sedute, che dopo una spinta recente comprende la fine della spinta: una pausa di 5 giorni sui massimi risultava "larga" (ZETA, PBF, PI, U, GGB il 13/10);
- **B** cercava la spinta solo negli ultimi 15 giorni: ogni base più lunga di tre settimane risultava "lagging" (MATX, CXW, ERO, WPM, HCC il 13/10), anche i triangoli che Jeff compra;
- **nessuna delle due guardava la forma**: un triangolo discendente o un allargamento passava se era stretto (RNG, FIVN, SN Focus il 09/10; CAKE il 12/10). Per questo serviva la revisione a occhio.

Dal 13/10 c'è **una sola lettura**, quella che disegna il grafico come lo si guarda a mano (ex lettura C, `jeffcoach/patterns.py`, soglie in `config.PATTERN`). Fonti: Jeff (spinta, poi base stretta sulle medie corte; si passa a Focus solo dopo sedute strette con volume in calo, mai dopo una seduta larga), il setup "breakout" di Qullamaggie, il ciclo del prezzo di Kell (Base n' Break, EMA crossback, 2B), le trendline di Monis e il failed breakdown di Mancini.

1. **Spinta**, misurata **prima** della base: dal minimo dei 60 giorni prima al picco, almeno **+25%** oppure **6 ATR**.
2. **Base**, dal picco a oggi, almeno 4 sedute (altrimenti "sta ancora correndo").
   - Se il massimo è di 1–3 giorni fa, la base è la pausa stretta sui massimi: la finestra più lunga con range ≤ 2,5 ATR (PLTR, SIG, SIMO l'08/10).
   - Non restituisce più di **metà della spinta** e non scende più del **30%** dal picco. [RONIN 08/10]
3. **Forma**, dalle trendline: linea alta sui pivot massimi rispettando il picco, linea bassa sull'ultimo pivot minimo e su uno precedente. Le pendenze danno flag, pennant, base piatta, base ascendente, falling wedge, canale stretto; quelle fuori dalla lista chiusa (rising wedge, triangolo discendente, allargamento, canale largo) **non sono ammesse**.
4. **Medie:** la SMA50 si può toccare ma non perdere (close di oggi sopra, al massimo 2 chiusure oltre 0,5 ATR sotto durante la base).
5. **Già stretto e pronto:**
   - le due linee distano al massimo **3,5 ATR**;
   - range degli ultimi 5 giorni ≤ **2 ATR** (il valore di B);
   - ultima seduta ≤ **1,3 ADR** (il valore di A; Jeff: mai dopo una seduta larga);
   - **volume in calo:** media degli ultimi 5 giorni sotto quella dei 50 prima (Jeff; il volume asciutto è anche il segnale migliore nel backtest del 10/10);
   - close entro **1,5 ATR sotto la linea alta** e non oltre di 0,5 ATR;
   - close non sotto la EMA20 (tolleranza 0,3 ATR).
6. **Triangolo ascendente** (`read_triangle`, sotto): è un modo in più per essere ammessi. Se la base non passa ma il triangolo sì, il pattern è il triangolo (con lo stesso controllo su ultima seduta e volume).
7. **Note che non decidono:** "undercut & reclaim" (2B / failed breakdown), "volume drying up" (sotto 0,8 della media), il **livello della linea alta per la seduta dopo** (`trendline_next`).

**Tre esiti** (`pattern` nella lista pubblica):

| Esito | Quando | Effetto |
|---|---|---|
| `tight` | punti 1–5 tutti ok (o triangolo ok) | il gate pattern è chiuso: Focus se lo sono anche gli altri 8 |
| `forming` | forma ammessa (1–4 ok) ma manca qualcosa del punto 5 | Stalk se manca al massimo 1 gate numerico; sulla card il motivo (es. `pattern wide (4.1 ATR)`, `last bar 1.5× ADR`, `already broken out`) |
| `none` | niente spinta, base troppo profonda, forma esclusa o SMA50 persa | non entra come nome nuovo |

Le stesse soglie valgono sulla weekly, lette sulle barre settimanali (§12).

**Verifica sui dati salvati (09–13/10), stessi gate numerici:**
- 09/10: Focus AB = RNG, FIVN, SN, HPQ, ELF → lettura unica = DELL, ELF, ESTC, HPQ, JXN, MANH, NSIT, PARR, SBLK, SIG, SNOW, TENB, VEEV, VRNS. Escono RNG, FIVN e SN (triangolo discendente).
- 12/10: Focus AB = RNG, CAKE, SN → CHEF, CVLT, DELL, ESTC, NSIT, SIG, VRNS. Escono CAKE (allargamento, SMA50 persa), RNG e SN.
- 13/10: Focus AB = nessuno (CAKE e SIG tenuti fuori da tema e regime) → ERO, MATX, PBF, PI, SIG, ZETA; CXW resta Stalk per il volume (1,24× la media).
- I Focus diventano di più (7–14 al giorno prima del regime), perché A e B insieme erano un'intersezione: tagliavano anche le basi buone. Il regime (§ Temi e regime) ne tiene al massimo 3 in MIXED e DEFENSIVE.

### Lettura D: canale rialzista, si compra nella parte bassa (dal 09/10, lista a parte) [RONIN 08/10]

Imparata dai grafici di Ronin dell'08/10 (XLK, NET, CRWD, FTNT, RNG, RBRK, SMCI). Codice: `jeffcoach/channel.py`, soglie in `config.CHANNEL`.

- Canale = due linee **parallele** tracciate sui pivot (massimi/minimi su 3 barre per lato) in una finestra da 50 a 150 sedute. Ogni linea ha almeno 2 tocchi (6 in totale), i tocchi coprono almeno il 35% della durata, le barre possono bucare la linea di 0,75 ATR (al massimo 2 spike di più). Larghezza 1,8-8 ATR. Il prezzo è salito nel canale di almeno 1,2 volte la larghezza (scalini, non laterale), pendenza almeno 0,03 ATR per seduta.
- Stati: **parte bassa** (sotto il 40% del range o a meno di 1,2 ATR dalla linea bassa), **pullback sulle EMA** (minimo sulla EMA21 e prezzo nella metà bassa), **backtest della linea rotta** (rotto il bordo alto, torna sulla linea); poi a metà, bordo alto (esteso, non si compra), breakout, esteso sopra, rottura fallita (XLK).
- Zona d'acquisto = i primi tre stati, con EMA21 > SMA50 > SMA200, close sopra la SMA50 e RS >= 80.
- **Lista canale** (`channel_watch` in `today.json`, riga "Canale rialzista" nel riepilogo): i nomi in zona d'acquisto con SMA30 65m ed EMA9. Si segnala anche chi ha **recuperato la SMA30 65m pur essendo ancora sotto la EMA9** [RONIN 08/10].
- **Alert Sydney "· Channel"**: per i nomi della lista che hanno chiuso **sotto** la SMA30 65m, un alert (una volta per nome al giorno) quando in seduta il prezzo torna sopra la SMA30 65m calcolata con il bucket in corso, anche se è ancora sotto la EMA9. È un "guardalo", non un ingresso Focus. Spegnibile con `CHANNEL_ALERT = False`.
- **Grafico nell'alert Channel (dal 09/10) [RONIN 09/10]:** sotto il testo c'è un'immagine con il daily degli ultimi ~6 mesi (candele, EMA9, EMA21, SMA50 e le due linee del canale prolungate a oggi, linea tratteggiata al prezzo dell'alert) e un riquadro con i close a 65 minuti degli ultimi ~15 giorni e la SMA30 65m. Le linee vengono da `channel_watch[].lines` della lista del mattino. Spegnibile con `CHANNEL_CHART = False`; senza matplotlib l'alert parte senza immagine.
- Non cambia Focus/Stalk: escono gli stessi nomi di prima. Gli utili e i gate di universo valgono anche per la lista canale; gli Stalk scaduti possono restarci (spesso sono proprio i pullback nel canale).

### Trendline discendente e "wedge pop" (dal 12/10) [RONIN 09/10]

Codice: `jeffcoach/dtl.py`, soglie in `config.DTL`. Sul daily, come la si disegna a mano (AAOI, PWR del 09/10):

- **Linea:** parte dal picco più alto delle ultime 200 sedute (nessun massimo più alto dopo) e passa per l'ultimo massimo più basso prima della rottura. Scende di almeno 0,03 ATR a seduta, dura almeno 20 sedute, il prezzo dal picco è sceso almeno del 15%. Fino alla rottura nessun close sopra la linea; i massimi possono bucarla di 0,3 ATR al massimo 3 volte.
- **Rottura:** primo close sopra la linea di almeno 0,1 ATR.
- **Filtri:** universo, utili fuori finestra, RS ≥ 80.
- **Nella card del giorno dopo** (sezione "DOWNTREND LINE BREAK"): solo le rotture in chiusura con volume **≥ 1,5× la media a 50 giorni**.
- **Alert Sydney in seduta** (con grafico daily + 65m):
  - **"· DTL break"**: nomi con il close sotto la linea entro 1 ATR; scatta se il prezzo supera la linea del giorno con **RVOL all'ora del giorno ≥ 1,5** (volume di oggi fino a quell'ora / media delle sedute precedenti alla stessa ora).
  - **"· Wedge pop"**: nomi che hanno rotto la linea nelle ultime 10 sedute (non ricaduti più di 1 ATR sotto). Crossback: il minimo torna sulla EMA9 o EMA21 (entro 0,3 ATR); scatta quando il prezzo, dopo essere stato sotto la SMA30 65m, la recupera stando sopra la EMA9 daily.
- Nel riepilogo: "Trendline discendente (wedge pop)" con le tre liste. Spegnibile con `DTL_ALERT = False`.

### Regole dai post per abbonati di Jeff (dal 09/10) [RONIN 08/10]

- **Gap da riempire — SPENTO** (`GAP_GATE_ON = False`, [RONIN 08/10]: da rifare meglio prima di usarlo). Com'è scritto oggi (`gap` in `focus_gates`, gate "soft"): un gap al ribasso degli ultimi 60 giorni ancora aperto sopra il prezzo, entro 3 ATR, tiene il nome in **Stalk** finché un massimo non torna al minimo del giorno prima del gap (XLK, ESTC, NOW, FRSH). Nel riepilogo: "Gap al ribasso da riempire".
- **Triangolo ascendente** (`patterns.read_triangle`): tetto piatto toccato almeno 2 volte (al massimo 2 spike sopra, nessun close sopra nelle ultime 3 sedute), supporto che sale (0,03–0,15 ATR a seduta) dalla prima metà del triangolo, larghezza che si stringe (≤ 75% di quella iniziale, ≤ 3,5 ATR), durata ≥ 15 sedute, close entro 1,5 ATR sotto il tetto, range 5 giorni ≤ 2 ATR (come la lettura unica), sopra una SMA50 che non scende. È **in più** alla base della lettura unica: se la base non passa ma il triangolo sì, il pattern è il triangolo; un triangolo trovato ma non ancora pronto è `forming` e basta per lo Stalk. Nel riepilogo: "Triangoli ascendenti".
- **Reazione ritardata agli utili** (`peg.py`, lista `peg_watch`): gap ≥ 4% (o 1 ATR) con volume ≥ 1,5× la media (o gap ≥ 8%) di 4–45 sedute fa, **confermato dalla data degli utili**; prezzo tornato nel range del PEG (dal close prima del gap al massimo del giorno del gap), base stretta, sopra la SMA200, RS ≥ 60. Lista a parte nel riepilogo, non cambia Focus/Stalk.

## 6b. Forza del gruppo (dal 09/10, per ora solo mostrata)

- **Gruppo:** l'industria Yahoo, circa 145 gruppi. La mappa titolo → industria si rinnova una volta a settimana in `state/industry_map.json`, con uno screener per industria.
- **Forza:** la mediana dell'RS dei titoli del gruppo nell'universo, messa in percentile tra i gruppi (100 = il più forte). I gruppi con meno di 3 titoli usano il percentile del settore.
- **Leader alla Qullamaggie:** il titolo è nel top 2% dell'universo per rendimento a 1, 3 o 6 mesi (`leader` nella lista pubblica).

Il riepilogo mostra i gruppi più forti con i nomi in lista e il percentile del gruppo di ogni Focus.

C'è un gate pronto ma spento: `GROUP_FOCUS_MIN_PCTL` (es. 40), che non farebbe essere Focus un nome di un gruppo debole (resta Stalk). Va acceso solo dopo averlo visto sui dati. Sull'08/10 avrebbe tolto SIG, che è in un gruppo al 10° percentile ed era un Focus di Jeff.

**Revisione a occhio:** tolta il 13/10 [RONIN 13/10]. La forma del pattern la giudica il motore (§6); nessuno sposta più nomi a mano tra Focus e Stalk.

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
  - `RVOL first 30m`;
  - `RVOL needed` e `LoD` (dal 09/10).
  - Niente PDH. [RONIN 04/10]
- **Condizioni d'ingresso di Jeff (dal 09/10)** [RONIN 08/10, dai post per abbonati]:
  - **RVOL:** controvalore medio ≥ 1 mld $ → non serve (ma niente prima dei 30 minuti). Sotto: RVOL entro 30 minuti tra il **18% e il 40%**, secondo il RVOL pieno di ieri (≤ 40% → 18%, ≥ 125% → 40%, in mezzo lineare). Dopo i 30 minuti la soglia cresce con il tempo (a 60 minuti serve il doppio). Se manca, l'alert non parte e si riprova al giro dopo.
  - **LoD:** prezzo − minimo del giorno ≤ **0,70 ATR**, adesso blocca.
- **Alert RVOL:** Focus e Stalk, una volta per nome, quando il volume RTH cumulato arriva al **30% della media a 50 giorni**, solo nella prima ora. Non è un ingresso. [RONIN 30/09]
- **Calcolati ma non bloccano:**
  - mega-liquidi con adv$ ≥ $2B (RVOL soft per l'alert RVOL del 30%).
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
| 10:45 | Server (`fasi.sh card`) | Card Discord con il txt TradingView. GitHub `card.yml` è la riserva alle 12:30–13:30 |
| lunedì ~09:00 | GitHub Actions (`weekly.yml`) | Weekly, niente Discord |
| in seduta USA | PC di Ronin (`JeffCoach-locale`) | Alert d'ingresso e RVOL, scanner di Remy |

**Correzioni nello stesso giorno:** si rilancia "Lista" con `force`, poi "Card Discord", che fa PATCH sullo stesso messaggio. Tutto va fatto prima dell'apertura USA.

## 10. Card Discord

- **Formato (dal 09/10) [RONIN 09/10]:** niente tabelle. Una voce per nome: in grassetto il ticker con RS · VCP · SMA5 · Atr Ext, e subito sotto (`↳`) la descrizione, per Focus e Stalk. Gli Stalk sono divisi in due sezioni: **sopra** e **sotto** la SMA30 65m. Ogni sezione (Focus, Stalk sopra, Stalk sotto) è un riquadro a sé dello stesso messaggio. Nella descrizione degli Stalk, `lagging` = la lettura B non vede una spinta recente (nessun +3 ATR negli ultimi 15 giorni).
- **Raggruppati per settore [RONIN 09/10]:** dentro Focus, Stalk sopra e Stalk sotto i nomi sono divisi per settore Yahoo (prima i settori con più nomi); nel txt i nomi di ogni sezione seguono lo stesso ordine. Ogni settore ha sull'intestazione le stesse statistiche dei titoli (RS · VCP · SMA5 · Atr Ext), misurate sull'ETF del settore (XLK, XLE, XLY, XLV, XLI, XLB, XLC, XLP, XLF, XLU, XLRE; `config.SECTOR_ETF`), e in fondo quanti titoli del settore hanno RS ≥ 90 sul totale dell'universo, con la variazione rispetto alla chiusura della settimana precedente (`RS≥90 44/115 (+3 vs last wk)`).
- **File txt per TradingView [RONIN 09/10]:** allegato allo stesso messaggio della card (Discord lo mostra sopra i riquadri).
- **Lunghezza:** Discord accetta al massimo 6000 caratteri per messaggio. Se la card li supera, l'ultima sezione continua in un messaggio subito sotto, senza tagliare le descrizioni. Sezioni `###FOCUS`, `###STALK ABOVE 65m SMA30`, `###STALK BELOW 65m SMA30`.

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
- la card usa `COACH_ALERT_DISCORD_WEBHOOK_URL` (Sydney, come gli alert; dal 14/10 Dua non si usa più), un segreto del repo GitHub;
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

**Uscita:** `data/state/weekly_<lunedì>/summary_it.md`; niente Discord, niente alert. File: `data/coach-agreed/weekly_<lunedì>.json`.

**Nota:** il pattern è la stessa lettura unica (§6) sulle barre settimanali, con le soglie in ATR settimanali; servono almeno 90 settimane di storia. Le soglie vanno riviste con Ronin dopo le prime weekly regolari.

## 13. Decisioni dell'08/10 (bot unico)

| Punto | Decisione |
|---|---|
| Struttura | Un bot unico: motore deterministico (la revisione a occhio è stata tolta il 13/10) |
| EMA 21 | Solo contesto. Gate = close sopra la EMA 9 ed entro 1,5 ATR |
| Compressione | Almeno 2 delle ultime 3 barre sotto l'ADR20, più VCP ≤ 25 |
| Biotech | Esclusa solo l'industria Biotechnology (il pharma resta) |
| Confronto Dua/Sydney | Sostituito dalla doppia lettura del pattern nel codice; dal 13/10 da una lettura unica |
| Stalk portati avanti | Scadenza dopo 5 sedute solo "per inerzia" |
| Forza del gruppo | Calcolata e mostrata, gate spento |
| Lettura C (trendline) | Dal 13/10 è la lettura unica del pattern (§6) |
| Canale rialzista (lettura D) | Lista a parte, alert Sydney sul recupero della SMA30 65m anche sotto la EMA9 |
| Regole di Jeff dai post abbonati | RVOL e LoD bloccano l'alert d'ingresso; gap da riempire spento (da rifare); triangolo ascendente in più; lista PEG |
| Letture A e B misurano la base nuova | A: entro 30% dal massimo a 20 giorni invece di 6%; B: la base tiene almeno metà della spinta invece di pullback ≤ 3,5 ATR. Caso HPQ, Focus di Jeff l'08/10 (mini triangolo ascendente) |

### Decisioni del 13/10 [RONIN 13/10]

| Punto | Decisione |
|---|---|
| Revisione a occhio | Tolta: niente più attività programmata delle 10:15, niente `review.json` |
| Pattern | Un solo metodo (lettura unica, §6) al posto delle letture A e B; esiti `tight` / `forming` / `none` |
| Stalk nuovi | Al massimo 1 gate numerico aperto e pattern ammesso (`tight` o `forming`) |

## 14. Regole superate (per non riaprirle)

| Vecchia regola | Sostituita da | Data |
|---|---|---|
| EMA 5 ±5% | Tetto ~5% dalla SMA5 più close sopra la SMA30 65m | 03–06/10 |
| SMA10/SMA20, poi EMA 9 e 21 "ristrette" | Solo entro 1,5 ATR dalla EMA 9 (EMA 21 contesto) | 04/10, 06/10, 08/10 |
| VARS / proxy RS 21–63 | RS Rating Fred6724 ≥ 80, in locale | 04/10 |
| RS da csv scaricati o percentile | pine_replay locale | 05–06/10 |
| Due liste più confronto alle 10:15 | Motore unico con doppia lettura del pattern | 08/10 |
| Top-11 Focus | Nessun taglio | 06/10 |
| LoD ≤ 0,60 ATR come veto | LoD 0,7 ATR, non blocca (04/10); dal 09/10 blocca l'alert d'ingresso | 04/10, 08/10 |
| Volume solo mostrato | RVOL richiesto per l'alert d'ingresso (18–40%, niente sopra 1 mld $) | 08/10 |
| Gap EMA 9/21 settimanali | Solo 1,5 ATR settimanali dalla EMA 9 settimanale | 06/10 |
| Drug Manufacturers esclusi (Dua) | Solo Biotechnology | 08/10 |
| Lettura A: close entro 6% dal massimo a 20 giorni | Entro 30% dal massimo a 20 giorni | 08/10 |
| Lettura B: pullback dal massimo ≤ 3,5 ATR | La base non restituisce più di metà della spinta | 08/10 |
| Lettura B: close entro 1 ATR dal massimo a 10 giorni; niente barra di espansione ieri | Tolte | 08/10 |
| Copiare i Focus di Jeff da X, controllo abbonati | Lista costruita dal processo; controllo FERMO | 04–05/10 |
| Due letture del pattern A e B, Focus solo se concordano; `PATTERN_MODE` | Lettura unica (§6) | 13/10 |
| Lettura A: range 10 sedute ≤ 2,5 ADR, close 5 giorni ≤ 1,3 ADR, spinta ≥ 15% in 60 barre | Base misurata dal picco, linee entro 3,5 ATR, range 5 giorni ≤ 2 ATR; spinta ≥ 25% o 6 ATR prima della base | 13/10 |
| Lettura B: spinta ≥ 3 ATR negli ultimi 15 giorni ("lagging"), pendenze a 8 barre | Spinta misurata prima della base; "ancora in corsa" se la base ha meno di 4 sedute | 13/10 |
| Revisione a occhio delle 10:15 (declassa/promuove) | Tolta: la forma la giudica il motore | 13/10 |

### Lettura D, correzioni del 09/10 (canali riconosciuti per sbaglio)
Ronin: Sydney segnalava "Channel" anche dove il canale non c'è. Rivisti i 32 nomi della lista canale del 09/10:
- **larghezza massima 6 ATR** (era 8): oltre è un trend generico con una linea lontana (QLYS, AVTR, APH, ELF, AUGO);
- **i tocchi devono alternarsi tra le due linee almeno 3 volte** (il prezzo va su e giù dentro il canale), non tutti da una parte;
- **backtest della linea rotta solo per canali che salgono** e solo dopo una rottura vera (almeno 3 close sopra la
  linea alta): niente più canali discendenti o piatti (ARM, PWR, STM, DVN, SNOW) chiamati "backtest".
Risultato sul 09/10: 19 nomi su 32 restano; NET, RNG, RBRK (gli esempi di Ronin) restano canali.
Il grafico dell'alert ricalcola le linee se la lista del giorno non le ha (RBRK del 09/10 era senza linee).

### Backtest daily 2017-2026 dei riconoscimenti (10/10)
Universo: ~1.600 azioni USA di oggi (mcap > 500M; i titoli usciti di borsa mancano, quindi i numeri assoluti sono
ottimistici: contano i confronti). Campione ogni 5 sedute dei titoli con RS (percentile vero del giorno) >= 70,
sopra la SMA200, adv$ >= 50M: 118.000 campioni. Esito = close dopo 20 sedute in ATR (base: +0,26).
- **Trendline discendente rotta** (6.500 rotture): +0,64, la lettura che rende di più. 3+ tocchi +0,70 (2 tocchi
  +0,59: tolte). Rende di più se la discesa è >= 25% (+0,8 contro +0,4 tra 15-25%) e se la linea dura >= 40 sedute
  (+0,75/+0,91 contro +0,41 tra 20-40). Il volume >= 1,5x abbassa le rotture fallite (33% contro 43%).
  Ronin 10/10: si tengono anche le linee corte (P, MMED), stessa dicitura.
- **Letture A, B, C, triangolo**: come stato del giorno, e anche dopo la rottura del massimo a 10 giorni, non fanno
  meglio della base (A +0,28 dopo la rottura, base +0,25). Conta molto di più la RS (RS >= 90: +0,45).
- **Canale (lettura D)**: zona di acquisto +0,16 contro +0,26; anche con l'ingresso sul recupero della SMA30 a 60m
  (dal 2024) +0,61 contro +0,80 della base. Dai dati daily il canale non aggiunge vantaggio.
- **Supporto bucato e recuperato (2B)**: +0,21, come la base.
- **Volume asciutto nella base** (< 0,6 della media): +0,44 dopo la rottura contro +0,25: il segnale di qualità
  più utile tra quelli della lettura C (dal 13/10 è un requisito della lettura unica: volume in calo).
- **Gap al ribasso aperto sopra**: +0,48 dopo la rottura, meglio della base: conferma che la regola del gap va
  tenuta spenta.
Script: tv-scanner/backtest/pattern_daily/.

### Disegno della trendline rivisto con il backtest (10/10)
Provate 11 varianti del disegno sugli stessi campioni 2017-2026 (tolleranza dei tocchi, barre che bucano la linea,
massimi su 2/3/5 barre, distanza minima tra i punti, quanto deve chiudere sopra la linea). La resa delle rotture
cambia poco (+0,65/+0,72 ATR a 20 sedute): il disegno era già solido. Adottato:
- **massimi su 2 barre per lato** (era 3): +38% di linee trovate con la stessa resa (prende linee come DIOD, ALAB, HCC);
- **rottura = close almeno 0,3 ATR sopra la linea** (era 0,1): rotture fallite entro 10 sedute dal 41% al 34%;
  **0,1 ATR basta se quel giorno il volume è >= 1,5x** (MMED 08/10). L'alert in seduta di Sydney usa 0,1 (chiede già RVOL >= 1,5).
Esito: 4.688 rotture in 9 anni (prima 3.391), +0,67 ATR a 20 sedute, fallite 34%. Gli esempi di Ronin (PWR, P, MMED,
CIEN, MRVL, ALAB, AAOI) restano tutti.

## Sezione short (dal 12/10, Ronin) — SOSPESA dal 13/10 (`SHORT["enabled"] = False`)

Stesse regole del long, al contrario, in una sezione separata e parallela (`jeffcoach/short.py`).
- Il grafico di ogni titolo dell'universo si capovolge (prezzo -> 10000/prezzo) e passa dagli stessi gate e dalle
  stessa lettura del pattern del long: SMA200 non obbligatoria (sotto è meglio: quei nomi vanno prima in lista; sopra la card scrive "above SMA200"), entro 1,5 ATR sotto la EMA9, estensione sotto la SMA50
  entro 4, VCP stretto, giorni compressi, bear flag / base discendente, chiusura sotto la SMA30 65m.
- L'RS non è un gate: si mostra quella vera. Ordine: prima i nomi sotto la SMA200, poi RS dalla più bassa.
- Universo, utili e market cap come nel long, sui prezzi veri. Stalk e scadenza come nel long.
- Card: dopo i riquadri long (verdi) vengono i riquadri short (rossi): SHORT FOCUS, SHORT STALK sotto e sopra la SMA30 65m.
  Nel txt TradingView le sezioni ###SHORT seguono quelle long.
- Alert (bordo rosso): RVOL nella prima ora su Focus e Stalk short; ingresso solo Short Focus, dopo 30 minuti, sulla
  rottura del minimo dei primi 30 minuti, con lo stesso RVOL richiesto del long e il massimo del giorno entro 0,7 ATR
  (lo stop). Pausa di 60 minuti per titolo come nel long.
- Per ora niente versione short di canale, trendline, PEG e pivot di Remy.

## Temi e regime di mercato (dal 13/10, Ronin)

**Temi** (`jeffcoach/themes_map.py`, `jeffcoach/etf_holdings.py`, `jeffcoach/themes.py`; dal 15/10 copia della mappa attuale di Martin-coach):
- Solo ETF tematici della lista di Andrea (foglio gid 305077282): tema = colonna Group, nome invariato, tutti i gruppi. Membri = partecipazioni COMPLETE degli ETF dall'N-PORT depositato alla SEC (CUSIP → ticker con OpenFIGI, cache `data/themes/cusip_ticker.json`); riserva per gli ETF senza N-PORT: prime 10 dal repo di NEL (archiviate in `data/themes/etf_holdings_nel.json`).
- Tema principale di un titolo = il gruppo con più ETF che lo tengono, mai un gruppo generico (Momentum, ESG, Meme stocks… contano solo in classifica); a parità di ETF vince il tema con cui il titolo si muove di più (correlazione a 60 sedute con la mediana del tema). Modifiche a mano in `data/themes/manuale.json`.
- ETF senza azioni (GLD, SLV, IBIT, USO, TLT…): l'ETF stesso è membro del suo tema, che entra in classifica anche con un solo ETF; gli ETF restano contesto, mai in lista.
- Niente basket TradingView, niente industria Yahoo: chi non è in un ETF tematico resta senza tema (e quindi non esce mai per il tema). Mappa riscaricata il lunedì.
- Indice del tema: mediana delle variazioni giornaliere dei titoli del tema con controvalore medio ≥ 75M$ (almeno 3 titoli).
- Trend dell'indice: **uptrend** = indice > EMA50 > EMA150 con EMA50 in salita (5 sedute); **downtrend** = indice < EMA50 < EMA150; altrimenti neutro.
- Punteggio (0-100): media dei ranghi di rendimento a 1 e 3 mesi, forza contro l'S&P a 1 mese, quota di titoli Leading (close > EMA50 > EMA150) e quota sopra la EMA21. **Leading** = uptrend e nel 30% più alto.
- Uso: i titoli col tema in **downtrend escono** dalla lista (motivo "theme in downtrend"); Focus e Stalk sono ordinati con i **temi leading prima**, poi per RS. Card: ★ tema accanto al nome e riquadro THEMES (temi leading, temi in downtrend).

**Regime** (`jeffcoach/regime.py`, logica di Martin-coach):
- Market Monitor di Stockbee (dal 15/10 come Martin-coach), fonti in ordine: foglio Google pubblico di Stockbee (`stockbee.py`) → file di NEL → archivio nel repo (`data/breadth/market_monitor_nel.json`, storico dal 2007) → replica completa nostra su ~5.700 azioni USA, calcolata ogni notte alle 00:00 di Roma (workflow "Market Monitor nostro", `data/breadth/market_monitor_full.json`) → calcolo sui titoli della lista; le repliche sono calibrate sulle ultime 120 sedute di Stockbee (stato uguale ~90%) e sulla card sono segnate "own calc". Sulla seduta di riferimento: Defensive se 4% down ≥ 300 o ratio 10g < 0,85 o (ratio 5g < 0,70 e down > 2× up); Expansion se ratio 10g ≥ 1,25, ratio 5g ≥ 1,10, up ≥ 180 e down < 150; altrimenti Mixed.
- Bias: Expansion → LONG, Mixed → MIXED, Defensive → DEFENSIVE. Punteggio indici (QQQ trend EMA9/21 e EMA50, IWM trend, MM ±1, T2108 a 5 sedute ±1) come contesto; decide solo se manca il Market Monitor.
- Gestione (JeffCoach è solo long): LONG nessun limite; MIXED al massimo 3 Focus (prima i temi leading, poi RS); DEFENSIVE solo Focus con tema leading, al massimo 3, segnati **"against the regime"** sulla card e negli alert di Sydney. Gli altri Focus restano in Stalk col motivo "regime".

### Aggiornamento del 16/10 (come Martin-coach, regole 2026-10-16h)
- **Market Monitor letto come Pradeep Bonde** (`regime.mm_state_pradeep`, `MM_READ = "pradeep"`; `"nel"` torna alle regole di prima): Expansion se T2108 < 20, o nei 30 giorni dopo un T2108 < 20 senza vendite in entrata, o indicatore primario verde (+25% nel trimestre > −25%) con acquisti in entrata o T2108 in salita, senza avvisi; Defensive se primario rosso, vendite in entrata (saldo dei giorni ±4% ≤ −2 su 5 sedute) e T2108 in calo; altrimenti Mixed (anche con studio 20% ≥ 200 in 10 sedute, −20% ≥ 200, T2108 > 65). Niente rapporti 5D/10D. Lo studio 20% (titoli +20% / −20% in 5 sedute, prezzo ≥ 3, minv3.1 ≥ 100k) viene dalla replica notturna.
- **Card, parte del regime**: regime e motivi, riga del Market Monitor (±4%, 25%Q, T2108, studio 20%), tabella ±4% degli ultimi 20 giorni (gg/mm, ▲ acquisti / ▼ vendite), grafico studio 20% e T2108 allegato, temi.
- **Potential trend reversal**: prima seduta con +4% > −4% dopo una fase di vendite (o il contrario); quel giorno e il successivo la card lo segnala. Verso gli acquisti il regime non limita i Focus.
- **Temi**: un titolo resta in un tema solo se l'ETF lo sovrappesa rispetto al mercato (≥ 5× e ≥ 1/3 del sovrappeso massimo); il tema si misura sui suoi ETF col punteggio a 7 fattori di Ratatouille (percentili tra gli ETF dei temi con ≥ 250k$ al giorno), stadio di Ratatouille dal punteggio e dalla sua variazione a 5 sedute (LEADING, FADING, BUILDING, SLIPPING, HOLDING, RECOVERY, WEAK, BEARISH).
- **Uso nella lista** [RONIN 16/10: "lascia fuori solo weak e bearish"]: escono solo i titoli con tema WEAK o BEARISH; senza tema in classifica nessun filtro; ordine LEADING, BUILDING, poi gli altri, poi RS. DEFENSIVE: Focus solo con tema LEADING/BUILDING (max 3). Sostituisce "fuori i temi in downtrend".

### Aggiornamento del 20/10 (dal bot di Martin, regole 2026-10-20g)
- **Il bias lo decidono le liste del pool monitorato** [ANDREA 20/10] (`jeffcoach/pool.py`, `regime.regime_pool`, `BIAS_SOURCE = "pool"`). Il pool sono i titoli liquidi dell'universo con ADR a 20 sedute ≥ 3,5% e percentile di forza relativa a 3 o 6 mesi ≥ 0,80 in un momento qualsiasi degli ultimi 6 mesi; le liste sono Leading (prezzo > EMA50 > EMA150), Lagging (il contrario) e Mediocre il resto. Punteggio: livello (quota Leading su Leading+Lagging, ≥ 70% +1, ≤ 50% −1), flusso a 5 sedute (ogni titolo che scende di una lista vale −1, di due −2, chi sale +, in quota del pool: ±10% ±1, ±20% ±2) e tendenza dei flussi giornalieri (3 su 4 oltre ±1% nello stesso verso, ±1). ≥ +2 LONG, ≤ −2 DEFENSIVE, in mezzo MIXED. Il Market Monitor e il punteggio sugli indici restano nella card come contesto, e tornano a decidere se il pool non si può calcolare.
- **Studio 20% di Pradeep come filtro dei lati** [ANDREA 20/10]: con più di 150 titoli +20% in 5 sedute il mercato è surriscaldato e oggi non si aprono long (nessun Focus, la lista resta pubblicata); con più di 100 titoli −20% la vendita è già esaurita e non si aprono short. Soglie `U20_LONG_MAX` e `D20_SHORT_MAX`.
- **Conferma dell'indice all'ingresso** [ANDREA 20/10] (`alerts.trend_60m`): long solo con il QQQ sopra la EMA50 oraria e la media in salita, short solo col QQQ sotto e la media in discesa. L'ingresso aspetta la conferma, non viene scartato: al giro dopo si riprova. Nel bot di Martin la stessa regola chiedeva anche gli ultimi due massimi e minimi di swing orari nel verso del trade; tolti il 20/10 perché pretendevano un indice già esteso, mentre un pullback si prende quando l'indice sta ritracciando (con gli swing 41 trade +62,2R, ma −0,1R togliendo i tre migliori; senza, 64 trade +135,2R e +72,9R togliendo i tre migliori). `QQQ_TREND_SWINGS` resta come interruttore.
- **Media sulle barre a 65 minuti: EMA50 al posto della SMA30** [ANDREA 20/10] (`MA65_KIND`, `MA65_LEN`). Vale dove la media 65m serviva prima: il gate `sma65` (il close daily deve stare sopra, sotto per gli short), la sezione della card e del file TradingView che divide gli Stalk sopra e sotto, la lista canale e il pullback sulla trendline negli alert di Sydney, e la riga sul grafico. I bucket da 65 minuti restano quelli di prima (sei al giorno dalle 09:30 ET, close dell'ultima barra a 5 minuti del bucket, come TradingView). Le barre a 5 minuti scaricate passano da 6 a 25 sedute (`MA65_SESSIONS`) e negli alert da 7 a 30 giorni (`MA65_LIVE_PERIOD`): la EMA50 su bucket da 65 minuti vuole almeno 50 bucket, cioè più di otto sedute, e con 25 la media è ben avviata. Il campo pubblicato si chiama ora `ma65` (`sma30_65m` resta come alias per compatibilità).
