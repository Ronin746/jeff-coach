cd /tmp/claude-0/dtl
run(){ NAME=$1 VAR="$2" CH=0 NCH=2 python sweep_dtl.py & NAME=$1 VAR="$2" CH=1 NCH=2 python sweep_dtl.py; wait; }
run attuale '{}'
run tocco04 '{"touch_atr":0.4}'
run tocco09 '{"touch_atr":0.9}'
run pulita '{"tol_atr":0.15,"max_violations":1}'
run larga '{"tol_atr":0.5,"max_violations":5}'
run pivot5 '{"pivot_k":5}'
run pivot2 '{"pivot_k":2}'
run rottura03 '{"break_atr":0.3}'
run gap15 '{"min_gap":15}'
echo FINITO
