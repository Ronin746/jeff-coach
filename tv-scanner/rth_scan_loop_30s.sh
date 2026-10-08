#!/usr/bin/env bash
# RTH scan: once per 5m bar, ~20s after bar close (Europe/Rome).
# Overlap-safe via flock. Window gate 15:10–21:55 Mon–Fri.
set -u
export TZ="${TZ:-Europe/Rome}"

LOG=/tmp/tv-scanner-rth.log
DIR=/workspace/tv-scanner
PY="${DIR}/.venv/bin/python"
SCRIPT="${DIR}/refresh_yfinance.py"
LOCK=/tmp/tv-scanner-rth.lock
OFFSET_SEC="${RTH_SCAN_OFFSET_SEC:-20}"

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

in_window() {
  local now_hm dow
  now_hm=$(date '+%H%M')
  dow=$(date '+%u')
  [[ "${dow}" -le 5 ]] || return 1
  [[ "${now_hm}" -ge 1510 && "${now_hm}" -le 2155 ]] || return 1
  return 0
}

# Sleep until next 5m boundary + OFFSET_SEC (e.g. :00+:20, :05+:20, …).
sleep_until_next_slot() {
  local now epoch next_close target wait
  now=$(date +%s)
  # next 5m close = ceil(now/300)*300 ; if exactly on boundary, next is +300
  next_close=$(( ((now + 299) / 300) * 300 ))
  if [[ $((now % 300)) -eq 0 ]]; then
    next_close=$((now + 300))
  fi
  # If we're still before this close's offset window for the *previous* close's slot
  # we want: fire at close+OFFSET. Next fire target:
  local last_close=$(( next_close - 300 ))
  local last_slot=$(( last_close + OFFSET_SEC ))
  if [[ "$now" -lt "$last_slot" ]]; then
    target=$last_slot
  else
    target=$(( next_close + OFFSET_SEC ))
  fi
  wait=$(( target - now ))
  if [[ "$wait" -lt 1 ]]; then wait=1; fi
  echo "$(ts) SLEEP ${wait}s until slot $(date -d "@${target}" '+%H:%M:%S' 2>/dev/null || date -r "${target}" '+%H:%M:%S')" >>"${LOG}"
  sleep "${wait}"
}

run_once() {
  if ! in_window; then
    return 0
  fi
  if [[ ! -x "${PY}" ]]; then
    echo "$(ts) ERROR: missing python ${PY}" >>"${LOG}"
    return 0
  fi
  exec 9>"${LOCK}"
  if ! flock -n 9; then
    echo "$(ts) SKIP overlap (previous scan still running)" >>"${LOG}"
    return 0
  fi
  echo "$(ts) START refresh_yfinance.py --scan (close+${OFFSET_SEC}s)" >>"${LOG}"
  set +e
  "${PY}" "${SCRIPT}" --scan >>"${LOG}" 2>&1
  rc=$?
  set -e
  echo "$(ts) END rc=${rc}" >>"${LOG}"
  flock -u 9
}

echo "$(ts) LOOP start mode=close+${OFFSET_SEC}s pid=$$" >>"${LOG}"
while true; do
  sleep_until_next_slot
  run_once
done
