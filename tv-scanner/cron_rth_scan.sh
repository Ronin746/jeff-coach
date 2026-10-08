#!/usr/bin/env bash
# Option B — box cron RTH scan wrapper (Europe/Rome).
# Runs refresh_yfinance.py --scan; Discord posts from Python alone.
# Always exits 0 so cron does not mail on "no signals" / soft failures.
set -u
export TZ="${TZ:-Europe/Rome}"

LOG=/tmp/tv-scanner-rth.log
DIR=/workspace/tv-scanner
PY="${DIR}/.venv/bin/python"
SCRIPT="${DIR}/refresh_yfinance.py"

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# Weekday + window gate: Mon–Fri 15:10–21:55 Europe/Rome inclusive.
# Cron fires */5 for hours 15–21; this skips before 15:10 and 22:00+.
now_hm=$(date '+%H%M')
dow=$(date '+%u')  # 1=Mon … 7=Sun
if [[ "${dow}" -gt 5 ]]; then
  echo "$(ts) SKIP weekend (dow=${dow})" >>"${LOG}"
  exit 0
fi
# Numeric compare: 1510..2155
if [[ "${now_hm}" -lt 1510 || "${now_hm}" -gt 2155 ]]; then
  echo "$(ts) SKIP outside RTH window 15:10–21:55 (now=${now_hm})" >>"${LOG}"
  exit 0
fi

cd "${DIR}" || {
  echo "$(ts) ERROR: cannot cd ${DIR}" >>"${LOG}"
  exit 0
}

if [[ ! -x "${PY}" ]]; then
  echo "$(ts) ERROR: missing python ${PY}" >>"${LOG}"
  exit 0
fi

echo "$(ts) START refresh_yfinance.py --scan" >>"${LOG}"
# Capture exit but never fail the cron job (no signals / soft errors → 0).
set +e
"${PY}" "${SCRIPT}" --scan >>"${LOG}" 2>&1
rc=$?
set -e
echo "$(ts) END rc=${rc} (wrapper forces exit 0)" >>"${LOG}"
exit 0
