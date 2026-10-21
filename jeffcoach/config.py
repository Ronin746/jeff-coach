"""Tutte le regole chiuse da Ronin, in un solo posto.

Ogni costante ha la fonte tra parentesi quadre. Le soglie marcate (impl.) servono
a MISURARE una regola (es. "pattern stretto"): non sono gate nuovi di Ronin e si
possono ricalibrare solo con il suo ok.

Nessun'altra parte del codice deve contenere numeri di regola.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- percorsi
HOME = Path(os.environ.get("JEFF_COACH_HOME", "/workspace/jeff-coach"))
STATE = HOME / "state"                      # cache dati + lavoro di ogni run
WATCHLISTS = HOME / "watchlists"            # liste complete (dettaglio)
LOGS = HOME / "logs"
AGREED = Path(os.environ.get("JEFF_COACH_AGREED", "/workspace/coach-agreed"))   # letto dagli alert
REMY_PIVOT_FILE = Path(os.environ.get("JEFF_COACH_REMY_FILE", "/workspace/tv-scanner/pivot30_list.txt"))
REMY_DAILY_CACHE = Path("/workspace/tv-scanner/cache/daily")   # solo lettura, simboli extra per l'universo
SECRETS_FILE = Path(os.environ.get("JEFF_COACH_SECRETS", "/home/box/agent-data/box-secrets.json"))

# Webhook: si legge il primo nome presente (env o file segreti). Mai stamparli.
ALERT_WEBHOOK_ENV = ("COACH_ALERT_DISCORD_WEBHOOK_URL", "SYDNEY_COACH_DISCORD_WEBHOOK_URL")
CARD_WEBHOOK_ENV = ALERT_WEBHOOK_ENV      # [RONIN 14/10] tutto su Sydney: il webhook di Dua non si usa più
FORBIDDEN_WEBHOOK_ENV = ("DISCORD_WEBHOOK_URL", "SYDNEY_DISCORD_WEBHOOK_URL")   # Remy: mai
ALERT_USERNAME = os.environ.get("COACH_ALERT_NAME", "Sydney")
CARD_USERNAME = ALERT_USERNAME            # [RONIN 14/10] card e riepiloghi col nome di Sydney
CARD_COLOR = 0x2ECC71          # long: bordo verde [RONIN 12/10] (era arancio #E67E22)
ALERT_COLOR = 0x2ECC71         # long: bordo verde [RONIN 12/10]
SHORT_COLOR = 0xE74C3C         # short: bordo rosso, lista e alert [RONIN 12/10]

# ---------------------------------------------------------------- universo [RONIN 04/10]
MCAP_MIN = 1e9                 # > $1 mld [RONIN 10/10] (era 500M)
ADV_MIN = 50e6                 # adv$ = sma(volume[1]*close[1], 50) >= $50M
ATR_PCT_MIN = 2.8              # Wilder ATR14 / close * 100, gate duro
EXCHANGES = ("NMS", "NYQ", "ASE", "NGM", "NCM")
EXCLUDED_INDUSTRIES = ("Biotechnology",)      # [JS hard 3] + scelta Ronin 08/10: solo Biotechnology
EXCLUDED_TICKERS = {"ADPT"}                    # biotech anche se Yahoo lo classifica altrove [METODOLOGIA §1]
# pre-filtro largo sullo screener Yahoo (il gate vero si ricalcola sui dati): non deve mai tagliare un nome buono
SCREEN_ADV_PREFILTER = 30e6

# ---------------------------------------------------------------- utili [JS] [RONIN]
EARNINGS_SESSIONS = 5          # fuori se utili nelle prossime 5 sedute, compresa quella della lista

# ---------------------------------------------------------------- gate Focus daily
RS_FOCUS_MIN = 80              # Fred6724 pine_replay [RONIN 04/10]
RS_PINE_REPLAY = (195.93, 117.11, 99.04, 91.66, 80.96, 53.64, 24.86)
SMA200_SLOPE_BARS = 5          # SMA200 oggi >= SMA200 di 5 barre fa [JS hard 7]
EXT_MAX = 4.0                  # ((close-SMA50)/SMA50*100)/ATR%  "~4x" [RONIN 01/10]
SMA5_MAX_DIST_PCT = 5.0        # |close/SMA5-1| <= ~5% (tetto) [RONIN 04/10]
EMA9_MAX_ATR = 1.5             # 0 < (close-EMA9)/ATR14 <= 1.5 ; EMA21 solo contesto [RONIN 06/10 + 08/10]
VCP_FOCUS_MAX = 25.0           # VCP Tightness <= 25 [RONIN 04/10]
VCP_LEN, VCP_ADR_LEN, VCP_BASELINE = 5, 20, 50
# ">=2 giorni di compressione" [JS hard 15] -- definizione scelta da Ronin l'08/10:
# almeno 2 delle ultime 3 barre con range% < ADR20% (un solo giorno largo non azzera i precedenti, caso PLTR)
COMPRESSION_DAYS_MIN = 2
COMPRESSION_WINDOW = 3
MA65_KIND = "ema"              # [ANDREA 20/10] media sulle barre 65m RTH: EMA50 al posto della SMA30
MA65_LEN = 50                  # (prima: SMA 30 [RONIN 06/10]). Il close daily deve stare SOPRA
MA65_SESSIONS = 25             # sedute di barre a 5 minuti da scaricare: la EMA50 oraria (7 barre al giorno) vuole piu'
#                                storico della SMA30 (50 bucket = ~8 sedute, con 25 la media e' ben avviata)
MA65_LIVE_PERIOD = "30d"       # 5m scaricati negli alert per la media 65m (con la SMA30 bastavano 7 giorni)
SMA65_LEN = MA65_LEN           # vecchio nome, tenuto per compatibilita'
BUCKET_MIN = 60                # [ANDREA 21/10] media intraday sulle barre da 1 ORA (EMA50), prima bucket da 65 minuti.
#                                Barre ancorate all'apertura delle 9:30 ET come TradingView (9:30, 10:30, ... 15:30 di mezz'ora)
MA_TF_LABEL = "1h" if BUCKET_MIN == 60 else f"{BUCKET_MIN}m"   # etichetta nei messaggi, nella card e nel grafico

# ---------------------------------------------------------------- Stalk
# Stalk = universo ok + utili ok + RS >= 80 + sopra la SMA200, con almeno un gate Focus aperto, e:
#  - NUOVO ingresso: al massimo 1 gate numerico aperto E almeno una delle due letture vede un pattern stretto
#    ("c'è il pattern, manca un gate");
#  - GIÀ IN LISTA ieri: resta in Stalk finché ha al massimo 2 gate numerici aperti (si continua a seguirlo);
#    con 3+ gate aperti, RS < 80, sotto la SMA200 o utili in finestra esce.
# (impl.) Calibrato sulle liste reali di Dua e Sydney (5-8/10): copre 35 dei 41 Stalk pubblici dell'08/10.
# Gate numerici = tutti tranne "pattern".
# ETF di settore per le statistiche del gruppo nella card (stesse misure dei titoli) [RONIN 09/10]
SECTOR_ETF = {"Technology": "XLK", "Energy": "XLE", "Consumer Cyclical": "XLY", "Healthcare": "XLV",
              "Industrials": "XLI", "Basic Materials": "XLB", "Communication Services": "XLC",
              "Consumer Defensive": "XLP", "Financial Services": "XLF", "Utilities": "XLU", "Real Estate": "XLRE"}
STALK_RS_MIN = 80
STALK_RS_THEME_MIN = 70        # RS 70-79 entra in Stalk solo se TUTTI gli altri gate sono chiusi [RONIN 04/10: tema forte]
STALK_NEW_MAX_NUMERIC_OPEN = 1
STALK_CARRY_MAX_NUMERIC_OPEN = 2

# ---------------------------------------------------------------- pattern: lettura unica [RONIN 13/10]
# Un solo metodo al posto delle letture A (Dua), B (Sydney) e C: la struttura disegnata con pivot e trendline,
# come si guarda un grafico a mano (vedi patterns.py e METODOLOGIA §6). Tre esiti:
#   "tight"   = pattern ammesso e già stretto vicino alla linea alta -> il gate pattern è chiuso (Focus possibile);
#   "forming" = pattern ammesso ma non ancora pronto (largo, lontano dalla linea, ultima barra larga...) -> Stalk;
#   "none"    = nessun pattern di continuation ammesso (niente spinta, base troppo profonda, forma esclusa, 50 persa).
# Fonti: Jeff (spinta, poi base stretta sulle medie corte; mai dopo una seduta larga), Qullamaggie (spinta 1-3 mesi,
# consolidamento ordinato che non restituisce più di metà della spinta), Kell (flag/pennant, 2B), Monis (trendline
# sui pivot, ingresso sulla rottura della linea alta), Mancini (failed breakdown). Valori già concordati con Ronin
# nelle letture precedenti; dove A/B/C dicevano cose diverse si tiene il valore indicato accanto.
PATTERN = dict(
    base_max_bars=50,          # il picco della spinta si cerca nelle ultime 50 sedute (consolidamento fino a ~2,5 mesi)
    base_min_bars=4,           # almeno 4 sedute dal picco, altrimenti sta ancora correndo (era "still trending" di B)
    shelf_max_atr=2.5,         # pausa stretta sui massimi: la base è la finestra con range <= 2,5 ATR (>= 3 sedute)
    thrust_lookback=60,        # la spinta parte dal minimo dei 60 giorni prima del picco (1-3 mesi)
    thrust_min_pct=25.0,       # spinta >= 25% ... (sostituisce il 15% in 60 barre di A e i 3 ATR in 15 giorni di B:
    thrust_min_atr=6.0,        # ... oppure >= 6 ATR    la spinta si misura PRIMA della base, non negli ultimi giorni)
    retrace_max=0.5,           # la base non restituisce più di metà della spinta [RONIN 08/10]
    depth_max_pct=30.0,        # e non scende più del 30% dal picco [RONIN 08/10: era il "30% dal massimo" di A]
    line_tol_atr=0.3,          # tolleranza delle trendline (una barra può bucarle di 0,3 ATR)
    flat_slope_atr=0.04,       # |pendenza| <= 0,04 ATR al giorno = linea piatta
    width_max_atr=3.5,         # stretto: oggi le due linee distano al massimo 3,5 ATR
    range5_max_atr=2.0,        # stretto: range degli ultimi 5 giorni <= 2 ATR (valore di B, concordato con Ronin)
    last_range_adr_max=1.3,    # stretto: l'ultima seduta non è larga, <= 1,3 ADR (Jeff: mai dopo una seduta larga)
    dist_upper_max_atr=1.5,    # vicino al pivot: close entro 1,5 ATR sotto la linea alta
    broken_above_atr=0.5,      # oltre 0,5 ATR sopra la linea = già rotto (Stalk, si aspetta il retest)
    ema20_tol_atr=0.3,         # close non sotto la EMA20 (tolleranza 0,3 ATR)
    sma50_tol_atr=0.5,         # la SMA50 si può toccare (Qullamaggie): conta come persa una chiusura oltre 0,5 ATR sotto
    sma50_max_closes_under=3,  # ... e la base è rotta con 3 chiusure così, o con il close di oggi sotto la SMA50
    channel_ok_width_atr=2.5,  # canale che sale ma stretto (<= 2,5 ATR) = gradini sui massimi, accettato
    undercut_min_atr=0.2,      # 2B / failed breakdown: minimo sotto il supporto di almeno 0,2 ATR, poi recuperato
    vol_contract_max=1.0,      # stretto: volume medio degli ultimi 5 giorni sotto la media dei 50 prima ("volume in calo",
                               # Jeff nei post per abbonati; il volume asciutto è il segnale migliore nel backtest del 10/10)
    dryup_note=0.8,            # sotto 0,8 della media la card scrive "volume drying up"
)
# Lettura D (impl., 08/10): canale rialzista lungo comprato nella PARTE BASSA del range (grafici di Ronin). Vedi channel.py.
CHANNEL = dict(
    windows=(150, 120, 100, 80, 65, 50),  # lunghezze provate per il canale (sedute): da ~2,5 a ~7 mesi
    exclude_last=(0, 5, 10, 15),  # prova anche lasciando fuori le ultime barre (rottura del bordo dopo il canale)
    pivot_k=3,                    # pivot = massimo/minimo su 3 barre per lato
    tol_atr=0.6,                  # un pivot a meno di 0,6 ATR dalla linea è un tocco
    side_tol_atr=0.75,            # le barre possono bucare la linea di 0,75 ATR ...
    max_violations=2,             # ... e al massimo 2 barre (spike) la bucano di più
    min_gap=10,                   # i due pivot che fanno la linea distano almeno 10 sedute
    min_touches_each=2, min_touches_total=6,  # tocchi = pivot sulla linea (le due linee sono parallele)
    max_width_atr=6.0,            # oltre 6 ATR non è un canale ma un trend generico (era 8; Ronin 09/10: troppi falsi canali)
    min_alternations=3,           # i tocchi devono alternarsi tra le due linee almeno 3 volte (sale e scende dentro il canale)
    min_touch_spread=0.35,        # i tocchi di ogni linea coprono almeno il 35% della durata del canale
    min_span=25,                  # il canale copre almeno 25 sedute (5 settimane)
    width_penalty=0.25,           # tra i canali trovati: -0,25 punti per ogni ATR di larghezza
    min_slope_atr=0.03,           # il canale sale di almeno 0,03 ATR per seduta
    min_rise_width=1.2,           # nel canale il prezzo è salito di almeno 1,2 volte la larghezza (scalini, non laterale)
    min_width_atr=1.8,            # largo almeno 1,8 ATR (altrimenti è la base, lettura C)
    lower_zone=0.40,              # parte bassa = sotto il 40% del range
    near_lower_atr=1.2,           # oppure a meno di 1,2 ATR dalla linea bassa
    upper_zone=0.80,              # sopra l'80% = bordo alto, esteso
    ema_touch_atr=0.35,           # il minimo di ieri è a meno di 0,35 ATR sopra la EMA21 (o sotto) ...
    ema_pullback_max_pos=0.55,    # ... e il prezzo è nella metà bassa del canale
    breakout_atr=0.3, fresh_breakout_bars=3,
    backtest_band_atr=0.8, backtest_min_break_atr=0.8,
    backtest_min_closes_above=3,  # rottura vera: almeno 3 close sopra la linea alta (+0,3 ATR), non uno spike (RBRK 09/10)
    failed_back_atr=0.5, failed_within=8,
    lost_lower_atr=0.5,
)
CHANNEL_RS_MIN = 80              # lista "canale": solo RS >= 80 [RONIN 08/10]
CHANNEL_ALERT = False            # Sydney: alert "· Channel" spenti [RONIN 21/10]; gli altri alert restano
# Trendline discendente e sua rottura ("wedge pop", Kell) [RONIN 09/10] — vedi dtl.py
DTL = dict(
    lookback=200,            # i massimi si cercano nelle ultime 200 sedute
    pivot_k=2,               # massimo = il più alto su 2 barre per lato (era 3: backtest 2017-2026, +38% linee, stessa resa)
    min_gap=8,               # tra il picco e il secondo punto almeno 8 sedute
    min_slope_atr=0.03,      # la linea scende di almeno 0,03 ATR a seduta
    tol_atr=0.3,             # un massimo può superare la linea di 0,3 ATR (spike) ...
    max_violations=3,        # ... al massimo 3 volte; i close mai
    break_atr=0.3,           # rottura = close sopra la linea di almeno 0,3 ATR (era 0,1: rotture fallite 41% -> 34%) ...
    break_atr_vol=0.1,       # ... o 0,1 ATR se quel giorno il volume è >= 1,5x la media (rottura con volume, caso MMED)
    touch_atr=0.6,           # un massimo a meno di 0,6 ATR dalla linea è un tocco
    min_touches=3,           # picco + almeno altri 2 massimi (Ronin 10/10: tolte le linee a 2 tocchi)
    min_drop_pct=15.0,       # dal picco il prezzo è sceso almeno del 15% (una vera discesa)
    min_span=20,             # la linea dura almeno 20 sedute
    break_vol_min=1.5,       # rottura in chiusura da segnalare: volume >= 1,5x la media a 50 giorni [RONIN 09/10]
    confirm_days=3,          # ... oppure confermata col volume >= 1,5x in uno dei 3 giorni dopo, sopra la linea (caso P)
    near_atr=1.0,            # "vicina": close sotto la linea entro 1 ATR (alert di rottura in seduta)
    pullback_max_days=10,    # dopo la rottura, per 10 sedute si segue il pullback (crossback e SMA30 65m)
    failed_atr=1.0,          # ricaduto più di 1 ATR sotto la linea = rottura fallita, non si segue più ...
    max_false_breaks=2,      # ... ma la linea resta valida e si aspetta la rottura vera (AAOI agosto -> ottobre) [RONIN 10/10]
    ema_touch_atr=0.3,       # crossback: il minimo torna a meno di 0,3 ATR dalla EMA9 o dalla EMA21
    live_rvol_min=1.5,       # rottura in seduta: RVOL all'ora del giorno >= 1,5 [RONIN 09/10]
    rs_min=80,               # RS minima per le liste della trendline (come il resto della lista)
)
DTL_ALERT = True               # alert Sydney sulla trendline discendente (rottura con RVOL, wedge pop) [RONIN 09/10]
CHANNEL_CHART = True           # grafico (daily con le linee del canale + 65m) allegato all'alert Channel [RONIN 09/10]
CHANNEL_POLL_SEC = 300           # la SMA30 65m live dei nomi del canale si riscarica ogni 5 minuti

# Gap al ribasso da riempire (Jeff: XLK, ESTC, NOW restano Stalk finché non riempiono il gap)
# SPENTO [RONIN 08/10 21:16: "per il momento no, bisogna lavorarci su meglio"]: si calcola ma non tocca la lista né il riepilogo
GAP_GATE_ON = False
GAP_LOOKBACK = 60                # sedute in cui si cercano i gap al ribasso
GAP_MIN_ATR = 0.10               # gap vero: massimo del giorno sotto il minimo del giorno prima, di almeno 0,1 ATR
GAP_NEAR_ATR = 3.0               # conta solo se il bordo alto del gap è entro 3 ATR sopra il close

# Reazione ritardata agli utili (PEG delayed reaction) [RONIN 08/10], lista a parte come il canale
PEG = dict(
    min_bars_ago=4, max_bars_ago=45,   # il gap è di 4-45 sedute fa (la reazione è "ritardata", al massimo ~2 mesi)
    gap_min_pct=4.0, gap_min_atr=1.0,  # apertura sopra il close prima di almeno 4% o 1 ATR ...
    vol_mult=1.5, gap_big_pct=8.0,     # ... con volume del giorno >= 1,5x la media 50 (o gap >= 8%, il volume di Yahoo a volte è basso)
    range_below_atr=0.5,               # il prezzo è nel range del PEG: dal close prima del gap (fino a 0,5 ATR sotto) ...
    range_above_atr=1.0,               # ... al massimo del giorno del gap (fino a 1 ATR sopra)
    range5_max_atr=2.5, atr5_atr20_max=0.8,   # base stretta
    sma200_tol_atr=0.3,                # mai contro la SMA200 (regola 7 di Jeff)
    rs_min=60,                         # Jeff li prende anche con RS 66 (ACN)
)

# Triangolo ascendente (in più alla base ascendente della lettura C, non al posto) [RONIN 08/10]
TRIANGLE = dict(
    windows=(60, 45, 30, 20, 15, 10), top_tol_atr=0.5, lo_tol_atr=0.35, min_top_touches=2, min_lo_touches=2,
    min_top_spread=4,                  # i tocchi del tetto distano almeno 4 sedute (mini triangolo, HPQ)
    max_spikes=2,                      # al massimo 2 barre oltre il tetto (spike), e nessun close sopra nelle ultime 3
    min_lo_slope_atr=0.03, max_lo_slope_atr=0.15,   # supporto che sale (0,03-0,15 ATR per seduta: non una V)
    min_len=15,                        # il triangolo dura almeno 15 sedute
    min_lo_share=0.5,                  # il supporto parte dalla prima metà del triangolo
    sma50_tol_atr=0.3,                 # sopra una SMA50 che non scende
    converge=0.75,                     # larghezza oggi <= 75% di quella all'inizio
    width_max_atr=3.5, dist_top_max_atr=1.5, above_top_max_atr=0.3, range5_max_atr=2.0,
)


# ---------------------------------------------------------------- forza del gruppo (impl., 08/10) [Kell, Jeff: temi e gruppi leader]
# Industria Yahoo (circa 145 gruppi). Forza del gruppo = mediana dell'RS dei suoi titoli nell'universo,
# messa in percentile tra i gruppi (0 = il più debole, 100 = il più forte). Gruppi con meno di
# GROUP_MIN_MEMBERS titoli usano il percentile del settore.
GROUP_MIN_MEMBERS = 3
# Gate sul gruppo: None = solo mostrato e usato per ordinare. Con un numero (es. 40) un nome di un gruppo
# sotto quel percentile non può essere Focus (resta Stalk).
GROUP_FOCUS_MIN_PCTL = None
# Leader alla Qullamaggie: nel top 2% dell'universo per rendimento a 1, 3 o 6 mesi.
LEADER_TOP_PCT = 2.0

# ---------------------------------------------------------------- scadenza degli Stalk portati avanti (impl., 08/10)
# Un nome resta in Stalk "per inerzia" (regola dei 2 gate aperti) al massimo per queste sedute di fila.
# Se in quel tempo non torna a soddisfare la regola dei nuovi ingressi (1 gate aperto + pattern stretto), esce.
STALK_CARRY_MAX_SESSIONS = 5

# ---------------------------------------------------------------- short [RONIN 12/10]
# Stesse regole del long sul grafico capovolto (vedi short.py). L'RS non è un gate.
SHORT = dict(
    enabled=False,             # SOSPESO [RONIN 13/10]: niente lista, card e alert short finché non si riattiva
    mirror_k=10000.0,          # prezzo capovolto = K / prezzo (K qualsiasi: conta solo per i livelli)
    # SMA200 [RONIN 12/10]: non è un gate. Sotto la SMA200 è meglio (va prima in lista e la card lo scrive), ma
    # valgono anche i titoli sopra, per esempio quelli che stanno passando da stage 2-3 a stage 4.
    sma200_gate=False,
    pre_max_numeric_open=2,    # la SMA30 65m si scarica solo per chi ha al massimo 2 gate numerici aperti (oltre a lei)
)

# ---------------------------------------------------------------- weekly [RONIN 06/10]
WEEKLY_SMA25_DAILY_MAX_PCT = 5.0   # al posto della SMA30 65m: close entro ~5% dalla SMA25 giornaliera
WEEKLY_EMA9_MAX_ATR = 1.5          # entro 1,5 ATR settimanali dalla EMA9 settimanale
# Pattern: stessa lettura unica della daily, sulle barre settimanali (soglie in ATR settimanali).

# ---------------------------------------------------------------- alert [RONIN 30/09, 04/10]
RVOL_ALERT = 0.30              # 30% della media 50gg, solo nella prima ora, Focus+Stalk
RVOL_ALERT_WINDOW_MIN = 60
ORH_MINUTES = 30               # ingresso: rottura del massimo dei primi 30 minuti, solo Focus
LOD_ATR_RONIN = 0.70           # ingresso solo se (prezzo - minimo del giorno) <= 0,70 ATR [RONIN 08/10: ora blocca, come Jeff]
ENTRY_LOD_BLOCKS = True
# RVOL richiesto per l'ingresso Focus (Jeff, post abbonati set-ott 2026) [RONIN 08/10]:
#   - controvalore medio >= 1 mld $: niente RVOL, si aspettano i primi 30 minuti;
#   - altrimenti RVOL >= soglia entro 30 minuti (ritmo: dopo 60 minuti serve il doppio); la soglia va dal 18% al 40%
#     in base al RVOL pieno della seduta prima (bassa dopo una seduta a volume contratto, alta dopo una a volume forte).
ENTRY_RVOL_REQUIRED = True
ENTRY_NO_RVOL_ADV = 1e9
ENTRY_RVOL_MIN, ENTRY_RVOL_MAX = 0.18, 0.40
ENTRY_RVOL_PREV_LO, ENTRY_RVOL_PREV_HI = 0.40, 1.25   # RVOL pieno di ieri: <=0,40 -> 18%, >=1,25 -> 40%, in mezzo lineare
MEGA_LIQUID_ADV = 2e9          # RVOL soft
# Distanza massima dall'ORH per mandare l'ingresso (anti-inseguimento, hard rule 10 "never chase").
# None = disattivo (comportamento attuale). Da attivare solo se Ronin lo chiede.
CHASE_MAX_ATR_ABOVE_ORH = None
POLL_SEC = 90
# Dopo un alert su un titolo, nessun altro alert sullo stesso titolo per questi minuti (qualsiasi tipo) [RONIN 12/10]
ALERT_COOLDOWN_MIN = 60

# ---------------------------------------------------------------- temi [RONIN 13/10]
# Mappa dei temi come in Martin-coach (themes_map.py): basket "🐭Baskets" di TradingView, ETF tematici del foglio di
# Andrea con le partecipazioni dal repo di NEL, modifiche a mano (state/themes/manuale.json); industria Yahoo come riserva.
THEME_ETF_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1OSC1ovj4y5I-Yb_xBsMNvexgAOSUbLJRzbQU9W9uCNM/export?format=csv&gid=305077282"
THEME_ETF_HOLDINGS_URL = "https://raw.githubusercontent.com/i-manage-risk/NEL/main/data/etf_holdings_cache.json"
# [RONIN 21/10, Andrea, come Martin] temi = basket di Lone Stock Trader (data/themes/lst_baskets.json, aggiornati il
# lunedì alle 01:00 dal server); punteggio del basket = media equal-weight del 7-factor di tutti i suoi titoli; grafico
# RS settimana / mese dei basket in testa alla sezione temi della card.
THEME_SOURCE = "lst"
LST_MIN_SCORED = 3               # un basket entra in classifica con almeno 3 titoli con storia sufficiente
THEME_RANK_ROWS = 15             # basket nella classifica complessiva della card
THEME_DV_MIN = 75e6              # un titolo conta in un tema con controvalore medio >= 75M$ (come Martin)
THEME_MIN_MEMBERS = 3            # un tema entra in classifica con almeno 3 titoli liquidi
# Trend del tema: indice a pesi uguali dei suoi titoli (mediana delle variazioni giornaliere).
#   uptrend   = indice > EMA50 > EMA150 e EMA50 in salita su 5 sedute
#   downtrend = indice < EMA50 < EMA150  -> i titoli di quel tema ESCONO da Focus e Stalk [RONIN 13/10]
THEME_EMA_FAST, THEME_EMA_SLOW, THEME_SLOPE_BARS = 50, 150, 5
THEME_EXCLUDE_DOWNTREND = True
# Tema "leading": in uptrend e nel 30% più alto della classifica (punteggio = media dei ranghi di rendimento a 1 e
# 3 mesi, forza rispetto all'S&P a 1 mese, quota di titoli Leading e quota sopra la EMA21). Premio: va prima in lista,
# vince i posti quando il regime limita i Focus, e la card lo segna [RONIN 13/10].
THEME_LEADING_PCTL = 0.70

# ---------------------------------------------------------------- regime di mercato [RONIN 13/10] (come Martin-coach)
# Market Monitor di Stockbee letto dal repo pubblico di NEL (regole NEL "marketRead"); punteggio sugli indici come
# contesto e riserva se manca la riga del giorno (QQQ e IWM: trend EMA9/21 e EMA50; stato MM ±1; T2108 a 5 sedute ±1).
MM_URLS = ("https://raw.githubusercontent.com/i-manage-risk/NEL/main/outputs/breadth_market_monitor.json",
           "https://i-manage-risk.github.io/NEL/outputs/breadth_market_monitor.json")
MM_DEF_DOWN4, MM_DEF_RATIO10, MM_DEF_RATIO5 = 300, 0.85, 0.70
MM_EXP_RATIO10, MM_EXP_RATIO5, MM_EXP_UP4, MM_EXP_DOWN4 = 1.25, 1.10, 180, 150
MM_T2108_DELTA = 5.0
MM_BIAS = {"Expansion": "LONG", "Defensive": "SHORT", "Mixed": "MIXED"}
REGIME_INDICES = ("QQQ", "IWM")
BIAS_LONG_MIN, BIAS_SHORT_MAX = 2, -2
BIAS_SOURCE = "pool"            # [ANDREA 20/10] "pool" = liste del pool monitorato (regime.regime_pool, come il bot
#                                 di Martin dal 17/10); "mm" = Market Monitor di Stockbee come prima. Senza il pool
#                                 si torna da sé al Market Monitor.
# Gestione (JeffCoach è solo long, lo short è sospeso):
#   LONG  (Expansion): tutti i Focus;
#   MIXED (Mixed): al massimo 3 Focus, i migliori (tema leading prima, poi forza del tema, poi RS); gli altri in Stalk;
#   SHORT (Defensive): niente Focus normali; restano al massimo 3 Focus "against the regime", solo con tema leading
#                      in uptrend, e i loro alert portano la nota "against the regime".
REGIME_MIXED_MAX_FOCUS = 3
REGIME_DEFENSIVE_MAX_FOCUS = 3

# ---------------------------------------------------------------- aggiornamento come Martin-coach [RONIN 16/10]
# Market Monitor letto come Pradeep Bonde (Martin 2026-10-16b..h): "pradeep" o "nel" (regole NEL di prima).
MM_READ = "pradeep"
MM_LABEL = {"Expansion": "Breakouts work", "Mixed": "Be selective", "Defensive": "Breakouts fail"}
PB_T2108_OVERSOLD = 20.0            # T2108 < 20: "start getting bullish"
PB_T2108_EXTREME = 10.0             # < 10: "extremely bullish"
PB_T30A = 30                        # 30 sedute dopo un T2108 < 20
PB_UP20_CAUTION = 200               # studio 20%: +20% in 5 sedute >= 200 = storno probabile entro 5-10 sedute
PB_DOWN20_CAUTION = 200             # -20% in 5 sedute >= 200 = vendita estrema, niente "Breakouts fail"
PB_UP20_WINDOW = 10
PB_FLOW_DAYS = 5                    # acquisti/vendite: saldo dei giorni ±4% nelle ultime 5 sedute
PB_FLOW_MIN = 2
PB_T2108_EXTENDED = 65.0
REVERSAL_DAYS = 2                   # potential trend reversal: il giorno dell'inversione del flusso ±4% e il successivo;
#                                     JeffCoach (solo long): con l'inversione verso gli acquisti il regime non limita i Focus
# Temi come Martin (16/10): classifica sugli ETF del tema col punteggio a 7 fattori di Ratatouille, stadi di Ratatouille,
# titolo in un tema solo se l'ETF lo sovrappesa rispetto al mercato.
THEME_ETF_DV_MIN = 250e3
BASKET_WEIGHTS = {"price_performance": 0.25, "bullish_candles": 0.15, "ma_alignment": 0.15, "trend_consistency": 0.15,
                  "volatility": 0.10, "volume": 0.10, "relative_strength": 0.10}
BASKET_BENCHMARK = "SPY"
STAGE_LONG = ("LEADING", "BUILDING")      # temi premiati (prima in lista; i soli ammessi nei Focus in DEFENSIVE)
STAGE_LONG_EXCLUDE = ("WEAK", "BEARISH")  # [RONIN 16/10] fuori dalla lista long solo i temi WEAK e BEARISH
THEME_OVERWEIGHT_MIN = 5.0
THEME_OVERWEIGHT_FRAC = 1 / 3
THEME_MEMBERSHIP = "sovrappeso-5-1/3"     # se cambia, la mappa si ricostruisce

# ---------------------------------------------------------------- pool monitorato e sue liste [ANDREA 20/10]
# Portato dal bot di Martin (pool.py + regime.pool_state). Soglie tarate là sulle 99 live di Martin: qui l'universo è
# un altro, i valori sono il punto di partenza e si ritarano col replay.
POOL_DV_RANK = 0.70                 # dollar volume a 20 sedute nel 30% più alto dell'universo
POOL_RS_MIN = 0.80                  # forza relativa a 3 o 6 mesi almeno all'80° percentile negli ultimi 6 mesi
POOL_LIQ_RS = 50e6                  # la forza relativa si misura tra i titoli con almeno 50M$/giorno
POOL_ADR_MIN = 3.5                  # ADR a 20 sedute almeno 3,5%
POOL_N = None                       # nessun tetto al numero di titoli del pool
POOL_MIN_UP_LOW = None              # (spento) minimo di salita dal minimo a 52 settimane
POOL_ADR_RANK = None                # (spento) ADR in percentile al posto della soglia fissa
POOL_BIG_RANK = None                # (spento) percentile delle sedute da +4% in 60 giorni
POOL_SHARE_GOOD = 70.0              # Leading / (Leading+Lagging) del pool: >= 70% = +1 ...
POOL_SHARE_BAD = 50.0               # ... <= 50% = -1
POOL_FLOW_MIN = 10.0                # flusso a 5 sedute in % del pool: ±10% = ±1 ...
POOL_FLOW_STRONG = 20.0             # ... ±20% = ±2
POOL_FLOW_DAY_MIN = 1.0             # tendenza: 3 flussi giornalieri su 4 oltre ±1% nello stesso verso = ±1
POOL_TREND_DAYS = 4                 # quante sedute guarda la tendenza dei flussi
POOL_TREND_MIN = 3                  # quante di quelle devono andare nello stesso verso
POOL_SCORE_GOOD = 2                 # punteggio del pool: >= +2 mercato in espansione ...
POOL_SCORE_BAD = -2                 # ... <= -2 mercato difensivo
# studio 20% di Pradeep come filtro degli ingressi [ANDREA 20/10, dal bot di Martin]
U20_FILTER = True
U20_LONG_MAX = 150                  # oltre 150 titoli +20% in 5 giorni: niente nuovi long (mercato surriscaldato)
D20_SHORT_MAX = 100                 # oltre 100 titoli -20% in 5 giorni: niente nuovi short
# conferma del trend del QQQ all'ingresso [ANDREA 20/10, dal bot di Martin]
QQQ_GATE = True                     # l'ingresso aspetta che il QQQ sia nel verso del trade (non lo scarta)
QQQ_TREND_SYMBOL = "QQQ"
QQQ_TREND_MA = ("ema", 50)          # media oraria che definisce il trend del QQQ
QQQ_TREND_SWINGS = False            # [20/10g di Martin] massimi e minimi di swing orari: chiedevano un indice già
#                                     esteso e scartavano i pullback buoni, quindi restano spenti
H60_SLOPE_BARS = 5                  # barre orarie per la pendenza della media
SWING_60M_K = 3                     # barre a destra e sinistra per un massimo/minimo di swing (solo con QQQ_TREND_SWINGS)

# ---------------------------------------------------------------- banda d'ingresso [20/10h di Martin, ANDREA 21/10]
# Dal bot di Martin (martincoach/config.py, versione 2026-10-20h): il prezzo d'ingresso deve stare fra lo 0,05% e
# l'1,0% dalla parte giusta del livello del trigger (sopra per i long, sotto per gli short). Qui il livello e' quello
# della rottura (ORH/ORL, pivot, media 65m): sotto lo 0,05% si sta entrando sul livello stesso, oltre l'1,0% si
# insegue. Fuori banda l'ingresso aspetta, il trigger resta libero. Studio su Martin 20/07-16/10: ingressi sul
# livello o oltre -0,23R di media, anticipati di 0,07-0,84% +1,43R.
ENTRY_BAND = True
ENTRY_DIST_MIN_PCT = 0.05
ENTRY_DIST_MAX_PCT = 1.0


def entry_dist_pct(price: float, level: float, side: str = "long") -> float:
    """Distanza in % del prezzo dal livello, positiva dalla parte del trade (sopra per i long, sotto per gli short)."""
    return (level / price - 1) * 100 * (1 if side == "short" else -1)


def in_entry_band(price: float, level: float, side: str = "long") -> bool:
    if not ENTRY_BAND or not level or not price:
        return True
    return ENTRY_DIST_MIN_PCT <= entry_dist_pct(price, level, side) <= ENTRY_DIST_MAX_PCT
