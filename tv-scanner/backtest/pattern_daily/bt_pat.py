"""Backtest su ~9 anni di daily di tutti i riconoscimenti della lista (letture A, B, C, triangolo, canale D, trendline
discendente, PEG, gap), calcolati come nella lista vera, senza dati futuri.

Campione: ogni 5 sedute, titoli con RS (percentile vero del giorno su tutto l'universo) >= 70, sopra la SMA200,
adv$ >= 50M. Per ogni campione si salvano le letture e gli esiti dopo (in ATR del giorno):
  r5/r10/r20/r40 = close tra N sedute; mfe20/mae20; h2v1 = +2 ATR prima di -1 ATR (20 sedute), h4v2 idem.
Rotture della trendline: misurate dal giorno della rottura (rilette con i dati fino a quel giorno).
"""
import os, sys, pickle, time
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/repo')
from jeffcoach import config as C, engine as E, daily as DA, peg as PG, dtl as D, channel as CH, patterns as P
import logging; logging.disable(logging.WARNING)

C.DTL['min_touches'] = 2          # per confrontare 2 tocchi con 3+
CHN = int(os.environ.get('CH', 0)); NCH = int(os.environ.get('NCH', 1))
tick, d = pickle.load(open('/tmp/claude-0/dtl/d10.pkl', 'rb'))
spx = d['^GSPC'].Close.dropna()

# RS vero: percentile del punteggio di forza tra tutti i titoli, giorno per giorno
closes = pd.DataFrame({t: d[t].Close for t in tick}).reindex(spx.index)
def strength(cl):
    s = 0
    for p, w in ((63, .4), (126, .2), (189, .2), (252, .2)):
        s = s + w * cl / cl.shift(p)
    return s
st = strength(closes)
rs = (st.rank(axis=1, pct=True) * 98 + 1)
vol = pd.DataFrame({t: d[t].Volume for t in tick}).reindex(spx.index)
adv = (closes * vol).shift(1).rolling(50).mean()
sma200 = closes.rolling(200).mean()

def outcomes(c, h, l, i, atr):
    n = len(c); out = {}
    for k in (5, 10, 20, 40):
        out[f'r{k}'] = (c[i + k] - c[i]) / atr if i + k < n else np.nan
    if i + 20 >= n:
        out.update(mfe20=np.nan, mae20=np.nan, h2v1=np.nan, h4v2=np.nan); return out
    hh, ll = h[i + 1:i + 21], l[i + 1:i + 21]
    out['mfe20'] = (hh.max() - c[i]) / atr; out['mae20'] = (c[i] - ll.min()) / atr
    for tag, up, dn in (('h2v1', 2, 1), ('h4v2', 4, 2)):
        res = 0.0
        for a, b in zip(hh, ll):
            if b <= c[i] - dn * atr: res = 0.0; break
            if a >= c[i] + up * atr: res = 1.0; break
        else:
            res = 0.5
        out[tag] = res
    return out

KEYS = ['rs', 'close', 'atr', 'ext', 'adr_pct', 'off_52w_high_pct', 'vcp', 'ret21_pct', 'ret63_pct',
        'a_range10_adr', 'a_off_high20_pct', 'a_close5_adr', 'a_thrust60_pct', 'last_range_adr',
        'b_rally20_atr', 'b_range5_atr', 'b_slope_h8', 'b_slope_l8', 'b_thrust_atr', 'b_pullback_atr', 'c_retrace',
        't_ok', 'c_ok_data', 'gap_open', 'gap_dist_atr', 'sma50', 'ema21', 'sma200_slope_ok']

def _shape(m):
    try:
        return P.shape(m)
    except Exception:
        return None

rows, drows = [], []
t0 = time.time()
mine = tick[CHN::NCH]
for ti, t in enumerate(mine):
    df = d[t].dropna(subset=['Close'])
    if len(df) < 320:
        continue
    pos = {x: j for j, x in enumerate(df.index)}
    c, h, l = (df[k].to_numpy(float) for k in ('Close', 'High', 'Low'))
    seen_breaks = set()
    for j in range(260, len(df), 5):
        day = df.index[j]
        r = rs.at[day, t] if day in rs.index else np.nan
        if not (r >= 70) or not (c[j] > sma200.at[day, t]) or not (adv.at[day, t] >= 50e6):
            continue
        sub = df.iloc[j - 259:j + 1]
        m = E.compute_metrics(sub, spx)
        if not m:
            continue
        m['rs'] = float(r)
        DA.add_channel(m, sub)
        try:
            m.update(PG.read_peg(sub, m['atr']))
        except Exception:
            pass
        okA = E.reading_a(m)[0]; okB = E.reading_b(m)[0]
        try:
            okC = P.reading_c(m)[0]
        except Exception:
            okC = False
        row = dict(t=t, day=day, A=okA, B=okB, Cc=okC, D=bool(m.get('pattern_d_ok')), d_state=m.get('d_state'),
                   d_found=bool(m.get('d_found')), d_width=m.get('d_width_atr'), c_shape=_shape(m),
                   peg=bool(m.get('peg_ok')), label=E.pattern_label(m),
                   **{k: m.get(k) for k in KEYS}, **outcomes(c, h, l, j, m['atr']))
        rows.append(row)
        # trendline: rottura negli ultimi 5 giorni -> rileggi al giorno della rottura
        if m.get('dt_broken') and m.get('dt_break_ago', 99) <= 4:
            b = j - m['dt_break_ago']
            key = (m.get('dt_start'), round(m.get('dt_slope', 0), 6))
            if key in seen_breaks or b < 260:
                continue
            subb = df.iloc[b - 259:b + 1]
            mb = E.compute_metrics(subb, spx)
            if not mb or not mb.get('dt_broken') or mb.get('dt_break_ago') != 0:
                continue
            seen_breaks.add(key)
            dayb = df.index[b]
            a_i = pos[pd.Timestamp(mb['dt_start'])]
            kk = np.arange(b, min(len(c), b + 11))
            line = mb['dt_start_high'] + mb['dt_slope'] * (kk - a_i)
            fail = bool(np.any(c[kk] < line))
            drows.append(dict(t=t, day=dayb, rs=float(rs.at[dayb, t]), touches=mb['dt_touches'], drop=mb['dt_drop_pct'],
                              span=mb['dt_span'], slope=mb['dt_slope'] / mb['atr'], vol=mb.get('dt_break_vol'),
                              conf=mb.get('dt_confirm_vol'), above_atr=(c[b] - mb['dt_break_line']) / mb['atr'],
                              ext=mb.get('ext'), above200=bool(c[b] > sma200.at[dayb, t]), ret63=mb.get('ret63_pct'),
                              off52=mb.get('off_52w_high_pct'), fail10=fail, **outcomes(c, h, l, b, mb['atr'])))
    if ti % 20 == 0:
        print(CHN, ti, len(mine), len(rows), len(drows), round(time.time() - t0), flush=True)
pd.DataFrame(rows).to_pickle(f'/tmp/claude-0/dtl/pat_{CHN}.pkl')
pd.DataFrame(drows).to_pickle(f'/tmp/claude-0/dtl/brk_{CHN}.pkl')
print('fine', len(rows), len(drows), round(time.time() - t0))
