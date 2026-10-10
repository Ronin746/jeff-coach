import pandas as pd, numpy as np
d=pd.read_pickle('pat_brk.pkl'); d['yr']=pd.to_datetime(d.day).dt.year
b=d[d.brk==True]
def row(lab,m):
    x=b[m.loc[b.index]]; tot=d[m]
    per=[x[(x.yr>=a)&(x.yr<=z)].b_r20.mean() for a,z in ((2017,2019),(2020,2021),(2022,2023),(2024,2026))]
    print(f"{lab:34s} setup {len(tot):6d} rotti {x.shape[0]/max(len(tot),1):4.0%} | r10 {x.b_r10.mean():+.2f} r20 {x.b_r20.mean():+.2f} +2/-1 {x.b_h2v1.mean():.2f} | rischio base {x.b_risk_atr.median():.1f} ATR, r20 in R {x.b_r20R.mean():+.2f} | r20 per periodo "+' '.join(f'{p:+.2f}' for p in per))
T=pd.Series(True,index=d.index)
print('Rottura del massimo a 10 giorni entro 5 sedute dal campione; esiti dall\'ingresso sulla rottura (ATR) e con stop sotto il minimo a 10 giorni (R)')
row('base',T); row('RS>=90',d.rs>=90)
row('lettura A',d.A); row('lettura B',d.B); row('A e B',d.A&d.B); row('lettura C',d.Cc); row('C e (A o B)',d.Cc&(d.A|d.B))
row('triangolo',d.t_ok==True); row('canale D ok',d.D); row('PEG',d.peg); row('gap aperto sopra',d.gap_open==True)
for sh in ['flat base','ascending base','box','descending triangle','broadening','pennant','falling wedge','bull flag','rising wedge','channel up','tight channel up']:
    row('forma C: '+sh,d.c_shape==sh)
for lb in ['box','ascending base','flag','pennant']: row('etichetta '+lb,d.label==lb)
