#!/usr/bin/env bash
# Fasi di Jeff Coach multi-edge sul server (Oracle). Le lancia systemd con i timer di installa.sh.
# [JEFF 28/10] Stesse fasi del bot di Martin (base multi-edge), per un'istanza sola con i dati in data/.
#
#   fasi.sh aggiorna    salva i dati locali, prende codice e lista nuovi da GitHub, (systemd poi riavvia gli alert)
#   fasi.sh lista       lista del mattino            (solo se la macchina è grande; altrimenti GitHub Actions)
#   fasi.sh card        card su Discord (Sydney)     (idem)
#   fasi.sh premarket   gap-up pre-market nella card  (idem)
#   fasi.sh chiusura    giornale dei trade simulati alla chiusura (sempre sul server: il giornale lo scrive solo lui)
#   fasi.sh settimana   report di performance del lunedì (e mensile il primo lunedì del mese)
#   fasi.sh basket      basket di Lone Stock Trader (lunedì 01:10): copia della lettura comune ~/.lst fatta da Dua
#   fasi.sh breadth     Market Monitor nostro sull'universo completo (mar-sab 01:45, riprova 06:45): data/breadth/
#
# Il webhook di Sydney e il token GitHub stanno in .env (mai nel repo).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
PY="$DIR/.venv/bin/python"
set -a; [ -f .env ] && . ./.env; set +a
export PYTHONUTF8=1 JEFF_COACH_HOME="$DIR/data"

prendi() {    # codice e dati nuovi da GitHub
  git pull -q --rebase --autostash origin main
}

salva() {     # commit dei dati e push, con nuovi tentativi se GitHub è andato avanti
  git add -A data
  git diff --cached --quiet || git commit -q -m "$1 (server)"
  for i in 1 2 3; do
    git pull -q --rebase --autostash origin main && git push -q origin HEAD:main && { echo "salvato"; return 0; }
    sleep 15
  done
  echo "push NON riuscito"; return 1
}

oggi() { "$PY" -c "from jeffcoach.calendar_us import today_rome,is_session;d=today_rome();print(d if is_session(d) else 'none')"; }

case "${1:-}" in
  aggiorna)
    old=$(git rev-parse HEAD)
    salva "Dati" || true
    new=$(git rev-parse HEAD)
    if ! git diff --quiet "$old" "$new" -- requirements.txt; then "$DIR/.venv/bin/pip" install -q -r requirements.txt; fi
    echo "codice a $(git rev-parse --short HEAD)"
    ;;
  lista)
    prendi
    "$PY" -m jeffcoach.daily --skip-if-done
    salva "Lista $(oggi)"
    ;;
  card)
    prendi
    S=$(oggi); [ "$S" = "none" ] && { echo "oggi niente seduta"; exit 0; }
    [ -f "data/lists/$S.json" ] || { echo "lista $S non pronta"; exit 1; }
    "$PY" -m jeffcoach.daily --session "$S" --from-cache || "$PY" -m jeffcoach.daily --session "$S"
    "$PY" -m jeffcoach.discord card --session "$S" --if-changed | tee /tmp/jc_card.txt
    grep -q '"ok": true' /tmp/jc_card.txt || { echo "card NON pubblicata"; exit 1; }
    salva "Card $S"
    ;;
  premarket)
    prendi
    "$PY" -m jeffcoach.premarket
    salva "Premarket $(oggi)"
    ;;
  chiusura)
    prendi
    "$PY" -m jeffcoach.chiusura
    salva "Giornale $(oggi)"
    ;;
  settimana)
    prendi
    "$PY" -m jeffcoach.report weekly
    if [ "$(date +%d)" -le 7 ]; then "$PY" -m jeffcoach.report monthly; fi
    salva "Performance"
    ;;
  breadth)     # Market Monitor nostro sull'universo completo (studio 20%, T2108, nuovi massimi/minimi del grafico della
               # card); alle 06:45 solo se la riga dell'ultima seduta manca o è a metà
    prendi
    [ "$("$PY" -m jeffcoach.breadth fatto)" = "si" ] && { echo "riga già fatta"; exit 0; }
    "$PY" -m jeffcoach.breadth completo
    salva "Market Monitor nostro"
    ;;
  basket)      # basket di Lone Stock Trader per i temi [RONIN 21/10]: la copia comune ~/.lst che Dua legge alle 01:00;
               # se manca o è vecchia si legge il sito con la sessione comune (o LST_TOKEN_0/1 in .env)
    prendi
    if "$PY" -m jeffcoach.lst_baskets; then salva "Basket LST"; else echo "basket LST non aggiornati: tengo quelli di prima"; exit 1; fi
    ;;
  *)
    echo "uso: fasi.sh aggiorna|lista|card|premarket|chiusura|settimana|breadth|basket"; exit 2 ;;
esac
