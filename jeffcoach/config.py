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
CARD_WEBHOOK_ENV = ("COACH_CARD_DISCORD_WEBHOOK_URL", "DUA_COACH_DISCORD_WEBHOOK_URL")
ALERT_WEBHOOK_ENV = ("COACH_ALERT_DISCORD_WEBHOOK_URL", "SYDNEY_COACH_DISCORD_WEBHOOK_URL")
FORBIDDEN_WEBHOOK_ENV = ("DISCORD_WEBHOOK_URL", "SYDNEY_DISCORD_WEBHOOK_URL")   # Remy: mai
CARD_USERNAME = os.environ.get("COACH_NAME", "Dua")
ALERT_USERNAME = os.environ.get("COACH_ALERT_NAME", "Sydney Sweeney")
CARD_COLOR = 15105570          # #E67E22 [RONIN 04/10]
ALERT_COLOR = 0xF39C12

# ---------------------------------------------------------------- universo [RONIN 04/10]
MCAP_MIN = 500e6               # > $500M
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
SMA65_LEN = 30                 # SMA30 su barre 65m RTH, close daily SOPRA [RONIN 06/10]
BUCKET_MIN = 65

# ---------------------------------------------------------------- Stalk
# Stalk = universo ok + utili ok + RS >= 80 + sopra la SMA200, con almeno un gate Focus aperto, e:
#  - NUOVO ingresso: al massimo 1 gate numerico aperto E almeno una delle due letture vede un pattern stretto
#    ("c'è il pattern, manca un gate");
#  - GIÀ IN LISTA ieri: resta in Stalk finché ha al massimo 2 gate numerici aperti (si continua a seguirlo);
#    con 3+ gate aperti, RS < 80, sotto la SMA200 o utili in finestra esce.
# (impl.) Calibrato sulle liste reali di Dua e Sydney (5-8/10): copre 35 dei 41 Stalk pubblici dell'08/10.
# Gate numerici = tutti tranne "pattern".
STALK_RS_MIN = 80
STALK_RS_THEME_MIN = 70        # RS 70-79 entra in Stalk solo se TUTTI gli altri gate sono chiusi [RONIN 04/10: tema forte]
STALK_NEW_MAX_NUMERIC_OPEN = 1
STALK_CARRY_MAX_NUMERIC_OPEN = 2

# ---------------------------------------------------------------- lettura pattern (impl.)
# Due letture indipendenti, come facevano Dua e Sydney. Focus solo se le danno stretto ENTRAMBE;
# se una dice largo -> Stalk [RONIN 04/10: "se non siete d'accordo lo mettete in stalk"].
PATTERN_A = dict(            # lettura "Dua" (range vs ADR20)
    range10_adr_max=2.5,       # range 10 sedute (in % del close) / ADR20%
    off_high20_min_pct=-6.0,   # close entro 6% dal massimo a 20 giorni
    last_range_adr_max=1.3,    # ultima barra <= 1.3 ADR
    close5_adr_max=1.3,        # escursione dei close a 5 giorni <= 1.3 ADR
    thrust60_min_pct=15.0,     # spinta >= 15% nelle ultime 60 barre (minimo -> massimo successivo)
)
PATTERN_B = dict(            # lettura "Sydney" (in ATR)
    rally20_min_atr=3.0,       # spinta: rally dei close in 20 barre (nelle ultime 15) >= 3 ATR
    range5_max_atr=2.0,        # range 5 sedute <= 2 ATR
    dist_hi10_max_atr=1.0,     # close entro 1 ATR dal massimo a 10 giorni
    pullback_max_atr=3.5,      # pullback dal massimo della spinta <= 3.5 ATR (oltre = base di pullback, non continuation)
    trend_slope_atr=0.25,      # pendenze massimi E minimi a 8 barre >= 0.25 ATR/barra = ancora in trend, non consolidato
    expansion_range_atr=1.5,   # barra di ieri >= 1.5 ATR ...
    expansion_ret_pct=3.0,     # ... e >= +3% = barra di espansione (l'ORH insegue)
)

# ---------------------------------------------------------------- weekly [RONIN 06/10]
WEEKLY_SMA25_DAILY_MAX_PCT = 5.0   # al posto della SMA30 65m: close entro ~5% dalla SMA25 giornaliera
WEEKLY_EMA9_MAX_ATR = 1.5          # entro 1,5 ATR settimanali dalla EMA9 settimanale
# Stessa regola della daily: Focus solo se le due letture del pattern concordano, altrimenti Stalk.
# Le soglie delle letture sono calibrate sulle barre daily: sulla weekly vanno riviste con Ronin dopo le prime
# weekly regolari (dal 12/10). Con False basta una lettura (più Focus, meno filtro).
WEEKLY_PATTERN_REQUIRE_BOTH = True

# ---------------------------------------------------------------- alert [RONIN 30/09, 04/10]
RVOL_ALERT = 0.30              # 30% della media 50gg, solo nella prima ora, Focus+Stalk
RVOL_ALERT_WINDOW_MIN = 60
ORH_MINUTES = 30               # ingresso: rottura del massimo dei primi 30 minuti, solo Focus
LOD_ATR_RONIN = 0.70           # si calcola, non blocca
MEGA_LIQUID_ADV = 2e9          # RVOL soft
# Distanza massima dall'ORH per mandare l'ingresso (anti-inseguimento, hard rule 10 "never chase").
# None = disattivo (comportamento attuale). Da attivare solo se Ronin lo chiede.
CHASE_MAX_ATR_ABOVE_ORH = None
POLL_SEC = 90
