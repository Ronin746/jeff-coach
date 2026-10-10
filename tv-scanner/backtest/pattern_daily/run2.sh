cd /tmp/claude-0/dtl
run(){ NAME=$1 VAR="$2" CH=0 NCH=2 python sweep_dtl.py & NAME=$1 VAR="$2" CH=1 NCH=2 python sweep_dtl.py; wait; }
run p2r03 '{"pivot_k":2,"break_atr":0.3}'
run p2r05 '{"pivot_k":2,"break_atr":0.5}'
run r05 '{"break_atr":0.5}'
echo FINITO
