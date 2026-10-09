import pandas as pd, numpy as np, glob, sys
MODE=sys.argv[1]; NP=int(sys.argv[2]); RMAX=float(sys.argv[3]); MINR=int(sys.argv[4])
d=pd.concat([pd.read_pickle(f) for f in sorted(glob.glob(f'h{MODE}_*.pkl'))],ignore_index=True)
d=d[(d.rs>=80)&(d.nr>=MINR)].copy()
days=sorted(d.day.unique()); nd=len(days); cuts=np.array([days[int(nd*k/NP)] for k in range(1,NP)])
d['per']=np.searchsorted(cuts,d.day.values,side='right')
Q=(d.ext50<=4)&(d.drop_atr<=1.5)&(d.R_atr<=RMAX)&(d.gap>=-0.5)&(d.lv_pdc>=-1)
vol=(d.bvol>=1.5)|(d.cvol>=1.5)
brk=lambda k: d.dt_broken.fillna(False).astype(bool)&(d.ago<=k)&(d.dist>=-1)
E9=d.e9_rise&d.lv_e9.between(-.25,.25)
G={'tutti RS>=80':pd.Series(True,index=d.index),'Q qualita':Q,'Q senza rottura DTL':Q&~d.dt_broken.fillna(False).astype(bool),
 'Q + DTL<=10 SENZA vol':Q&brk(10)&~vol,'Q + DTL<=10 vol':Q&brk(10)&vol,'Q + DTL<=20 vol':Q&brk(20)&vol,
 'Q + DTL<=20 vol, <=2ATR sopra':Q&brk(20)&vol&(d.dist<=2),'Q + EMA9 salita +-0.25':Q&E9,'Q + DTL<=20 vol + EMA9':Q&brk(20)&vol&E9,
 'DTL<=20 vol (senza Q)':brk(20)&vol}
print(f'MODE {MODE}m  sedute {nd}  dal {days[0]} al {days[-1]}  rischio max {RMAX} ATR  rosse >= {MINR}')
for W in (5,10):
    print(f'\n== tenuta {W} sedute, stop fisso: % target presi, attesa R, [periodi]')
    for g,m in G.items():
        x=d[m&d[f'full{W}']]; cells=[]
        for T in (3,5,7,10):
            per=' '.join(f"{d[m&d[f'full{W}']&(d.per==p)][f'r{T}_{W}'].mean():+.2f}" for p in range(NP))
            cells.append(f"{T}R {x[f'h{T}_{W}'].mean():3.0%} {x[f'r{T}_{W}'].mean():+.2f} [{per}]")
        print(f"{g:30s} n={len(x):5d} ({m.sum()/nd*5:4.1f}/sett) | "+" | ".join(cells))
