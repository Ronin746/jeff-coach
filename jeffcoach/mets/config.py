"""Parametri del charting e dei supporti di METS (Martin-coach, istanza multi-edge, regole 2026-10-28b-meta) [ANDREA 29/10:
"riportalo alla versione precedente ... aggiorna solo la parte di charting e supporti alla versione usata nel Mets"].
Copiati da martincoach/config.py con i valori dell'istanza multi-edge (TL_CHART, HZ_CHART accesi, ~5 anni di daily)."""

ADR_LEN = 20
# trendline e canali paralleli sul daily, in scala logaritmica (martincoach/trendlines.py) [RONIN 22/10, Andrea;
# J Law EP2: trendline per almeno 2 swing, canale parallelo] (impl.)
TL_LOOKBACK = 120                   # swing degli ultimi 6 mesi
TL_PIVOT_K = 3                      # swing = massimo/minimo di 7 barre (come SWING_K)
TL_MIN_SPAN = 10                    # ancoraggi distanti almeno 10 sedute
TL_TOL_ADR = 0.25                   # tolleranza di tocchi e chiusure: 0,25 ADR
TL_MIN_TOUCHES = 2                  # trendline valida con 2 swing (3 o più = più solida)
TL_CHANNEL_MIN_TOUCHES = 2          # canale solo se anche la parallela tocca almeno 2 swing
TL_CHART = True                     # [METS] grafico daily in scala log con trendline e canali (bianchi)
TL_CONFIRMED_TOUCHES = 3            # segno di trend (M&T): trendline confermata da almeno 3 swing [J Law EP2]
# supporti e resistenze orizzontali, linee o aree (martincoach/orizzontali.py) [RONIN 23/10, Andrea] (impl.)
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
HZ_CHART = True                     # [METS] linee e aree orizzontali sul grafico
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
CHART_DAILY_DAYS = 1900             # [METS] ~5 anni: orizzontali weekly di mesi e anni prima
