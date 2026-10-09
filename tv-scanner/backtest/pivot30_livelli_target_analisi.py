import pandas as pd, numpy as np, glob
d=pd.concat([pd.read_pickle(f) for f in sorted(glob.glob('sig4_*.pkl'))],ignore_index=True)
d=d[d.rs>=80].copy(); d['day']=d.time.dt.date
days=sorted(d.day.unique()); nd=len(days); thirds=[days[0],days[nd//3],days[2*nd//3]]
d['per']=np.searchsorted(np.array(thirds[1:]),d.day.values,side='right')
F2=(d.d_ext50<=4)&(d.drop_atr<=1.5)&(d.R_atr<=0.3)&(d.gap_atr>=-0.5)&(d.lv_pdc>=-1)&(d.lv_e21_30>=-1)
A=F2&(d.n_reds>=3)
n9=lambda lo,hi: d.e9_rise & d.lv_e9.between(lo,hi)
n65=lambda lo,hi: d.s65_rise & d.lv_s65.between(lo,hi)
G={'base':pd.Series(True,index=d.index),'A':A,
 'A+EMA9 +-0.25':A&n9(-.25,.25),'A+EMA9 sopra 0..0.5':A&n9(0,.5),
 'A+SMA65 +-0.25':A&n65(-.25,.25),'A+SMA65 sopra 0..0.5':A&n65(0,.5),
 'A+entrambe +-0.25':A&n9(-.25,.25)&n65(-.25,.25),'A+entrambe +-0.5':A&n9(-.5,.5)&n65(-.5,.5),
 'A lontano da entrambe':A&~d.lv_e9.between(-.5,.5)&~d.lv_s65.between(-.5,.5)}
def val(x,T,W,BE):
    x=x[x[f'full{W}']] if W>1 else x
    if BE==0: r=np.where(x[f'h{T}_{W}'],T,np.where(x[f'stop{W}'],x[f'stopR{W}'],x[f'endR{W}']))
    else: r=x[f'be{BE}_{T}_{W}'].values
    return x, r
for W in (1,5,10):
  for BE in (0,1,2):
    print(f"\n=== {W} sedute, stop {'fisso' if BE==0 else f'a pareggio dopo +{BE}R'}: attesa R (n)   per target 2/3/5/7/10")
    for g,m in G.items():
        x,_=val(d[m],2,W,BE)
        print(f"{g:24s} n={len(x):5d} "+"  ".join(f"{T:>2d}R {val(d[m],T,W,BE)[1].mean():+.2f}" for T in (2,3,5,7,10)))
# stabilita' per periodo, finestra 5 e 10, BE0 e BE2, target 7 e 10
print('\n=== per periodo (3 terzi) attesa R')
for W in (5,10):
  for BE in (0,2):
    for T in (7,10):
      print(f'-- W{W} BE{BE} {T}R')
      for g in ('base','A','A+EMA9 +-0.25','A+SMA65 +-0.25','A+entrambe +-0.25','A+entrambe +-0.5'):
        m=G[g]; s=[]
        for p in (0,1,2):
            x,r=val(d[m&(d.per==p)],T,W,BE); s.append(f"{r.mean():+.2f}({len(x)})")
        print(f"   {g:22s} "+"  ".join(s))
print('\n=== verifica EMA9: in salita o no, tolleranza; W5 stop fisso')
for lab,m in [('A+EMA9 +-0.25 in salita',A&n9(-.25,.25)),('A+EMA9 +-0.25 NON in salita',A&~d.e9_rise&d.lv_e9.between(-.25,.25)),
              ('A+EMA9 +-0.15 in salita',A&n9(-.15,.15)),('A+EMA9 +-0.35 in salita',A&n9(-.35,.35)),
              ('A+EMA9 salita forte (3gg>0.3ATR) +-0.25',A&n9(-.25,.25)&(d.e9_slope3>0.3)),
              ('A+EMA9 +-0.25 sotto (-0.25..0)',A&n9(-.25,0)),('A+EMA9 sopra (0..0.25)',A&n9(0,.25))]:
    out=[]
    for T in (5,7,10):
        x,r=val(d[m],T,5,0); out.append(f"{T}R hit {x[f'h{T}_5'].mean():.0%} exp {r.mean():+.2f} [{' '.join(f'{val(d[m&(d.per==p)],T,5,0)[1].mean():+.2f}' for p in (0,1,2))}]")
    print(f"{lab:42s} n={m.sum():4d} "+" | ".join(out))
# serie perdenti: max perdite consecutive per A+EMA9 a 7R W5
x=d[A&n9(-.25,.25)&d.full5].sort_values('time'); w=x['h7_5'].values
mx=c=0
for v in w: c=0 if v else c+1; mx=max(mx,c)
print('A+EMA9 7R W5: max non-hit consecutivi', mx, 'su', len(w))
