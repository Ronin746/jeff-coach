import pandas as pd, numpy as np
d=pd.concat([pd.read_pickle('pat_0.pkl'),pd.read_pickle('pat_1.pkl')],ignore_index=True)
d['yr']=pd.to_datetime(d.day).dt.year
print('campioni',len(d),'titoli',d.t.nunique(), d.day.min(), d.day.max())
def row(lab,m):
    x=d[m]
    yrs=' '.join(f"{x[x.yr==y].r20.mean():+.2f}" for y in range(2017,2027))
    print(f"{lab:38s} n={len(x):6d} r10 {x.r10.mean():+.2f} r20 {x.r20.mean():+.2f} r40 {x.r40.mean():+.2f} | +2/-1 {x.h2v1.mean():.2f} +4/-2 {x.h4v2.mean():.2f} | r20 per anno {yrs}")
T=pd.Series(True,index=d.index)
row('base (RS>=70, >SMA200, adv>=50M)',T)
row('RS>=80',d.rs>=80); row('RS>=90',d.rs>=90)
row('lettura A',d.A); row('lettura B',d.B); row('A e B (Focus pattern)',d.A&d.B); row('A o B',d.A|d.B)
row('lettura C',d.Cc); row('C e (A o B)',d.Cc&(d.A|d.B))
row('triangolo',d.t_ok==True)
row('canale D ok',d.D)
for s in ['lower part of the channel','pullback to the EMAs','backtest of the broken line']:
    row(' D: '+s,d.D&(d.d_state==s))
row('canale trovato ma non zona acquisto',d.d_found&~d.D)
row('PEG',d.peg)
row('gap aperto sopra',d.gap_open==True)
for lb in d.label.dropna().unique(): row('etichetta '+lb,d.label==lb)
for sh in d.c_shape.dropna().value_counts().index[:10]: row('forma C: '+str(sh),d.c_shape==sh)
