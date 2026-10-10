#!/usr/bin/env bash
# Installazione di Jeff Coach su un server Ubuntu 24.04 (Oracle Cloud Always Free, anche ARM Ampere).
# Si lancia una volta sola, come utente normale (ubuntu), dalla cartella del repo:
#     bash server/installa.sh
# Si può rilanciare: non cancella .env né i dati.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
U="$(id -un)"
cd "$DIR"

echo "== 1/5 pacchetti di sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-dev build-essential tzdata >/dev/null

echo "== 2/5 ambiente Python"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt -r tv-scanner/requirements.txt

echo "== 3/5 file .env (webhook e token)"
if [ ! -f .env ]; then
  cp server/env.esempio .env
  echo "   creato .env: va completato (nano .env), poi rilancia questo script"
fi
chmod 600 .env
set -a; . ./.env; set +a
if [ -z "${GITHUB_TOKEN:-}" ] || [ -z "${COACH_ALERT_DISCORD_WEBHOOK_URL:-}" ] || [ -z "${DISCORD_WEBHOOK_URL:-}" ] \
   || [ -z "${COACH_CARD_DISCORD_WEBHOOK_URL:-}" ]; then
  echo "   .env incompleto: apri nano .env, metti i 3 webhook e il token GitHub, poi rilancia bash server/installa.sh"
  exit 1
fi

echo "== 4/5 git (push dei dati con il token, salvato solo in ~/.git-credentials)"
git config user.name "jeff-coach-server"
git config user.email "jeff-coach-server@users.noreply.github.com"
git config credential.helper store
printf 'https://x-access-token:%s@github.com\n' "$GITHUB_TOKEN" > ~/.git-credentials
chmod 600 ~/.git-credentials
git remote set-url origin https://github.com/Ronin746/jeff-coach.git
git fetch -q origin main && echo "   GitHub raggiungibile"

echo "== 5/5 servizi e orari (systemd)"
chmod +x server/fasi.sh
for f in server/systemd/*; do
  sed -e "s#@DIR@#$DIR#g" -e "s#@USER@#$U#g" "$f" | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now jeffcoach-alert.service
sudo systemctl enable --now jeffcoach-lista.timer jeffcoach-card.timer jeffcoach-settimana.timer jeffcoach-aggiorna.timer
echo
echo "Fatto. Controlli:"
echo "  systemctl status jeffcoach-alert        (alert di Sydney e Remy, sempre acceso)"
echo "  systemctl list-timers 'jeffcoach*'      (prossimi orari di lista, card, settimana, aggiornamento)"
echo "  journalctl -u jeffcoach-alert -f        (log in diretta, Ctrl+C per uscire)"
