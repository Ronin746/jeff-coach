import pickle,numpy as np,pandas as pd
d=pd.read_pickle('pat_brk.pkl'); d=d[pd.to_datetime(d.day)>='2024-01-01']
tick60,h60,_=pickle.load(open('/tmp/claude-0/piv/raw60.pkl','rb')); tick,raw=pickle.load(open('d10.pkl','rb'))
have=set(c[0] for c in h60.columns)
out=[]
for t,g in d.groupby('t'):
    if t not in have: continue
    x=h60[t].dropna(subset=['Close'])
    if len(x)<200: continue
    x=x.tz_convert('America/New_York'); cl=x.Close.to_numpy(); sma=pd.Series(cl).rolling(30).mean().to_numpy()
    days=np.array(x.index.date)
    df=raw[t].dropna(subset=['Close']); didx={k.date():i for i,k in enumerate(df.index)}; C=df.Close.to_numpy(); H=df.High.to_numpy(); L=df.Low.to_numpy()
    for ri,r in g.iterrows():
        d0=r.day.date(); ud=sorted(set(days[days>d0]))[:5]
        if not ud: continue
        m=np.where(np.isin(days,ud))[0]
        e=None
        for k in m:
            if k>0 and cl[k]>sma[k] and cl[k-1]<=sma[k-1]: e=k; break
        if e is None: continue
        en=cl[e]; ed=days[e]; j=didx.get(ed)
        if j is None or j+20>=len(C): continue
        A=r.atr
        res=0.5
        for q in range(j+1,j+21):
            if L[q]<=en-A: res=0;break
            if H[q]>=en+2*A: res=1;break
        out.append(dict(ri=ri,e_r10=(C[j+10]-en)/A,e_r20=(C[j+20]-en)/A,e_h=res))
o=pd.DataFrame(out).set_index('ri'); d=d.join(o,how='inner')
def row(lab,m):
    x=d[m]; print(f"{lab:36s} n={len(x):5d} r10 {x.e_r10.mean():+.2f} r20 {x.e_r20.mean():+.2f} +2/-1 {x.e_h.mean():.2f}")
T=pd.Series(True,index=d.index)
print('Ingresso: primo close a 60m che riprende la SMA30 a 60m nelle 5 sedute dopo (dal 2024)')
row('base',T); row('base RS>=90',d.rs>=90)
row('canale D ok',d.D); row('canale D ok RS>=90',d.D&(d.rs>=90))
for s in ['lower part of the channel','pullback to the EMAs','backtest of the broken line']: row('D '+s,d.D&(d.d_state==s))
row('lettura C ok',d.Cc); row('A e B',d.A&d.B)
