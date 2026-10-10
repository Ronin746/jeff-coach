"""Varianti del disegno della trendline discendente sugli stessi campioni (2017-2026)."""
import os, sys, pickle, json, numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/repo')
from jeffcoach import config as C, dtl as D, indicators as I
VAR = json.loads(os.environ['VAR']); NAME = os.environ['NAME']; CHN = int(os.environ['CH']); NCH = int(os.environ['NCH'])
base = dict(C.DTL); C.DTL.update(VAR)
s = pd.read_pickle('pat_brk.pkl')[['t', 'day', 'rs']]
tick, raw = pickle.load(open('d10.pkl', 'rb'))
def outc(c, h, l, i, atr):
    n = len(c); o = {f'r{k}': (c[i + k] - c[i]) / atr if i + k < n else np.nan for k in (10, 20, 40)}
    res = np.nan
    if i + 20 < n:
        res = 0.5
        for a, b in zip(h[i + 1:i + 21], l[i + 1:i + 21]):
            if b <= c[i] - atr: res = 0.; break
            if a >= c[i] + 2 * atr: res = 1.; break
    o['h2v1'] = res; return o
rows = []
for t in sorted(s.t.unique())[CHN::NCH]:
    df = raw[t].dropna(subset=['Close']); idx = {x: i for i, x in enumerate(df.index)}
    c, h, l = (df[k].to_numpy(float) for k in ('Close', 'High', 'Low'))
    atr_s = I.atr(df).to_numpy(); seen = set()
    for day in s.day[s.t == t]:
        j = idx[day]; m = D.read_dtl(df.iloc[j - 259:j + 1], atr_s[j])
        if not (m.get('dt_broken') and m.get('dt_break_ago', 99) <= 4): continue
        b = j - m['dt_break_ago']
        if b in seen or b < 260: continue
        mb = D.read_dtl(df.iloc[b - 259:b + 1], atr_s[b])
        if not (mb.get('dt_broken') and mb.get('dt_break_ago') == 0): continue
        seen.add(b)
        a_i = idx[pd.Timestamp(mb['dt_start'])]; kk = np.arange(b, min(len(c), b + 11))
        fail = bool(np.any(c[kk] < mb['dt_start_high'] + mb['dt_slope'] * (kk - a_i)))
        rows.append(dict(t=t, day=df.index[b], touches=mb['dt_touches'], drop=mb['dt_drop_pct'], span=mb['dt_span'],
                         vol=mb.get('dt_break_vol'), conf=mb.get('dt_confirm_vol'), fail10=fail, **outc(c, h, l, b, atr_s[b])))
pd.DataFrame(rows).to_pickle(f'sw_{NAME}_{CHN}.pkl'); print(NAME, CHN, len(rows))
