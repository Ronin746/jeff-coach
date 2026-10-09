"""Backtest dei segnali "30M PIVOT" (crossback EMA6/20 + MACD sui 5m) di Remy sugli ultimi ~45 giorni.

Replica la logica attuale (pivot = prima candela 30m verde dopo >=2 rosse della stessa seduta, discesa >= 0,55 ATR,
solo pivot della seduta, il pivot attivo e' l'ultimo valido, 1 crossback per pivot, morto se il 5m buca il minimo)
e misura l'esito: ingresso al close della 5m del segnale, stop sotto il minimo del pivot.
Raccoglie le caratteristiche del contesto per capire quali segnali funzionano.
"""
import os, sys, pickle, math
sys.path.insert(0, '/home/claude/repo/tv-scanner'); os.environ['TV_SCANNER_HOME'] = '/home/claude/repo/tv-scanner'
sys.path.insert(0, '/home/claude/repo')
import bisect
import numpy as np, pandas as pd, yfinance as yf
import scanner as S
S.PIVOT30_MIN_REDS = 2
from refresh_yfinance import bars_from_df
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
OUT = '/tmp/claude-0/piv'

syms = S.load_pivot_wl()
tick = sorted({s.split(':')[-1].replace('.', '-') for s in syms} | set(open(f'{OUT}/universe.txt').read().split()))
CH = int(os.environ.get('CH', 0)); NCH = int(os.environ.get('NCH', 1))
tick = tick[CH::NCH]
print('simboli', len(tick))

if not os.path.exists(f'{OUT}/raw.pkl'):
    f5 = yf.download(tick, period='58d', interval='5m', prepost=False, auto_adjust=False, group_by='ticker', progress=False, threads=True)
    fd = yf.download(tick + ['^GSPC', 'SPY'], period='2y', interval='1d', auto_adjust=False, group_by='ticker', progress=False, threads=True)
    pickle.dump((f5, fd), open(f'{OUT}/raw.pkl', 'wb'))
f5, fd = pickle.load(open(f'{OUT}/raw.pkl', 'rb'))


def ema(a, n):
    out = np.empty(len(a)); k = 2 / (n + 1); out[0] = a[0]
    for i in range(1, len(a)):
        out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out


spx = fd['^GSPC'].dropna(subset=['Close'])
rows = []
for t in tick:
    try:
        sub5 = f5[t].dropna(subset=['Close'])
        subd = fd[t].dropna(subset=['Close'])
    except Exception:
        continue
    if len(sub5) < 500 or len(subd) < 260:
        continue
    b5 = bars_from_df(sub5)
    bd = bars_from_df(subd)
    bd_days = [datetime.fromtimestamp(int(x['t']), ET).date() for x in bd]
    closed = S.closed_rth_5m(b5, b5[-1]['t'] + 400)
    closed = sorted(closed, key=lambda b: int(b['t']))
    if len(closed) < 300:
        continue
    T = np.array([b['t'] for b in closed]); H = np.array([b['h'] for b in closed]); L = np.array([b['l'] for b in closed])
    Cc = np.array([b['c'] for b in closed]); V = np.array([b['v'] for b in closed]); O = np.array([b['o'] for b in closed])
    day5 = np.array([datetime.fromtimestamp(int(x), ET).date() for x in T])
    e6, e20 = ema(Cc, 6), ema(Cc, 20)
    macd = ema(Cc, 6) - ema(Cc, 20); sig = ema(macd, 9)
    cross = np.r_[False, (e6[:-1] <= e20[:-1]) & (e6[1:] > e20[1:])] & (macd > sig)
    # VWAP di seduta
    tp = (H + L + Cc) / 3
    vwap = np.empty(len(Cc))
    for d in np.unique(day5):
        m = day5 == d
        vwap[m] = np.cumsum(tp[m] * V[m]) / np.maximum(np.cumsum(V[m]), 1)
    b30 = S.rebuild_30m_bars(closed)
    c30 = np.array([b['c'] for b in b30]); e8_30, e21_30 = ema(c30, 8), ema(c30, 21)
    v30 = np.array([b['v'] for b in b30])
    # daily: indicatori al close del giorno prima
    dC = subd.Close; dates = [x.date() for x in subd.index]
    dE8, dE21, dS50 = dC.ewm(span=8, adjust=False).mean(), dC.ewm(span=21, adjust=False).mean(), dC.rolling(50).mean()
    tr = pd.concat([subd.High - subd.Low, (subd.High - dC.shift()).abs(), (subd.Low - dC.shift()).abs()], axis=1).max(axis=1)
    dATR = tr.ewm(alpha=1 / 14, adjust=False).mean()
    from jeffcoach import indicators as I
    dE9 = dC.ewm(span=9, adjust=False).mean()
    # barre 65m (RTH 9:30, 6 per seduta) dalle 5m chiuse
    mins_rth = np.array([(datetime.fromtimestamp(int(x), ET).hour * 60 + datetime.fromtimestamp(int(x), ET).minute - 570) for x in T])
    bk = mins_rth // 65
    key = [(d_, b_) for d_, b_ in zip(day5, bk)]
    b65_end_t, b65_c = [], []
    for ii in range(len(T)):
        if ii == len(T) - 1 or key[ii + 1] != key[ii]:
            b65_end_t.append(T[ii] + 300); b65_c.append(Cc[ii])
    b65_end_t = np.array(b65_end_t); s30_65 = pd.Series(b65_c).rolling(30).mean().to_numpy()
    def _s65(tt, pl_, A_):
        k_ = np.searchsorted(b65_end_t, tt, side='right') - 1
        if k_ < 30:
            return dict(lv_s65=np.nan, s65_rise=False)
        return dict(lv_s65=(pl_ - s30_65[k_]) / A_, s65_rise=bool(s30_65[k_] > s30_65[k_ - 6]), px_s65=(Cc[np.searchsorted(T, tt) - 1] - s30_65[k_]) / A_)
    # pivot: per ogni verde 30m qualificata
    piv = []
    for j in range(1, len(b30)):
        g = b30[j]
        if not S._bar_is_green(g):
            continue
        gday = S._et_day(g['t'])
        k = j - 1; n_reds = 0
        while k >= 0 and S._bar_is_red(b30[k]) and S._et_day(b30[k]['t']) == gday:
            n_reds += 1; k -= 1
        bd_before = bd[:bisect.bisect_left(bd_days, gday)]
        if len(bd_before) < 30:
            continue
        if n_reds < S._pivot30_min_reds(gday, b30, bd_before, closed):
            continue
        atr = S.daily_atr14(bd_before, now=int(g['t']))
        info = S._pivot30_drop(b30, j, daily_bars=bd_before, bars_5m=closed)
        if atr is None or info is None or info[0] < S.PIVOT30_ATR_MULT * atr:
            continue
        piv.append((j, g, n_reds, info, atr))
    # segnali: pivot attivo = l'ultimo valido; un crossback per pivot; stessa seduta; stop non toccato
    for pi, (j, g, n_reds, info, atr) in enumerate(piv):
        gt = int(g['t']); gend = gt + 1800; gday = S._et_day(gt)
        nxt_gt = piv[pi + 1][1]['t'] if pi + 1 < len(piv) else None
        ph, pl = float(g['h']), float(g['l'])
        idx = np.where((T >= gend) & (day5 == gday))[0]
        fired_c = fired_b = None
        for i in idx:
            if nxt_gt is not None and T[i] >= nxt_gt + 1800:
                break                                # c'e' un pivot piu' recente
            if L[i] < pl:
                break                                # stop bucato: pivot morto
            if fired_c is None and cross[i]:
                fired_c = i
            if fired_b is None and H[i] > ph:
                fired_b = i
            if fired_c is not None and fired_b is not None:
                break
        for kind, fi in (('cross', fired_c),):
            if fi is None:
                continue
            i = fi
            entry = Cc[i] if kind == 'cross' else max(ph + 0.01, O[i])
            R = entry - pl
            if R <= 0:
                continue
            alld = sorted(set(day5[i:]))
            TG = (2, 3, 5, 7, 10)
            res = {}
            for W in (1, 3, 5, 10):
                days = alld[:W]
                fw = np.where((T > T[i]) & np.isin(day5, days))[0]
                for BE in (1, 2, 3):
                    # stop a pareggio dopo +BE R (dalla barra successiva); per ogni target: esito in R
                    for kk in TG:
                        stp = pl; out_ = None
                        for q in fw:
                            if L[q] <= stp:
                                out_ = (min(O[q], stp) - entry) / R; break
                            if H[q] >= entry + kk * R:
                                out_ = kk; break
                            if H[q] >= entry + BE * R:
                                stp = max(stp, entry)
                        if out_ is None:
                            out_ = ((Cc[fw[-1]] if len(fw) else entry) - entry) / R
                        res[f'be{BE}_{kk}_{W}'] = out_
                hit = {k: None for k in TG}; stop_at = None; stop_px = pl; mfe = 0
                for q in fw:
                    if L[q] <= pl:
                        stop_at = q; stop_px = min(O[q], pl); break
                    mfe = max(mfe, (H[q] - entry) / R)
                    for kk in TG:
                        if hit[kk] is None and H[q] >= entry + kk * R:
                            hit[kk] = q
                last_c = Cc[fw[-1]] if len(fw) else entry
                res[f'full{W}'] = len(days) == W
                res[f'stopR{W}'] = (stop_px - entry) / R if stop_at is not None else np.nan
                res[f'endR{W}'] = (last_c - entry) / R
                res[f'mfe{W}'] = mfe
                for kk in TG:
                    res[f'h{kk}_{W}'] = hit[kk] is not None and (stop_at is None or hit[kk] < stop_at)
                res[f'stop{W}'] = stop_at is not None
            hit = {1: None, 2: None, 3: None}; stop_at = None; mfe = 0
            eod = np.where((day5 == gday) & (T >= T[i]))[0]
            eod_r = ((Cc[eod[-1]] if len(eod) else entry) - entry) / R
            di = max(ix for ix, dd in enumerate(dates) if dd < gday)
            dclose = float(dC.iloc[di]); A = float(dATR.iloc[di])
            sess = np.where(day5 == gday)[0]
            rows.append(dict(
                kind=kind, t=t, time=datetime.fromtimestamp(int(T[i]), ET), green=datetime.fromtimestamp(gt, ET), n_reds=n_reds,
                drop_atr=info[0] / atr, R_atr=R / atr, R_pct=R / entry * 100, entry=entry, ph=ph, pl=pl,
                eod_r=eod_r,
                d_above_e21=dclose > dE21.iloc[di], d_above_s50=dclose > dS50.iloc[di],
                d_ext50=(dclose - dS50.iloc[di]) / A,
                rs=I.rs_rating(I.rs_raw(list(dC.iloc[:di + 1].values), list(spx.Close.reindex(subd.index[:di + 1]).ffill().values))),
                lv_e8=(pl - dE8.iloc[di]) / A, lv_e21=(pl - dE21.iloc[di]) / A, lv_s50=(pl - dS50.iloc[di]) / A,
                lv_pdl=(pl - subd.Low.iloc[di]) / A, lv_pdc=(pl - dclose) / A,
                lv_vwap=(pl - vwap[i]) / A, lv_e21_30=(pl - e21_30[j]) / A,
                gap_atr=(O[sess[0]] - dclose) / A, gvol=v30[j] / max(np.mean(v30[max(0, j - 65):j]), 1),
                mins=(T[i] - T[sess[0]]) / 60,
                lv_e9=(pl - dE9.iloc[di]) / A, e9_rise=bool(dE9.iloc[di] > dE9.iloc[di - 1]), e9_slope3=float((dE9.iloc[di] - dE9.iloc[di - 3]) / A),
                e9_proj=(pl - (dE9.iloc[di] * 0.8 + Cc[i] * 0.2)) / A,
                **_s65(gt + 1800, pl, A),
                **res,
            ))
    print(t, len(piv), sum(1 for r in rows if r['t'] == t), flush=True)

df = pd.DataFrame(rows)
df.to_pickle(f'{OUT}/sig4_{CH}.pkl')
print('segnali', len(df))
