#!/usr/bin/env bash
set -u
export TZ="${TZ:-Europe/Rome}"
LOG=/tmp/tv-scanner-rth.log
DIR=/workspace/tv-scanner
LOOP="${DIR}/rth_scan_loop_30s.sh"
PIDFILE=/tmp/tv-scanner-rth-loop.pid

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

# outside window: stop loop if running
# Window gate Mon–Fri 15:10–21:55 Europe/Rome
now_hm=$(date '+%H%M')
dow=$(date '+%u')
if [[ "${dow}" -gt 5 || "${now_hm}" -lt 1510 || "${now_hm}" -gt 2155 ]]; then
  if [[ -f "${PIDFILE}" ]]; then
    old=$(cat "${PIDFILE}" 2>/dev/null || true)
    if [[ -n "${old}" ]] && kill -0 "${old}" 2>/dev/null; then
      kill "${old}" 2>/dev/null || true
      echo "$(ts) STOP loop outside window pid=${old}" >>"${LOG}"
    fi
    rm -f "${PIDFILE}"
  fi
  exit 0
fi

if [[ -f "${PIDFILE}" ]]; then
  old=$(cat "${PIDFILE}" 2>/dev/null || true)
  if [[ -n "${old}" ]] && kill -0 "${old}" 2>/dev/null; then
    # already running
    exit 0
  fi
fi

nohup "${LOOP}" >>"${LOG}" 2>&1 &
echo $! >"${PIDFILE}"
echo "$(ts) STARTED loop pid=$! interval=${RTH_SCAN_INTERVAL_SEC:-30}s" >>"${LOG}"
exit 0
