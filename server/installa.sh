#!/usr/bin/env bash
# Installazione di Jeff Coach multi-edge sul server Ubuntu (Oracle Cloud, lo stesso dei bot di Martin).
# Si lancia una volta, come utente normale, dalla cartella del repo:   bash server/installa.sh
# Si può rilanciare: non cancella .env né i dati. Non tocca martin-coach né martin-meta.
# [JEFF 28/10] Stessa struttura dell'installazione di Martin (base multi-edge), con un'istanza sola: servizi jeffcoach-*
# (sostituiscono quelli di prima: l'alert service non lancia più avvia.py), dati in data/, webhook di Sydney.
# Niente stato di datahub: lo salva Dua.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
U="$(id -un)"
cd "$DIR"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)

echo "== 1/5 pacchetti di sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-dev build-essential tzdata >/dev/null

echo "== 2/5 ambiente Python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "== 3/5 file .env (webhook di Sydney e token GitHub)"
if [ ! -f .env ]; then
  cp server/env.esempio .env
  chmod 600 .env
  echo "   creato .env: completalo (nano .env), poi rilancia: bash server/installa.sh"
  exit 1
fi
chmod 600 .env
set -a; . ./.env; set +a
[ -n "${COACH_ALERT_DISCORD_WEBHOOK_URL:-}" ] || { echo "   manca COACH_ALERT_DISCORD_WEBHOOK_URL (Sydney) in .env"; exit 1; }
for k in LISA_DISCORD_WEBHOOK_URL; do      # il webhook di Dua non va in questo .env: Jeff Coach non lo usa mai
  [ -z "${!k:-}" ] || echo "   attenzione: $k in .env non serve qui (Jeff Coach scrive solo su Sydney)"
done

echo "== 4/5 git"
git config user.name "jeff-coach-server"
git config user.email "jeff-coach-server@users.noreply.github.com"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/Ronin746/jeff-coach.git"
else
  echo "   manca GITHUB_TOKEN: il server non potrà salvare lista, card e giornale su GitHub"; exit 1
fi
git fetch -q origin main && echo "   GitHub raggiungibile"

echo "== 5/5 servizi e orari (systemd)"
chmod +x server/fasi.sh
for f in server/systemd/*; do
  name="$(basename "$f")"
  sed -e "s#@DIR@#$DIR#g" -e "s#@USER@#$U#g" "$f" > "/tmp/$name"
  sudo cp "/tmp/$name" "/etc/systemd/system/$name" && rm -f "/tmp/$name"
done
sudo systemctl daemon-reload
sudo systemctl enable --now jeffcoach-alert.service jeffcoach-aggiorna.timer jeffcoach-chiusura.timer \
  jeffcoach-basket.timer jeffcoach-breadth.timer
sudo systemctl restart jeffcoach-alert.service          # prende subito il codice nuovo (prima girava avvia.py)
if [ "$MEM_MB" -ge 2500 ]; then
  sudo systemctl enable --now jeffcoach-lista.timer jeffcoach-card.timer jeffcoach-premarket.timer jeffcoach-settimana.timer
  echo "   lista, card, pre-market e settimana girano qui (GitHub Actions resta solo a mano)"
else
  sudo systemctl disable --now jeffcoach-lista.timer jeffcoach-card.timer jeffcoach-premarket.timer jeffcoach-settimana.timer 2>/dev/null || true
  echo "   macchina piccola (${MEM_MB} MB): qui alert e giornale; lista, card, pre-market e settimana su GitHub Actions"
fi
if [ -d "$HOME/datahub/src" ]; then          # servizio dati comune: anche questo ambiente passa da datahub
  sp="$(.venv/bin/python -c "import site; print([p for p in site.getsitepackages() if p.endswith('site-packages')][0])")"
  printf '%s\nimport datahub_autopatch\n' "$HOME/datahub/src" > "$sp/datahub.pth"
  echo "   agganciato a datahub"
fi
echo
echo "Prova del canale:   .venv/bin/python -m jeffcoach.discord test"
echo "Controlli:"
echo "  systemctl status jeffcoach-alert          (alert, sempre acceso)"
echo "  systemctl list-timers 'jeffcoach*'        (prossimi orari)"
echo "  journalctl -u jeffcoach-alert -f          (log in diretta)"
