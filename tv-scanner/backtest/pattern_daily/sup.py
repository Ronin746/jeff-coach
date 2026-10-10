import os,sys,pickle,numpy as np,pandas as pd
sys.path.insert(0,'/home/claude/repo')
from jeffcoach import patterns as P
CH=int(os.environ['CH']); NCH=2
d=pd.read_pickle('pat_brk.pkl'); tick,raw=pickle.load(open('d10.pkl','rb'))
ts=sorted(d.t.unique())[CH::NCH]; out=[]
for t in ts:
    df=raw[t].dropna(subset=['Close']); idx={x:i for i,x in enumerate(df.index)}
    for ri,r in d[d.t==t].iterrows():
        j=idx[r.day]; sub=df.iloc[j-259:j+1]
        try: m=P.read_structure(sub,r.atr)
        except Exception: continue
        out.append(dict(ri=ri,uc=m.get('c_undercut_reclaim'),kind=m.get('c_kind'),dry=m.get('c_vol_dryup'),dup=m.get('c_dist_upper_atr'),retr=m.get('c_retrace'),thr=m.get('c_thrust_pct')))
pd.DataFrame(out).to_pickle(f'sup_{CH}.pkl'); print('ok',len(out))
