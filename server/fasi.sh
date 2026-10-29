#!/usr/bin/env bash
# Fasi di Jeff Coach sul server (Oracle, Ubuntu). Le lancia systemd con i timer installati da installa.sh.
#
#   fasi.sh aggiorna    codice nuovo da GitHub (+ librerie se cambiate)
#   fasi.sh lista       lista Focus/Stalk del mattino -> commit su GitHub (la leggono gli alert)
#   fasi.sh card        card su Discord alle 10:45 di Roma (GitHub fa solo da riserva)
#   fasi.sh settimana   riepilogo del lunedì
#
# I webhook e il token GitHub stanno in ~/jeff-coach/.env (mai nel repo).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
PY="$DIR/.venv/bin/python"
set -a; [ -f .env ] && . ./.env; set +a
export PYTHONUTF8=1
# per lista, card e settimana i dati stanno nella cartella data/ del repo, come su GitHub
export JEFF_COACH_HOME="$DIR/data" JEFF_COACH_AGREED="$DIR/data/coach-agreed" JEFF_COACH_REMY_FILE="$DIR/data/remy/pivot30_list.txt"

allinea() {     # porta il codice e i dati a quelli di GitHub (i file locali non tracciati restano)
  git fetch -q origin main
  git reset -q --hard origin/main
}

pubblica() {    # commit dei dati e push, con nuovo tentativo se GitHub è andato avanti
  git add -A data
  git diff --cached --quiet && { echo "niente da salvare"; return 0; }
  git commit -q -m "$1 (server)"
  for i in 1 2 3; do
    git pull -q --rebase origin main && git push -q origin HEAD:main && { echo "pubblicato"; return 0; }
    sleep 15
  done
  echo "push NON riuscito"; return 1
}

oggi() { "$PY" -c "from jeffcoach.calendar_us import today_rome,is_session;d=today_rome();print(d if is_session(d) else 'none')"; }

case "${1:-}" in
  aggiorna)
    old=$(git rev-parse HEAD:requirements.txt HEAD:tv-scanner/requirements.txt 2>/dev/null || true)
    allinea
    new=$(git rev-parse HEAD:requirements.txt HEAD:tv-scanner/requirements.txt)
    if [ "$old" != "$new" ]; then "$DIR/.venv/bin/pip" install -q -r requirements.txt -r tv-scanner/requirements.txt; fi
    echo "codice a $(git rev-parse --short HEAD)"
    ;;
  lista)
    allinea
    "$PY" -m jeffcoach.daily --skip-if-done
    S=$(oggi)
    pubblica "Lista $S"
    ;;
  card)
    allinea
    S=$(oggi)
    [ "$S" = "none" ] && { echo "oggi niente seduta"; exit 0; }
    [ -f "data/coach-agreed/$S.json" ] || { echo "lista $S non pronta"; exit 1; }
    [ -f "data/state/daily_$S/discord_post.json" ] && { echo "card $S già pubblicata"; exit 0; }
    "$PY" -m jeffcoach.daily --session "$S" --from-cache
    "$PY" -m jeffcoach.discord card --session "$S" | tee /tmp/jc_card.txt
    grep -q '"ok": true' /tmp/jc_card.txt || { echo "card NON pubblicata"; exit 1; }
    pubblica "Card $S"
    ;;
  settimana)
    allinea
    "$PY" -m jeffcoach.weekly --skip-if-done
    pubblica "Settimana"
    ;;
  basket)      # basket di Lone Stock Trader per i temi [RONIN 21/10]: la copia comune ~/.lst che il bot di Martin
    #              legge alle 01:00; se manca o è vecchia si legge il sito con la sessione comune (o LST_TOKEN_0/1 in .env)
    allinea
    if "$PY" -m jeffcoach.lst_baskets; then pubblica "Basket LST"; else echo "basket LST non aggiornati: tengo quelli di prima"; exit 1; fi
    ;;
  *)
    echo "uso: fasi.sh aggiorna|lista|card|settimana|basket"; exit 2 ;;
esac
