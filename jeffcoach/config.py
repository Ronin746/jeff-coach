"""Tutte le regole del bot Martin Luk, in un solo posto.

Ogni costante ha la fonte tra parentesi quadre:
  [ML ...]    regola di Martin Luk (live, articoli, intervista) — vedi METODOLOGIA_MARTIN.md
  [RONIN ...] scelta di Andrea
  (impl.)     soglia che serve a MISURARE una regola (non è una regola nuova): si ricalibra solo con l'ok di Andrea
Nessun'altra parte del codice deve contenere numeri di regola. Ogni modifica va scritta nel registro
di METODOLOGIA_MARTIN.md (data, regola, motivo).
"""
from __future__ import annotations

import os
from pathlib import Path

RULES_VERSION = "2026-10-28b"   # si aggiorna a ogni modifica di questo file (finisce in ogni trade del giornale)

# ---------------------------------------------------------------- percorsi
HOME = Path(os.environ.get("JEFF_COACH_HOME", Path(__file__).resolve().parent.parent / "data"))
STATE = HOME / "state"              # cache e lavoro di ogni run (non tutto va su git)
LISTS = HOME / "lists"              # lista del giorno: today.json, <data>.json, dettaglio, card, txt TradingView
HISTORY = HOME / "history"          # storico liste e temi (serve a breadth, passaggi di lista, temi in salita)
JOURNAL = HOME / "journal"          # giornale dei trade simulati: file a parte [RONIN 13/10]
REPORTS = HOME / "reports"
ALERTS_STATE = HOME / "alerts"      # alert già mandati (scritto solo dal server)
LOGS = HOME / "logs"

# Webhook: unico canale per watchlist e alert, bot "Dua" [RONIN 13/10]. Mai stamparlo né scriverlo nel repo.
WEBHOOK_ENV = ("LISA_DISCORD_WEBHOOK_URL",)
BOT_NAME = os.environ.get("JEFF_COACH_NAME", "Dua")
CARD_COLOR = 0x8E44AD
ALERT_COLOR = {"long": 0x2ECC71, "short": 0xE74C3C, "info": 0xF1C40F}   # long bordo verde, short rosso, anche livello e uscite [RONIN 13/10]

# ---------------------------------------------------------------- universo [ML]
MCAP_MIN = 1e9                      # prefiltro screener (impl.): i titoli sotto 1 mld raramente hanno 100M$ al giorno
EXCHANGES = ("NMS", "NYQ", "ASE", "NGM", "NCM")
SCREEN_DV_PREFILTER = 50e6          # prefiltro largo sullo screener (prezzo × volume medio 3 mesi)
DV_MIN = 100e6                      # dollar volume medio minimo per entrare in lista [ML: soglia 100M, liste divise a 500M]
DV_TIER = 500e6                     # sezione "alta liquidità" [ML set 2026]
SHORT_DV_MIN = 50e6                 # short: liquidità minima per lista, Focus e ingresso [RONIN 14/10: 75M; 16/10: 50M]
LONG_DV_MIN = 50e6                  # long: liquidità minima per candidati, Focus e ingresso [RONIN 16/10, Andrea: 50M anche per i long]
DV_TRADE_MIN = 200e6                # minimo per aprire un trade (alert/giornale) [ML mag 2026: soglia alzata a ~200M]
DV_DAYS = 5                         # media del dollar volume sugli ultimi 5 giorni [ML]
PRICE_MIN = 5.0                     # sotto 5$ size ridotta/esclusi [ML 2024]
ADR_LEN = 20
ADR_MIN = 3.5                       # ADR% minimo per un Focus (impl.: "preferisce >5%, non è rigido") [ML]
ADR_MIN_LARGE = 2.0                 # long e short su titoli con almeno ADR_LARGE_DV al giorno: ADR minimo 2% (TSLA, NVDA) [RONIN 16/10]
ADR_LARGE_DV = 1e9
EXCLUDED_INDUSTRIES = ("Biotechnology", "Utilities—Regulated Electric", "Utilities—Diversified",
                       "Utilities—Regulated Gas", "Utilities—Regulated Water", "Tobacco",
                       "Beverages—Non-Alcoholic", "Household & Personal Products", "Packaged Foods")  # [ML: niente utility/staples/biotech]
EXCLUDED_TYPES = ("ETF",)           # gli ETF sono solo contesto, mai idee

# ---------------------------------------------------------------- medie [ML]
EMA_FAST, EMA_MID, EMA_SLOW, EMA_LONG = 9, 21, 50, 150
INDICES = ("QQQ", "IWM", "SPY")
SECTOR_ETFS = ("SOXX", "IGV", "XLF", "XLE", "XLV", "XLI", "XBI", "ARKK", "UFO", "CIBR", "URA", "QTUM", "BLOK")

# ---------------------------------------------------------------- liste Leading / Mediocre / Lagging [ML 12/03/2026]
# Leading = close > EMA50 e EMA50 > EMA150 ; Lagging = close < EMA50 e EMA50 < EMA150 ; Mediocre = il resto.

# ---------------------------------------------------------------- scan [ML]
POTENT_TOP = 40                     # migliori del giorno prima (ritorno 1g), con close > EMA50 [ML mar 2026]
POTENT_MIN_RET = 4.0                # % minima per entrare nel potent (impl.)
LEADER_TOP = 50                     # weekend: migliori per ritorno a ~21 sedute [ML]
LEADER_DAYS = 21
PREMARKET_GAP_MIN = 5.0             # gap pre-market minimo % [ML: EP con gap ≳5%]

# ---------------------------------------------------------------- livelli (confluenza) (impl.)
SWING_K = 3                         # pivot: massimo/minimo di 2k+1 barre
SWING_LOOKBACK = 90                 # sedute in cui cercare swing e ancoraggi AVWAP
LEVEL_CLUSTER_PCT = 0.8             # livelli entro questa % si sommano in una confluenza
LEVEL_MAX_DIST_ADR = 1.0            # il livello deve essere entro 1 ADR dal close (il pullback è vicino)
CONFLUENCE_MIN = 3                  # [RONIN 20/10b, Andrea] mai i setup con 2 livelli (studio 20/07-16/10: long -17R)
# alert "al livello" e ingresso solo vicino al livello, dopo un tocco recente e un'inversione [RONIN 14/10]
# avviso di avvicinamento [RONIN 14/10]: short verso la resistenza, long verso il supporto; con bias LONG anche il long
# verso la resistenza sopra (massimo a 10 sedute entro 1 ADR) per un possibile breakout, e un avviso quando la rompe
APPROACH_PCT = 1.5                  # entro l'1,5% (o 0,4 ADR, il minore) dal livello
APPROACH_ADR_FRAC = 0.4
BREAKOUT_LOOKBACK = 10              # livello di breakout: massimo delle ultime 10 sedute ...
BREAKOUT_MAX_DIST_ADR = 1.0         # ... se è entro 1 ADR sopra il close
BREAKOUT_ALERT_BIASES = ()          # spento: da rivedere con Andrea (prima ("LONG",))
TOUCH_LOOKBACK_MIN = 30             # il tocco del livello deve essere negli ultimi 30 minuti
LEVEL_NEAR_PCT = 1.0                # prezzo entro l'1% (o 0,25 ADR, il minore) dal livello per avviso e ingresso
LEVEL_NEAR_ADR_FRAC = 0.25
LEVEL_TOUCH_PCT = 0.5               # alert "livello raggiunto": prezzo entro lo 0,5% [design 12/10]

# ---------------------------------------------------------------- multi-edge (META) [RONIN 22/10, Andrea; J Law, serie METS]
# Ogni candidato riceve cinque edge (jeffcoach/edges.py): M&T momentum e trend, S&R supporti e resistenze multi-timeframe,
# PA/VOL candele, price action e volume, MTF weekly e daily concordi, RS forza/debolezza relativa a 1 settimana-1 mese o
# rotazione del gruppo. J Law EP1: si entra dove più edge sono d'accordo, almeno 2-3; più edge = meno trade, più probabilità.
# Dua (regole di Martin) li tiene spenti; li accende l'istanza multi-edge (JEFF_COACH_META=1, in fondo al file).
META_EDGES = False                  # calcola gli edge e li mostra in card, alert e giornale
META_RANK = False                   # ordine di watchlist e Focus: prima il numero di edge, poi il punteggio di sempre
META_FILTER = False                 # Focus solo con almeno META_MIN_EDGES edge (gli altri restano in tracking)
META_MIN_EDGES = 3                  # [J Law EP1: almeno 2-3 edge]
META_RANK_MODE = "count"            # "count": tutti e cinque gli edge contano uguale; "side": contano solo quelli del lato
META_SIDE_EDGES = {"long": ("SR", "PV", "MTF", "RS"), "short": ("SR", "PV", "MTF", "RS")}   # [RONIN 22/10d, Andrea] gli stessi 4 per i due lati, M&T solo scritto   # studio 22/10 (replay 24/08-21/10, scelti sugli stessi
#                                     dati): long S&R +0,99R contro +0,08R e PA/VOL +1,05 contro +0,41; short MTF +1,35 contro
#                                     -0,15 e RS +0,75 contro +0,42; M&T peggiora su tutti e due i lati (titoli già tirati)
# trendline e canali paralleli sul daily, in scala logaritmica (jeffcoach/trendlines.py) [RONIN 22/10, Andrea;
# J Law EP2: trendline per almeno 2 swing, canale parallelo] (impl.)
TL_LOOKBACK = 120                   # swing degli ultimi 6 mesi
TL_PIVOT_K = 3                      # swing = massimo/minimo di 7 barre (come SWING_K)
TL_MIN_SPAN = 10                    # ancoraggi distanti almeno 10 sedute
TL_TOL_ADR = 0.25                   # tolleranza di tocchi e chiusure: 0,25 ADR
TL_MIN_TOUCHES = 2                  # trendline valida con 2 swing (3 o più = più solida)
TL_CHANNEL_MIN_TOUCHES = 2          # canale solo se anche la parallela tocca almeno 2 swing
TL_CHART = False                    # grafico daily degli alert in scala log con trendline e canali (bianchi)
TL_CONFIRMED_TOUCHES = 3            # segno di trend (M&T): trendline confermata da almeno 3 swing [J Law EP2]
# supporti e resistenze orizzontali, linee o aree (jeffcoach/orizzontali.py) [RONIN 23/10, Andrea] (impl.)
HZ_LOOKBACK = 300                   # swing degli ultimi ~14 mesi
HZ_PIVOT_K = 2                      # swing: massimo/minimo di 5 barre (doppi massimi e ritest compresi)
HZ_TOL_ADR = 0.5                    # tocchi dello stesso livello: entro 0,5 ADR l'uno dall'altro
HZ_MIN_TOUCHES = 2
HZ_REACT_BARS = 10                  # reazione dello swing: quanto si allontana il prezzo in 10 barre prima o dopo ...
HZ_REACT_ADR = 3.0                  # ... un tocco vale 1 se si allontana di almeno 3 ADR (meno: in proporzione)
HZ_ROLE_BONUS = 1.0                 # massimi e minimi nello stesso livello (cambio di ruolo)
HZ_RECENCY_DAYS = 60                # recenza dell'ultimo tocco (0-1, mezza vita ~40 sedute)
HZ_CROSS_PENALTY = 0.25             # ogni attraversamento netto delle chiusure oltre i primi HZ_CROSS_FREE toglie 0,25
HZ_CROSS_FREE = 2                   # (rotto una volta e ripreso, o resistenza che diventa supporto, è normale)
HZ_MIN_SCORE = 3.0                  # solo livelli significativi: 3 swing veri, o 2 con il cambio di ruolo [Andrea 23/10:
#                                     "evita un numero eccessivo di linee, devono essere significative"]
HZ_GAP_ADR = 1.0                    # due livelli a meno di 1 ADR: resta il più forte
HZ_ZONE_MIN_ADR = 0.35              # tocchi sparsi per almeno 0,35 ADR: area invece di linea
HZ_MAX_LEVELS = 30                  # tutti i livelli validi: il grafico mostra quelli nella sua scala
HZ_STRONG_TOUCHES = 3               # con almeno 3 tocchi il livello pesa come un weekly nell'edge S&R
HZ_CHART_MAX = 5                    # sul grafico al massimo 5 livelli, i più forti tra quelli nella sua finestra ...
HZ_CHART_GAP_ADR = 1.5              # ... ad almeno 1,5 ADR l'uno dall'altro
HZ_CHART = False                    # linee e aree sul grafico degli alert (le accende l'istanza multi-edge)
# weekly, per i livelli di mesi e anni prima [RONIN 23/10, Andrea: "usa anche il timeframe weekly e daily su una più
# ampia scala"] (impl.): settimane fatte dal daily
HZ_W_LOOKBACK = 260                 # ultime 260 settimane (~5 anni, quanto c'è di storico)
HZ_W_PIVOT_K = 2                    # swing weekly: massimo/minimo di 5 settimane
HZ_W_TOL_ADR = 1.0                  # tocchi dello stesso livello entro 1 ADR daily
HZ_W_REACT_BARS = 6                 # reazione in 6 settimane ...
HZ_W_REACT_ADR = 8.0                # ... di almeno 8 ADR daily per un tocco pieno
HZ_W_RECENCY = 26                   # recenza in settimane
HZ_W_ZONE_MIN_ADR = 0.7             # area se i tocchi sono sparsi per almeno 0,7 ADR
HZ_W_BONUS = 1.0                    # un livello weekly vale un punto in più di uno daily
DAILY_HISTORY_DAYS = 620            # giorni di daily scaricati per la lista (l'istanza multi-edge ne prende ~5 anni)
CHART_DAILY_DAYS = 420              # giorni di daily per il grafico degli alert (idem)
MTF_REQUIRE = {"long": ("H", "D"), "short": ("D",)}  # timeframe obbligatori nell'edge MTF [RONIN 22/10e long 1h+1d;
#                                     23/10a short solo 1d, Andrea: "rimuovi la MTF necessaria dell'1h per lo short"]
# M&T [J Law EP2 trend: swing, medie, trendline, canali; EP3 momentum] (impl.)
MT_WINDOW = 20                      # sedute per candele e candele grandi
MT_UP_SHARE = 0.55                  # sedute in rialzo (in ribasso per gli short) almeno il 55%
MT_BIG_RANGE_ADR = 1.5              # candela grande: range di almeno 1,5 ADR ...
MT_BIG_VOL = 1.5                    # ... volume di almeno 1,5 volte la media a 50 sedute ...
MT_BIG_CLOSE_POS = 0.7              # ... chiusura nel 30% alto della candela (basso per gli short)
MT_BIG_MIN = 1                      # almeno una nelle ultime MT_WINDOW sedute
MT_UDV_MIN = 1.2                    # volume dei giorni in rialzo / volume dei giorni in ribasso, 50 sedute (inverso per gli short)
MT_EMA21_DAYS = 20
MT_EMA21_WRONG_MAX = 2              # al massimo 2 chiusure sotto la EMA21 in 20 sedute (sopra per gli short): pullback sani
MT_TREND_MIN = 2                    # edge M&T: almeno 2 segni di trend su 4 (struttura, medie, trendline, canale) ...
MT_MOM_MIN = 3                      # ... e 3 di momentum su 5 (sedute, gap aperti, candele grandi, volumi, tenuta della 21)
# S&R multi-timeframe (impl.)
SR_TF_WEIGHT = {"W": 1.5, "D": 1.0, "H": 0.5}   # peso dei livelli per timeframe [RONIN 22/10, Andrea: "maggiore importanza
#                                                 ai timeframe daily e weekly"]
SR_EDGE_MIN_W = 4.0                 # edge S&R: livelli nella zona con peso di almeno 4 (es. 3 daily + 1 weekly) ...
SR_REQUIRE_WEEKLY = True            # ... con almeno un livello weekly nella zona [RONIN 22/10, Andrea: S&R "anche MTF"]
SR_TEST_DAYS = 20                   # test del livello nelle ultime 20 sedute ...
SR_TEST_TOL_ADR = 0.25              # ... (minimo entro 0,25 ADR dal livello, massimo per gli short) ...
SR_MAX_TESTS = 3                    # ... dal 3° test il livello è debole [J Law EP3: test ripetuti indeboliscono il supporto]
SR_WEEKLY_PIVOT_K = 2               # swing weekly: massimo/minimo di 5 settimane ...
SR_WEEKLY_LOOKBACK = 52             # ... nell'ultimo anno
SR_EXTRA_IN_CONFLUENCE = False      # livelli nuovi (EMA150, weekly, trendline) anche nella confluenza di base del candidato
# PA/VOL [J Law EP3: setup = prezzo e volume che si stringono nella correzione; pullback sano] (impl.)
PV_LOOKBACK = 15                    # inizio del pullback: massimo (minimo per gli short) delle ultime 15 sedute
PV_DRY_RATIO = 0.8                  # volume medio del pullback sotto l'80% di quello delle 10 sedute di salita
PV_TIGHT_ADR = 0.8                  # ultime 3 candele con range medio sotto 0,8 ADR (o inside day)
PV_DIST_DAYS = 10                   # distribuzione nel pullback (ultime 10 sedute al massimo): ribasso con ...
PV_DIST_VOL = 1.5                   # ... volume di almeno 1,5 volte la media a 50 sedute ...
PV_DIST_CLOSE_POS = 0.35            # ... e chiusura nel 35% basso (per gli short: accumulo, rialzo con chiusura nel 35% alto)
PV_WICK_BODY = 2.0                  # pin bar: coda di almeno 2 corpi ...
PV_WICK_RANGE = 0.5                 # ... e di metà del range ...
PV_PIN_CLOSE_POS = 0.6              # ... chiusura nel 40% alto (basso per gli short)
PV_MIN_SIGNS = 2                    # edge PA/VOL: nessuna distribuzione e 2 segni su 3 (volume asciutto, candele strette, candela)
# RS a 1 settimana-1 mese e rotazioni [RONIN 22/10, Andrea] (impl.)
RS_EDGE_RS21_LONG_MAX = 21.0        # long: forza a 1 mese oltre +21 non conta [RONIN 20/10b: studio, oltre +21 = -24R]
RS_EDGE_ROT_RS5 = 2.0               # rotazione: titolo che batte il QQQ di 2 punti in una settimana (perde per gli short) ...
RS_EDGE_QUAD_LONG = ("Improving", "Strong")     # ... con il gruppo in questi quadranti del grafico RS settimana/mese ...
RS_EDGE_QUAD_SHORT = ("Weakening", "Weak")      # ... (per gli short)

# ---------------------------------------------------------------- setup long [ML]
LONG_EXT_EMA9_MAX_PCT = 15.0        # oltre il 15% sopra la EMA9 = esteso (niente nuovi long) [ML: trim a ~15% sopra la 9]
LONG_REQUIRE_EMA9_GT_21 = True      # trend: 9 > 21 e 21 in salita [ML]
LONG_EMA21_SLOPE_BARS = 5
# consonanza dei timeframe [RONIN 16/10, Andrea; ML: weekly/daily danno la direzione, il 60m conferma]: il daily è
# obbligatorio (regole del candidato); weekly contrario = TF_WEEKLY_AGAINST punti, weekly e 60m concordi = +TF_FULL_BONUS;
# all'ingresso il 60m deve essere nella direzione del trade (prezzo sotto la EMA9 oraria per gli short, sopra per i long)
WEEKLY_EMA9_TOL_ADR = 0.5           # ammesso anche appena oltre (entro 0,5 ADR) se la 9 weekly va già nella direzione del
#                                     trade (in discesa per gli short, in salita per i long) [RONIN 17/10, Andrea]
WEEKLY_EMA9_REQUIRED = True         # consonanza weekly obbligatoria [RONIN 17/10, Andrea: "rimetti la consonanza con il weekly,
#                                     in particolare della 9 EMA"]: long con il close weekly sopra la EMA9 weekly, short sotto
TREND_TF = "ema50d"                # [RONIN 17/10i, Andrea] consonanza di fondo sulla EMA50 daily e la sua inclinazione al
#                                     posto della EMA9 weekly ("weekly_ema9" = regola di prima)
EMA50D_TOL_ADR = 0.5                # appena oltre la 50 (entro 0,5 ADR) ammesso se la 50 va già nella direzione del trade
TF_WEEKLY_AGAINST = -0.5
TF_FULL_BONUS = 0.5
TF_60M_TRIGGER = True
H60_MODE = "ema50"                  # "ema50" (17/10d) o "ema9_21" (17/10a), per i confronti nel replay
H60_SLOPE_BARS = 5                  # pendenza della EMA50 oraria su 5 barre [RONIN 17/10]
H60_TOL_ADR = 0.25                  # il prezzo può superare la 50 oraria di 0,25 ADR (overshoot del livello)
MIN_TREND_R2 = 0.30                 # linearità del trend: R² del log del prezzo, il migliore tra 42, 63 e 126 sedute;
#                                     sotto 0,30 il titolo è fuori (es. WRBY 0,02) [RONIN 16/10, Andrea]
FAKEOUT_WATCH = False               # [20/10a, Andrea: "solo pullback short e pullback long"] (prima True)
FAKEOUT_MAX = 40                    # breakout/breakdown sul livello (+ 60m girato) [RONIN 16/10, Andrea]
STRETCH_EMA9_ADR = 1.5              # "troppo esteso" (es. LITE) [RONIN 16/10, Andrea]: oltre 1,5 ADR dalla EMA9 nella direzione
#                                     del trade → fuori (long e short); solo l'estensione dalla 9 ("e basta")
ZONE_ADR_FRAC = 0.5                 # livelli nella zona: entro 0,5 ADR dal livello di confluenza [RONIN 16/10]
ZONE_LEVEL_WEIGHT = 0.25            # punteggio: +0,25 per ogni livello nella zona oltre quelli della confluenza
VOL10_MIN = 500_000                 # [RONIN 20/10c, Andrea] volume medio a 10 sedute almeno 500k azioni (oltre ai 50M$)
QQQ_GATE = True                     # [RONIN 20/10c-d, Andrea] ingresso long solo con QQQ in trend a 60m (EMA50 oraria, HH/HL) e su un
#                                     suo supporto daily; short: QQQ consonante al ribasso e su una resistenza
QQQ_GATE_TREND = True               # parte "trend a 60m" della conferma del QQQ
QQQ_GATE_LEVEL = False              # [20/10e, Andrea] tolta: col livello 14 trade in 3 mesi; solo trend 36 trade +52R
U20_FILTER = True                   # [20/10e, Andrea] studio 20% come filtro dei lati
U20_LONG_MAX = 150
D20_SHORT_MAX = 100
QQQ_TREND_MA = ("ema", 50)          # media oraria del trend del QQQ: ("ema", 50) o ("sma", 30)
QQQ_TREND_SWINGS = False            # [20/10g, Andrea] massimi e minimi di swing orari nella definizione di trend:
#                                     chiedevano un QQQ già esteso (in un pullback gli ultimi swing sono contrari al
#                                     trade) e scartavano i trade buoni. Con swings: 41 trade +62,2R, ma -0,1R senza i
#                                     3 migliori; senza: 64 trade +135,2R, +72,9R senza i 3 migliori, 33% vincenti
SWING_60M_K = 3                     # swing a 60m: massimo/minimo più alto/basso di 3 barre per lato
QQQ_LEVEL_ADR = 0.25                # "su un livello": il QQQ ha toccato oggi un suo livello entro 0,25 ADR e il prezzo è
QQQ_LEVEL_NEAR_ADR = 0.5            # ancora entro 0,5 ADR da quel livello
LONG_MAX_EXT_SMA50_ATR = 5.0        # [RONIN 20/10b, Andrea] long entro 5 ATR dalla SMA50 daily (entro 4 meglio: bonus)
LONG_EXT50_BONUS_ATR = 4.0
LONG_EXT50_BONUS = 0.5
STREAK_FILTER = True                # [RONIN 20/10b, Andrea] niente titoli con 4+ sedute di fila nel verso del trade ...
STREAK_DAYS = 4
STREAK_MIN_ADR = 2.0                # ... e un movimento di almeno 2 ADR ...
BASE_MAX_ADR = 3.0                  # ... salvo che siano ancora in una base (15 giorni entro 3 ADR)
RS63_WEIGHT = 0.75                  # [RONIN 20/10b, Andrea] forza relativa: 3 mesi più del mese (il mese porta su titoli
RS21_WEIGHT = 0.25                  # che hanno già fatto il movimento, studio: forza a 1 mese oltre +21 = -24R)
MAX_EXT_SMA50_ATR = 6.0             # long e short: niente titoli a più di 6 ATR(14) dalla SMA50 [RONIN 16/10, Andrea]
LONG_MAX_FOCUS = 8

# ---------------------------------------------------------------- setup short [ML]
SHORT_MAX_FOCUS = 8                 # Focus short: i primi 8 ...
SHORT_FOCUS_EXTRA_MIN_SCORE = 4.0   # ... più tutti gli altri con punteggio alto (impl.) [RONIN 14/10]
SHORT_FOCUS_MAX = 15                # tetto per la lunghezza della card
SHORT_INPLAY_BONUS = 1.0            # short: precedenza ai temi in play rispetto ai difensivi [RONIN 14/10]
INPLAY_THEME_WORDS = (              # temi "in play" (tech, speculativi, AI) cercati per parola nel nome del tema (impl.)
    "semiconductor", "memor", "software", "cyber", "crypto", "bitcoin", "blockchain", "quantum", "datacenter",
    "data center", "optical", "space", "nuclear", "uranium", "drone", "robot", "artificial intelligence", "lidar",
    "rare earth", "solar", "fuel cell", "batter", "lithium", "defense", "computer hardware", "internet",
    "communication equipment", "electronic", "fintech", "social media", "3d printing", "genomics", "ev",
    "electrification", "networking", "ai", "cloud", "gaming", "streaming", "biotech",
    "photonic", "electrical grid", "neocloud", "digital infrastructure")   # nomi dei gruppi ETF [RONIN 15/10]
SHORT_NO_ABOVE_EMA9 = True          # "non shorto finché sta sopra la 9 daily" [ML gen 2026]
SHORT_STRONG_CANDLE_CLOSE_POS = 0.8 # niente short il giorno dopo una candela forte: chiusura nel 20% alto del range ...
SHORT_STRONG_CANDLE_RET_ADR = 1.0   # ... e rialzo ≥ 1 ADR [ML 22/07/2026]
SHORT_WEEKLY_HEALTHY_BLOCK = False  # weekly sano: dal 16/10 non blocca più, toglie punti (consonanza dei timeframe) [RONIN 16/10]
# livello short "forte": la confluenza deve contenere almeno uno di questi (lo short sulla sola 9 ha il win rate più basso;
# il migliore è il primo rimbalzo nella 50 declinante, poi AVWAP da swing high e gap) [ML 22/07, 16/09, articolo; RONIN 14/10]
SHORT_STRONG_LEVELS = ("EMA21", "EMA50", "AVWAP swing high", "gap")
THEME_WEIGHT_LONG = 2.0             # peso del tema nel punteggio dei long
THEME_WEIGHT_SHORT = 1.0            # short: il tema conta meno (i temi forti sono già esclusi) [RONIN 14/10]
THEME_WEIGHT_LONG = 2.0            # peso del rango del tema nel punteggio dei long
THEME_WEIGHT_SHORT = 1.0           # short: premia ancora i temi di metà classifica, ma pesa meno [RONIN 14/10]
# dal thread "Shorting" e dall'articolo sullo studio (grafici annotati RGTI, CVNA, TEM, NVDA, LRCX, ADBE) [ML 2025; studio 14/10]:
SHORT_EARLY_DOWNTREND = False       # [20/10a, Andrea] solo pullback (prima True)        # in watchlist anche il trend che gira: 9 sotto 21, entrambe in discesa, EMA strette
SHORT_EMA_TIGHT_ADR = 1.0           # EMA strette: distanza tra la più alta e la più bassa di 9/21/50 entro 1 ADR
SHORT_EARLY_IGNORES_WEEKLY = True   # il trend che gira è il primo top: il weekly è per forza ancora sano
# primo crack di un ex-leader [ML EP103 12/10 (SNDK), 5/3 e 12/3 (top parabolici), EP104]: dopo una grande corsa, prima
# chiusura sotto la EMA9 che gira giù, debolezza relativa, short sul rimbalzo nella 9 declinante / AVWAP da swing high.
SHORT_EXLEADER = False              # [20/10a, Andrea] solo pullback (prima True)
EXLEADER_IGNORES_STRONG_SECTOR = True   # l'ex-leader si shorta anche se il suo tema/settore è ancora forte [RONIN 14/10]
EXLEADER_MIN_UP_52W_LOW = 150.0     # ex-leader: almeno +150% dal minimo a 52 settimane (impl.; SNDK +5000%, MU, AXTI)
EXLEADER_RISK_MULT = 0.5            # ingresso aggressivo: metà rischio [ML EP17: se anticipi usa metà rischio]
SHORT_TIGHT_BONUS = 0.5             # punteggio: "più le EMA sono strette, più alto il tasso di rigetto" (impl.)
SHORT_EMA9_IF_FEEDBACK = False  # [16/10p: i trade li sceglie Andrea, il feedback simulato non decide]       # la sola EMA9 vale come ingresso secondario se il feedback degli short è positivo
SHORT_EMA50_BONUS = 0.5           # punteggio: EMA50 declinante nella confluenza short (impl.) [RONIN 14/10]
# mai shortare il settore forte né il suo titolo più debole [ML EP16, EP18, 15/09; RONIN 14/10]:
THEME_IN_SELECTION = False          # [RONIN 20/10b, Andrea: "togliamo i temi"] Focus scelti solo sul setup (studio: +31,7R contro +19,8R)
SHORT_BLOCK_STRONG_THEME = False    # [19/10e, Andrea] niente blocco/requisito di tema per gli short: bastano le regole sul titolo
SHORT_BLOCK_THEME_PCT = 0.5         # niente short se il tema è nella metà alta della classifica
SHORT_BLOCK_ETF_W9_RISING = False  # [RONIN 16/10: tolto, lo stadio del tema fa già questo lavoro]    # ... o se l'ETF di settore del tema è sopra la EMA9 weekly in salita
# ETF di settore del tema = gli ETF del gruppo nella lista di Andrea (themes_map: theme_etfs), scaricati ogni giorno [RONIN 15/10]

# ---------------------------------------------------------------- regime e bias (una direzione alla volta) [ML]
FEEDBACK_TRADES = 15                # ultimi N trade simulati per il "trade feedback"
FEEDBACK_BAD_R = -4.0               # somma R degli ultimi N sotto questa soglia = feedback negativo (impl.)
FEEDBACK_GOOD_R = 3.0
# Market Monitor di Stockbee [RONIN 13/10]: letto dal foglio pubblico di Stockbee (stockbee.py) [RONIN 15/10]; riserve:
# il file di NEL (MM_URLS), l'archivio nel repo e il calcolo nostro (breadth.py).
# Sostituisce la nostra breadth Leading nel regime con la stessa logica: stato ±1 (regole NEL "marketRead")
# e variazione ±1 (T2108 a 5 sedute, come la variazione della quota Leading). Se manca la riga del giorno: breadth Leading.
MM_URLS = ("https://raw.githubusercontent.com/i-manage-risk/NEL/main/outputs/breadth_market_monitor.json",
           "https://i-manage-risk.github.io/NEL/outputs/breadth_market_monitor.json")
MM_DEF_DOWN4 = 300                  # Defensive: down 4% >= 300, oppure 10D < 0,85, oppure 5D < 0,70 con down4 > 2x up4 [NEL]
MM_DEF_RATIO10 = 0.85
MM_DEF_RATIO5 = 0.70
MM_EXP_RATIO10 = 1.25               # Expansion: 10D >= 1,25 e 5D >= 1,10 e up4 >= 180 e down4 < 150 [NEL]
MM_EXP_RATIO5 = 1.10
MM_EXP_UP4 = 180
MM_EXP_DOWN4 = 150
# Lettura del Market Monitor come la usa Pradeep Bonde (Stockbee) [RONIN 16/10; video TraderLion kCLiSsIZ7L4
# 81:20-98:00, trascrizione in data/studi/pradeep_situational_awareness.md]. "pradeep" o "nel" (regole NEL, sopra).
# Tre stati, gli stessi nomi interni di prima: Expansion = "Breakouts work", Mixed = "Be selective",
# Defensive = "Breakouts fail". Niente rapporti 5D/10D ("no value in those ratios", 87:01).
MM_READ = "pradeep"
MM_LABEL = {"Expansion": "Breakouts work", "Mixed": "Be selective", "Defensive": "Breakouts fail"}
PB_T2108_OVERSOLD = 20.0            # T2108 < 20: "start getting bullish" (97:30, 88:01)
PB_T2108_EXTREME = 10.0             # < 10: "extremely bullish" (97:30)
PB_T30A = 30                        # 30 sedute dopo un T2108 < 20: "not worried about a market correction" (92:31)
PB_UP20_CAUTION = 200               # studio 20%: +20% in 5 sedute >= 200 = estremo, storno entro 5-10 sedute (90:00) [RONIN 16/10: 200]
PB_DOWN20_CAUTION = 200             # speculare: -20% in 5 sedute >= 200 = vendita estrema, rimbalzo probabile [RONIN 16/10]
PB_UP20_EXTREME = 200               # linea del grafico
PB_UP20_WINDOW = 10                 # l'avviso vale 10 sedute ("pullback next 5 to 10 days")
PB_FLOW_DAYS = 5                    # acquisti/vendite: giorni con più +4% che -4% nelle ultime 5 sedute (86:00)
PB_FLOW_MIN = 2                     # saldo >= +2 = "buying coming in", <= -2 = "selling coming in" (impl.)
PB_T2108_EXTENDED = 65.0            # oltre la zona 50-65 della slide = "T2108 extended" (impl. dalla slide)
# Il Market Monitor decide il bias [RONIN 13/10]: Expansion -> LONG, Defensive -> SHORT, Mixed -> MISTO
# (long e short, solo i migliori, rischio dimezzato). Il punteggio sugli indici resta come contesto e come riserva.
MM_BIAS = {"Expansion": "LONG", "Defensive": "SHORT", "Mixed": "MISTO"}
MM_MIXED_MODE = "misto"             # Mixed: "misto" (long e short selettivi), "fermo" (niente trade), "score" (decide il
#                                     punteggio di indici/breadth/feedback) [RONIN 16/10: in prova col replay]
REVERSAL_SKIP_DAY1 = False          # potential trend reversal: il giorno dell'inversione niente trade (si parte dal 2°)
BIAS_EN = {"LONG": "LONG", "SHORT": "SHORT", "MISTO": "MIXED", "FERMO": "FLAT"}     # Discord in inglese [RONIN 13/10]
PHASE_EN = {"attivo": "active", "neutro": "neutral", "accensione": "ignition", "preparazione": "setting up",
            "maturità": "mature"}
# Lista del lato opposto al regime, sempre presente [RONIN 13/10]: i migliori (qualità), max 4, mai voto C o declassati.
# Alert con la nota "against the regime": sono solo conoscenza, il bot non li prende (giornale: trade ombra) [20/10f, Andrea]
COUNTER_MAX = 4
COUNTER_MIN_CONFLUENCE = 3          # livello con almeno 3 componenti
COUNTER_MIN_THEME_PCT = 0.5         # tema nella metà alta della classifica
REVERSAL_DAYS = 2                   # "potential trend reversal": nelle prime 2 sedute dopo l'inversione del flusso ±4%
#                                     la card porta Focus long e short (fino a LONG/SHORT_MAX_FOCUS per lato) [RONIN 16/10]
MIXED_FOCUS_PER_SIDE = 6            # [22/10, Andrea] MISTO: 6 Focus long + 6 short (prima 4, 19/10e)
MIXED_MAX_FOCUS = 3                 # MISTO: al massimo 3 Focus tra long e short, i migliori per punteggio [RONIN 13/10]
RISK_PCT_MIXED = 0.15               # MISTO: rischio per trade dimezzato [RONIN 13/10]
MM_T2108_DELTA = 5.0                # punti di T2108 in 5 sedute per il +1/-1 della variazione (impl.)
BREADTH_LEAD_GOOD = 0.45           # quota Leading / (Leading+Lagging) sopra = breadth buona (impl.)
BREADTH_LEAD_BAD = 0.30
IWM_LAG_WARNING = True              # IWM in relativa debolezza = condizione necessaria delle correzioni >15% [ML]
# Il bias si decide con un punteggio (engine.regime): ≥ +2 LONG, ≤ -2 SHORT, in mezzo FERMO.
BIAS_LONG_MIN = 2
BIAS_SHORT_MAX = -2

# ---------------------------------------------------------------- temi (design_modulo_temi.md)
# Mappa dei temi (themes_map.py) [RONIN 15/10]: solo ETF tematici (lista di Andrea, tutti i gruppi) con partecipazioni
# complete da SEC N-PORT (etf_holdings.py; riserva: top 10 dal repo di NEL),
# modifiche a mano; correlazione solo come proposta. Niente basket a mano, industria Yahoo o cluster.
THEME_ETF_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1OSC1ovj4y5I-Yb_xBsMNvexgAOSUbLJRzbQU9W9uCNM/export?format=csv&gid=305077282"
THEME_ETF_HOLDINGS_URL = "https://raw.githubusercontent.com/i-manage-risk/NEL/main/data/etf_holdings_cache.json"
# secondo messaggio sotto la card: temi in uptrend e in breakdown [RONIN 14/10]
THEME_MSG_ROWS = 10                 # temi per sezione
THEME_MSG_TICKERS = 10              # titoli tra parentesi, in ordine di punteggio a 7 fattori [RONIN 16/10, Andrea: fino a 10]
THEME_LEADING_MIN_LEAD = 0.5        # leading in uptrend: almeno metà dei titoli in Leading e 1 mese positivo
THEME_BREAKING_MIN_LAG = 0.5        # breaking down: almeno metà dei titoli in Lagging e 1 mese negativo
# Classifica dei temi come i basket di Ratatouille (ratatouille-public/Screener) [RONIN 16/10]: punteggio del tema =
# media del Final_Score a 7 fattori dei suoi titoli (percentili sull'universo dei temi). Solo la classifica long, che vale
# anche per i filtri degli short. Pesi di Ratatouille (config.py).
# [RONIN 21/10, Andrea] temi = basket di Lone Stock Trader (data/themes/lst_baskets.json, aggiornati il lunedì alle 01:00
# dal server con lst_baskets.py); classifica complessiva = media equal-weight del Final_Score a 7 fattori di TUTTI i titoli
# del basket (percentili calcolati su tutti i titoli dei basket, nessun filtro di liquidità); in testa al messaggio dei
# temi il grafico RS settimanale (asse X) / RS mensile (asse Y) dei basket, come "Market Metrics - Industries".
THEME_SOURCE = "lst"                # "lst": basket di Lone Stock Trader; "etf": vecchia mappa dagli ETF tematici
LST_MIN_SCORED = 3                  # un basket entra in classifica con almeno 3 titoli con storia sufficiente (63 sedute)
# [ANDREA 28/10] messaggio dei temi più semplice: niente classifica (Overall ranking, Weakest, Leading in uptrend,
# Breaking down), restano i due grafici RS settimana/mese e mese/trimestre
CARD_THEMES_RANKING = False
# [ANDREA 28/10] grafico daily di ogni Focus sotto FOCUS LONG / FOCUS SHORT della card (galleria di Discord, si scorre
# con le frecce): solo il multi-edge (acceso in fondo al file)
CARD_FOCUS_CHARTS = False
THEME_RS_CHART = True               # grafico RS settimana / mese dei basket in testa al messaggio dei temi
THEME_RANK_ROWS = 15                # basket nella classifica complessiva del messaggio dei temi
THEME_RANKING = "basket"            # [21/10] prima "etf_perf"; "etf_perf": performance degli ETF del tema vs SPY a 1S/1M/3M + livelli degli ETF [RONIN 17/10,
#                                     Andrea: come prima dei 7 fattori]; "etf": 7 fattori sugli ETF; "basket": 7 fattori sui
#                                     titoli; "componenti": media dei ranghi di 7 misure dei titoli
MEGA_CAPS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "NFLX", "ORCL")   # breadth: mega cap sopra la 9 [ML 31/08]
BREADTH_LEADERS_N = 20              # breadth: i 20 titoli più forti a 3 mesi (RS63) e la loro tenuta su 9/21 [ML: leader "àncora"]
SIGNAL_FEEDBACK_N = 15              # feedback dei segnali: ultimi 15 alert per lato [RONIN 17/10; ML 15/07]
THEME_PERF_WEIGHTS = {"rs_1w": 0.2, "rs_1m": 0.3, "rs_3m": 0.3, "levels": 0.2}
#                                     Andrea: "usa direttamente l'ETF al posto dei singoli titoli"]; "basket": media dei
#                                     titoli del tema; "componenti": vecchio metodo (media dei ranghi di 7 misure)
THEME_ETF_DV_MIN = 250e3            # ETF di tema con almeno 250k$ al giorno (20 sedute): sotto, candele e volumi poco affidabili
# stadi dei temi come Ratatouille (punteggio del tema e variazione a 5 sedute) [RONIN 16/10, Andrea]:
# long solo nei temi LEADING o BUILDING, short solo nei temi SLIPPING o WEAK; i temi FADING si aprono agli short quando
# lo studio 20% ha +20% >= 200 e ai long quando ha -20% >= 200 (nelle ultime PB_UP20_WINDOW sedute).
# Titoli senza tema in classifica: nessun filtro (non c'è informazione).
THEME_STAGES = False                # [RONIN 17/10h, Andrea: "levali gli stadi"] niente stadi: né filtro né etichetta
STAGE_LONG = ("LEADING", "BUILDING")
STAGE_SHORT = ("FADING", "SLIPPING", "WEAK")   # FADING sempre aperto agli short [RONIN 16/10, Andrea: "ho sbagliato io"]
STAGE_FADING_SHORT_UP20 = 200          # non più usato dal 16/10l (FADING sempre aperto agli short)
STAGE_FADING_LONG_DOWN20 = 200
STAGE_REQUIRE_THEME = False         # True: senza tema in classifica niente candidato (prova del 17/10: lato dal solo tema)
BASKET_WEIGHTS = {"price_performance": 0.25, "bullish_candles": 0.15, "ma_alignment": 0.15, "trend_consistency": 0.15,
                  "volatility": 0.10, "volume": 0.10, "relative_strength": 0.10}
BASKET_BENCHMARK = "SPY"
THEME_DV_MIN = 75e6                 # liquidità minima per contare in un tema [RONIN 13/10]
# appartenenza a un tema [RONIN 16/10, Andrea: "riguarda l'associazione dei basket"]: un titolo sta in un tema solo
# se l'ETF del tema lo sovrappesa rispetto al mercato. Sovrappeso = peso nell'ETF / (capitalizzazione del titolo /
# capitalizzazione totale dell'universo). Tiene i temi con sovrappeso >= MIN e almeno FRAC del suo sovrappeso massimo;
# se nessuno passa, resta solo il tema col sovrappeso più alto. Così MSFT non è in Cybersecurity né NVDA in Bitcoin.
THEME_OVERWEIGHT_MIN = 5.0
THEME_OVERWEIGHT_FRAC = 1 / 3
THEME_MEMBERSHIP = "sovrappeso-5-1/3"   # se cambia, la mappa si ricostruisce
MAP_THEME_MIN_MEMBERS = 3           # un tema della mappa entra in classifica con almeno 3 titoli liquidi
THEME_PROPOSAL_CORR = 0.60          # titolo senza tema che si muove con un tema (60 sedute): proposta, non assegnazione
THEME_CLOSES_MAX = 700              # titoli per la correlazione (i più liquidi sopra THEME_DV_MIN)
THEME_MIN_MEMBERS = 4               # un tema esiste con almeno 4 titoli liquidi
CORR_WINDOWS = (40, 60)             # correlazione dell'andamento (variazioni % giornaliere), QQQ escluso [RONIN 12/10]
CORR_THRESHOLD = 0.55               # soglia di legame tra due titoli (impl.)
CORR_UNIVERSE_MAX = 400             # i più liquidi
RED_DAY_LOOKBACK = 20               # giorni rossi di QQQ negli ultimi 20

# ---------------------------------------------------------------- utili [ML]
EARNINGS_BLOCK_SESSIONS = 3         # niente nuovi trade nelle 3 sedute prima degli utili

# ---------------------------------------------------------------- trigger intraday [ML]
TRIGGER_1M_UNTIL_MIN = 0            # [RONIN 27/10d, Andrea: "togliendo il 1 minute trigger sia su martin che su mets"]
#                                     niente trigger a 1m: dall'apertura rottura della candela 5m (fino al 27/10c: 1m nei primi 15 minuti)
# apertura [ML: evita i primi minuti, ORB solo se il 1° minuto è stretto, non shorta la debolezza in apertura; RONIN 14/10: 10 minuti]
EARLY_MIN = 10                      # primi 10 minuti senza trigger [RONIN 27/10f; 17/10-27/10e: 15; ML 23/04, EP103] ...
EARLY_OPEN_NEAR_ADR = 0.5           # ... salvo apertura già entro 0,5 ADR dal livello (gap nella resistenza / sul supporto)
EARLY_LONG_FIRST_BAR_MAX_PCT = 1.5  # ... e long solo se la prima candela 1m ha range < 1,5%
TRIGGER_5M_UNTIL_MIN = 999          # [RONIN 27/10e, Andrea] 5m per tutta la seduta, come negli studi sul replay
#                                     (fino al 27/10d: 15m dopo i primi 60 minuti)
STOP_MAX_PCT = 2.0                  # stop oltre min(2%, 0,5 ADR) = scartato [ML]
STOP_MAX_ADR_FRAC = 0.5
CHASE_MAX_PCT = 3.0                 # oltre il 3% dal livello = non si insegue [ML]
# [20/10h, Andrea] banda d'ingresso: il prezzo d'ingresso deve stare un po' PRIMA del livello, non sopra di esso.
# Studio 20/07-16/10 sui 123 trade: ingresso praticamente sul livello o oltre -0,23R di media (short -0,85R),
# anticipato di 0,07-0,84% +1,43R. Con la banda 0,05-1,0% sulla versione attiva: 45 trade +129,6R (+2,88 di media)
# contro 64 trade +135,2R (+2,11). Fuori banda l'ingresso aspetta, il trigger resta libero.
ENTRY_BAND = True
ENTRY_DIST_MIN_PCT = 0.05           # minimo: sotto, si sta comprando/vendendo sul livello stesso
ENTRY_DIST_MAX_PCT = 1.0            # massimo: oltre, il livello e' ancora troppo lontano
INDEX_GAP_BLOCK_PCT = 0.75          # soglia del gap del QQQ (±0,75%) per le attese d'apertura [ML: non shortare il gap down del mercato]
INDEX_GAP_UP_LONG_WAIT_MIN = 30     # QQQ apre ≥ +0,75%: long solo dopo 30 minuti, sul pullback al livello [ML 18/09; RONIN 14/10]
INDEX_GAP_DOWN_SHORT_WAIT_MIN = 30  # QQQ apre ≤ -0,75%: short solo dopo 30 minuti, sul rimbalzo al livello (prima: blocco di seduta) [ML 6/03; RONIN 15/10]
ALERTS_ONLY = True                  # [RONIN 16/10, Andrea: "tu mi segnali gli alert, io scelgo i trade"]: tetto giornaliero,
#                                     pausa dopo le perdite e feedback dei trade simulati non bloccano né orientano più
#                                     niente; restano i filtri di qualità del trigger (stop, inseguimento, gap, liquidità).
#                                     Il giornale resta come statistica di tutti i trigger.
MAX_NEW_TRADES_DAY = 4              # freno anti-overtrading [ML: 3-5 nuove posizioni]
LOSS_STREAK_PAUSE = 10              # dopo 10 perdite di fila ...
PAUSE_SESSIONS = 2                  # ... 2 sedute senza nuovi trade (i segnali vanno nei trade ombra)
POLL_SEC = 60

# ---------------------------------------------------------------- giornale / simulazione [RONIN 13/10]
START_EQUITY = 100_000.0
RISK_PCT = 0.30                     # rischio per trade in % dell'equity [ML 2026]
SIZE_MAX_PCT = 25.0                 # size massima per posizione [ML 2026]
GROSS_MAX_PCT = 250.0               # esposizione lorda massima [ML]
SLIPPAGE_PCT_LIQUID = 0.05          # titoli ≥ 500M$/giorno
SLIPPAGE_PCT_OTHER = 0.15
# gestione long [ML]
LONG_TRIM_FRAC = 0.15
LONG_TRIM_EXT_EMA9_PCT = 15.0       # trim quando il close è ≥15% sopra la EMA9
LONG_TRIM_R = 4.0                   # oppure a 4R
LONG_TRAIL = "ema9_close"           # uscita del resto: chiusura sotto la EMA9 daily
# gestione short [ML]
SHORT_TRIM_FRAC = 0.15
SHORT_TRIM_R = 3.0
SHORT_MAX_DAYS = 3                  # gli short sono swing brevi ...
SHORT_TIME_EXIT_FREE_BIAS = ("SHORT",)  # ... ma con bias SHORT niente uscita a tempo: a inizio downtrend li tiene [ML 12/10; RONIN 14/10]
SHORT_EXIT_HOURLY_EMA = 50          # barra oraria che chiude sopra la EMA50 oraria = fuori
# gestione "ext_h50" [RONIN 17/10, Andrea; studi/gestione_stop.py: 4 settimane, 97 trigger, -27.8R -> -13.4R]
#   parziali nelle estensioni dalla EMA9 daily (valore della chiusura precedente) misurate in ATR(14) daily;
#   short più aggressivi (nei giorni di vendita pesante si allontanano presto dalla 9);
#   il resto in trailing sulla EMA50 oraria: fuori alla barra oraria che chiude oltre la 50, attivo solo dopo +1R
#   (prima vale lo stop iniziale: così la 50 oraria non falcia il trade appena aperto);
#   sostituisce trim a 4R/3R, uscita sotto la EMA9 daily, trim 15% sopra la 9 e uscita a tempo degli short.
MGMT_MODE = "ext_h50"               # "ext_h50" oppure "classic" (regole fino alla 17f)
LONG_EXT_TRIMS = ((2.0, 0.25), (3.0, 0.25))      # (ATR oltre la EMA9 daily, quota delle azioni iniziali)
SHORT_EXT_TRIMS = ((1.5, 1 / 3), (2.5, 1 / 3))
TRAIL_H50_EMA = 50
TRAIL_H50_AFTER_R = 1.0
MGMT_MAX_SESSIONS = 15              # oltre si chiude alla chiusura serale

# fonte del bias: "mm" = stato del Market Monitor (13/10-17/10i); "qqq" = solo il QQQ sulle EMA daily
# (sopra 9 e 21 = LONG, sotto entrambe = SHORT, altrimenti MISTO)
BIAS_SOURCE = "pool"                # [17/10o] "pool" = liste del pool di Martin + feedback dei segnali (engine.regime_pool);
#                                     "martin" = liste dell'universo + feedback (17/10j-m): in ritardo e cieco ai crolli dei leader
# pool di Martin (jeffcoach/pool.py; studio studi/pool_martin.py) [RONIN 17/10o, Andrea]
EXLEADER_SKIPS_TREND_TF = True      # [19/10a, Andrea] ex-leader (sotto 9 e 21, 9 in discesa) esenti dalla consonanza EMA50 daily
POOL_PRIORITY = True                # in Focus prima i titoli del pool di Martin (la sua watchlist)
POOL_FOCUS_ONLY = False             # [20/10c, Andrea: "va bene qualsiasi titolo, conta il setup"] (19/10a-20/10b: True)
FEEDBACK_IN_CARD = False            # [19/10b, Andrea] feedback dei segnali tolto anche dalla card
LONG_ABOVE_EMA9 = True              # [19/10b, Andrea] long: chiusura sopra la EMA9 daily (specchio degli short)
LONG_WEEKLY_HEALTHY = True          # [19/10b, Andrea] long: weekly sano (specchio di "weekly non sano" degli short)
STOCKBEE_IN_CARD = False            # [19/10a, Andrea] card e regime solo col modello di Martin: niente Market Monitor,
#                                     tabella ±4% e potential trend reversal (il grafico 20%/T2108/NH-NL resta)
POOL_FB_WEIGHT = 0                  # [19/10a] peso del feedback nel bias dal pool: test 2016-2026 (studi/pool_martin/fbbal.py)
#                                     peso 0 ritardo 6 sedute, 100 falsi SHORT; peso 1: 4,5 sedute ma 167 falsi SHORT e niente
#                                     differenza di drawdown tra LONG e SHORT. Il feedback resta nella card come contesto
POOL_N = None                       # 17/10o: i 130 migliori; dal 19/10 nessun tetto [Andrea]
POOL_MIN_UP_LOW = None              # 19/10a: +100% dal minimo; tolto 19/10b (55% delle menzioni, pool di 15 titoli nel 2022)
POOL_ADR_MIN = 3.5                  # [19/10c, Andrea] ADR >= 3,5% al posto del percentile: 119 titoli il 03/09/2026,
#                                     11-145 negli anni (segue la volatilità), 69% delle menzioni (73% senza mega cap)
POOL_ADR_RANK = None                # 19/10b: ADR nel 40% più alto
POOL_BIG_RANK = None                # [19/10d, Andrea: "situazionale, poco rilevante"] tolto: 132 titoli il 03/09/2026
#  (19/10b-c: 0.5)                 # ADR nel 40% più alto e sedute da +4% a 60 giorni nella metà alta dell'universo:
#                                     132 titoli il 03/09/2026 (Martin: 46+31+55 = 132), 55-133 negli anni 2016-2026,
#                                     68% delle menzioni (73% senza mega cap)
POOL_DV_RANK = 0.70                 # dollar volume a 20 sedute nel 30% più alto dell'universo
POOL_RS_MIN = 0.80                  # forza relativa a 3 o 6 mesi almeno all'80° percentile negli ultimi 6 mesi
POOL_LIQ_RS = 50e6                  # la forza relativa si misura tra i titoli con almeno 50M$/giorno
POOL_RS_WINDOW = 126                # sedute in cui cercare la forza massima (6 mesi); proposta studio 27/10: 252 (12 mesi)
POOL_ADR_REL = None                 # proposta studio 27/10: 1.2 = ADR >= 1,2 volte l'ADR mediano del mercato del giorno al
#                                     posto di POOL_ADR_MIN (pool di 89-144 titoli ogni anno dal 2016 invece di 11-159)
POOL_ADR_REL_DV = 50e6              # (impl.) titoli negoziabili per l'ADR mediano: dv20 >= 50M$ e prezzo >= PRICE_MIN
POOL_SHARE_GOOD = 70.0              # Leading / (Leading+Lagging) del pool: >= 70% = +1 ...
POOL_SHARE_BAD = 50.0               # ... <= 50% = -1
POOL_FLOW_MIN = 10.0                # flusso a 5 sedute in % del pool: ±10% = ±1 ...
POOL_FLOW_STRONG = 20.0             # ... ±20% = ±2
POOL_FLOW_DAY_MIN = 1.0             # tendenza: 3 flussi giornalieri su 4 oltre ±1% nello stesso verso = ±1
# [RONIN 27/10, Andrea: "nella card una linea con l'andamento in % dei titoli nei tre gruppi leading-mediocre-lagging"]
# gruppo del titolo e grafico del suo ETF [RONIN 28/10a, Andrea: "metti su entrambi questa versione", studio
# studi/gruppo_etf.py: Focus Dua 59 trade +91,4R contro 65 +85,8R, multi-edge 55 trade +128,9R contro 65 +92,9R; il
# risultato dipende da pochi trade (vedi claude/studio_gruppo_etf.md)] — jeffcoach/gruppo.py
GROUP_ETF = True                    # gruppo dalla mappa ETF di Andrea di prima dei basket (data/themes/mappa_etf.json)
GROUP_HISTORY_DAYS = 1900           # daily degli ETF per livelli e orizzontali weekly (~5 anni)
GROUP_AREA_PAD_ADR = 0.25           # (impl.) ogni livello dell'ETF è un'area ± 0,25 ADR dell'ETF
GROUP_HZ_PAD_ADR = 0.10             # (impl.) aree orizzontali dal bordo basso al bordo alto ± 0,1 ADR
GROUP_PREFER_RS = True              # Focus: a parità di pool ed edge prima i titoli più forti (long) / deboli (short) della media del gruppo
GROUP_RS_MIN_MEMBERS = 3            # (impl.) media del gruppo su almeno 3 altri titoli del tema
GROUP_SHORT_NOT_UP = True           # niente short con l'ETF del gruppo in trend su (EMA9 > 21, 21 in salita, sopra la 21)
GROUP_LONG_NEAR_SUPPORT = True      # long solo con l'ETF del gruppo vicino a una sua area di supporto al trigger ...
GROUP_LONG_NEAR_ADR = 0.25          # ... il minimo di oggi entro 0,25 ADR dell'ETF dal bordo alto dell'area ...
GROUP_LONG_MIN_LEVELS = 2           # ... area con almeno 2 livelli ...
GROUP_BREAK_ADR = 0.25              # ... e il prezzo non sotto l'area di oltre 0,25 ADR
ALERT_INTRADAY_PANEL = False        # [RONIN 28/10, Andrea] grafico degli alert senza il pannello intraday sotto
ALERT_GROUP_CHART = True            # [RONIN 28/10, Andrea] seconda immagine negli alert: il grafico dell'ETF del gruppo
LISTS_CHART = True                  # pannello del grafico della card: % del pool in Leading / Mediocre / Lagging
LISTS_CHART_DAYS = 130              # sedute (le stesse del grafico 20% / T2108)
LISTS_CHART_UNIVERSE = True         # tratteggiate le stesse % sull'universo liquido della lista (DV_MIN, PRICE_MIN)
# bias alla Martin
MB_FB_MIN_N = 5                     # almeno 5 segnali chiusi per lato perché il feedback conti
MB_FB_FAIL_SHARE = 0.5              # metà o più stoppati senza arrivare a +0,5R = feedback negativo [ML 31/01: 8 su 10]
MB_FB_HIT_SHARE = 0.4               # positivo: somma >= FEEDBACK_GOOD_R e almeno il 40% arrivati a +1R
MB_FB_WEIGHT = 2                    # il feedback pesa doppio [ML: "il miglior indicatore"]
MB_LEAD_SHARE_GOOD = 55.0           # Leading / (Leading+Lagging) in %
MB_LEAD_SHARE_BAD = 40.0
# flusso tra le liste [17/10m, Andrea]: -1 per ogni titolo che scende di una lista, -2 se ne salta una, + se sale
MB_FLOW_MIN = 3.0                   # netto a 5 sedute in % dei titoli: oltre ±3% = ±1 ...
MB_FLOW_STRONG = 6.0                # ... oltre ±6% = ±2 (settembre 2026: tra -7% e +0%)
MB_FLOW_DAY_MIN = 0.5               # flusso giornaliero che conta per la tendenza (±0,5%)
MB_TREND_DAYS = 4                   # tendenza: flussi giornalieri delle ultime 4 sedute ...
MB_TREND_MIN = 3                    # ... almeno 3 nello stesso verso [17/10k]
MB_LEAD_SHARE_D5 = 3.0              # non più usato dal 17/10m (sostituito dal flusso tra le liste)
MB_LEAD_ABOVE9_GOOD = 65.0          # quota della lista Leading sopra la 9 daily
MB_LEAD_ABOVE9_BAD = 45.0
MB_LEADERS_BELOW9_BAD = 0.4         # leader (20 più forti a 3 mesi) sotto la 9: dal 40% in su = negativo
MB_LEADERS_BELOW9_GOOD = 0.15

# ---------------------------------------------------------------- istanza multi-edge [RONIN 22/10, Andrea]
# Lo stesso codice gira due volte sul server: Dua con le regole di Martin (questa configurazione) e, al posto di Remy,
# la versione multi-edge sul suo webhook, con la stessa card. L'istanza multi-edge ha JEFF_COACH_META=1 nel suo .env:
# edge accesi, trendline sui grafici, e liste, giornale, alert, report e cache in data/meta/ (storico, breadth e temi
# li legge da data/ come Dua, senza riscriverli).
META_INSTANCE = os.environ.get("JEFF_COACH_META") == "1"
WRITE_HISTORY = not META_INSTANCE   # lo storico (liste, potent, temi) lo scrive solo Dua: è uguale per le due istanze
if META_INSTANCE:
    META_EDGES = True
    META_RANK = True
    META_RANK_MODE = "side"         # [RONIN 22/10d, Andrea] Focus per S&R, PA/VOL, MTF e RS (long e short); M&T non conta
    META_FILTER = False
    TL_CHART = True
    HZ_CHART = True
    DAILY_HISTORY_DAYS = CHART_DAILY_DAYS = 1900   # ~5 anni: orizzontali weekly di mesi e anni prima [RONIN 23/10]
    # [RONIN 27/10c, Andrea: "sul multi edge"] pool con ADR relativo al mercato e forza cercata in 12 mesi (studio
    # studi/pool_martin/parametri.py); confluenza minima 4 livelli (studi/livelli_ingressi_ricontrollo.py: Focus 53
    # trade +25,0R di conto contro +14,5R con 3 livelli, 22/08-22/10), da confermare dal vivo prima di Dua
    POOL_ADR_REL = 1.2
    POOL_RS_WINDOW = 252
    CONFLUENCE_MIN = 4
    CARD_FOCUS_CHARTS = True        # [ANDREA 28/10] grafici dei Focus nella card (solo il titolo)
    RULES_VERSION = RULES_VERSION + "-meta"
    _META_HOME = HOME / "meta"
    STATE, LISTS, JOURNAL, REPORTS, ALERTS_STATE, LOGS = (_META_HOME / x for x in
                                                          ("state", "lists", "journal", "reports", "alerts", "logs"))
