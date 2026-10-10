import pandas as pd, numpy as np, pickle
d=pd.concat([pd.read_pickle('pat_0.pkl'),pd.read_pickle('pat_1.pkl')],ignore_index=True)
tick,raw=pickle.load(open('d10.pkl','rb'))
out=[]
for t,g in d.groupby('t'):
    df=raw[t].dropna(subset=['Close']); idx={x:i for i,x in enumerate(df.index)}
    O,H,L,C=(df[k].to_numpy(float) for k in ('Open','High','Low','Close')); n=len(C)
    for ri,r in g.iterrows():
        j=idx[r.day]; piv=H[j-9:j+1].max(); lo=L[j-9:j+1].min(); A=r.atr
        e=None
        for k in range(j+1,min(n,j+6)):
            if H[k]>piv: e=k; break
        if e is None: out.append((ri,False,np.nan,np.nan,np.nan,np.nan,np.nan)); continue
        en=max(O[e],piv)
        r20=(C[e+20]-en)/A if e+20<n else np.nan
        r10=(C[e+10]-en)/A if e+10<n else np.nan
        # +2/-1 ATR dall'ingresso, dal giorno dopo (il giorno d'ingresso: conta solo il close)
        res=np.nan
        if e+20<n:
            res=0.5
            if C[e]<=en-A: res=0.0
            else:
                for k in range(e+1,e+21):
                    if L[k]<=en-A: res=0.0; break
                    if H[k]>=en+2*A: res=1.0; break
        # stop sotto il minimo della base: perdita in R e risultato a 20 sedute in R
        R=en-lo
        rr=(C[e+20]-en)/R if (e+20<n and R>0) else np.nan
        if e+20<n and R>0 and L[e:e+21].min()<lo: rr=-1.0
        out.append((ri,True,r10,r20,res,R/A,rr))
o=pd.DataFrame(out,columns=['ri','brk','b_r10','b_r20','b_h2v1','b_risk_atr','b_r20R']).set_index('ri')
d=d.join(o); d.to_pickle('pat_brk.pkl'); print('ok',d.brk.mean())
