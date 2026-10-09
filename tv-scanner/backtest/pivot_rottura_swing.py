"""Pivot intraday (30m o 60m) con ingresso sulla rottura del massimo del pivot. Uscita su piu' sedute (swing).
pivot = prima candela verde dopo >= MINR rosse della stessa seduta, discesa dal massimo di seduta >= 0,55 ATR.
Ingresso: prima barra successiva (stessa seduta o la seguente) con massimo > massimo del pivot; prezzo max(ph+0.01, open).
Il pivot muore se prima della rottura il minimo viene bucato o se nasce un pivot piu' recente. Stop = minimo del pivot."""
import sys, os, pickle, numpy as np, pandas as pd
sys.path.insert(0,'/home/claude/repo')
from jeffcoach import indicators as I, dtl as D
MODE=os.environ['MODE']; CH=int(os.environ.get('CH',0)); NCH=int(os.environ.get('NCH',1))
if MODE=='30':
    f5,fd=pickle.load(open('raw.pkl','rb'))
    tick=sorted({c[0] for c in f5.columns}); spx=fd['^GSPC'].dropna(subset=['Close'])
else:
    tick,f5,fd=pickle.load(open('raw60.pkl','rb')); spx=fd['^GSPC'].dropna(subset=['Close'])
tick=[t for t in tick if not t.startswith('^') and t!='SPY'][CH::NCH]
TG=(3,5,7,10); WS=(5,10)
rows=[]
for t in tick:
    try:
        ib=f5[t].dropna(subset=['Close']); dd=fd[t].dropna(subset=['Close'])
    except Exception: continue
    if len(ib)<200 or len(dd)<300: continue
    ib=ib.tz_convert('America/New_York')
    ib=ib[(ib.index.hour*60+ib.index.minute>=570)&(ib.index.hour*60+ib.index.minute<960)]
    if MODE=='30':
        ib=ib.groupby([ib.index.date, ((ib.index.hour*60+ib.index.minute-570)//30)]).agg(
            Open=('Open','first'),High=('High','max'),Low=('Low','min'),Close=('Close','last'),Volume=('Volume','sum'))
        days_i=np.array([k[0] for k in ib.index])
    else:
        days_i=np.array(ib.index.date)
    O,H,L,C=(ib[x].to_numpy(float) for x in ('Open','High','Low','Close'))
    n=len(C)
    dC=dd.Close; ddays=np.array([x.date() for x in dd.index])
    tr=pd.concat([dd.High-dd.Low,(dd.High-dC.shift()).abs(),(dd.Low-dC.shift()).abs()],axis=1).max(axis=1)
    dATR=tr.ewm(alpha=1/14,adjust=False).mean(); dE9=dC.ewm(span=9,adjust=False).mean(); dE21=dC.ewm(span=21,adjust=False).mean(); dS50=dC.rolling(50).mean()
    spxc=spx.Close.reindex(dd.index).ffill().to_numpy(); dcv=dC.to_numpy()
    useq=sorted(set(days_i)); dpos={d:i for i,d in enumerate(useq)}
    sess_first={}
    for i,d in enumerate(days_i):
        sess_first.setdefault(d,i)
    dtl_cache={}; rs_cache={}
    # pivot
    piv=[]
    for j in range(1,n):
        if not C[j]>O[j]: continue
        d=days_i[j]; k=j-1; nr=0
        while k>=0 and days_i[k]==d and C[k]<O[k]: nr+=1; k-=1
        if nr<2: continue
        di=np.searchsorted(ddays,d)-1          # ultimo daily prima della seduta
        if di<260: continue
        A=float(dATR.iloc[di]); s0=sess_first[d]
        drop=H[s0:j+1].max()-L[j-nr:j+1].min()
        if drop<0.55*A: continue
        piv.append((j,nr,di,A,drop))
    for pi,(j,nr,di,A,drop) in enumerate(piv):
        d=days_i[j]; ph,pl=H[j],L[j]
        nxt=piv[pi+1][0] if pi+1<len(piv) else n
        last_day=useq[min(dpos[d]+1,len(useq)-1)]
        e=None
        for i in range(j+1,min(n,nxt+1)):
            if days_i[i]>last_day: break
            if H[i]>ph:
                e=i; break
            if L[i]<pl: break
        if e is None: continue
        entry=max(ph+0.01,O[e]); R=entry-pl
        if R<=0: continue
        res={}
        for W in WS:
            lastd=useq[dpos[days_i[e]]+W-1] if dpos[days_i[e]]+W-1<len(useq) else None
            full=lastd is not None
            end=np.searchsorted(days_i, lastd, side='right') if full else n
            res[f'full{W}']=full
            for T in TG:
                out=None
                for q in range(e,end):
                    if q==e:
                        if C[q]<=pl: out=(pl-entry)/R; break
                        if C[q]>=entry+T*R: out=T; break
                        continue
                    if L[q]<=pl: out=(min(O[q],pl)-entry)/R; break
                    if H[q]>=entry+T*R: out=T; break
                res[f'r{T}_{W}']=out if out is not None else (C[end-1]-entry)/R
                res[f'h{T}_{W}']=out==T
        if di not in rs_cache:
            rs_cache[di]=I.rs_rating(I.rs_raw(list(dcv[:di+1]),list(spxc[:di+1])))
        if di not in dtl_cache:
            dtl_cache[di]=D.read_dtl(dd.iloc[max(0,di-259):di+1],A)
        m=dtl_cache[di]; dcl=float(dC.iloc[di])
        rows.append(dict(t=t,day=d,eday=days_i[e],same=days_i[e]==d,nr=nr,drop_atr=drop/A,R_atr=R/A,rs=rs_cache[di],
            ext50=(dcl-dS50.iloc[di])/A,gap=(O[sess_first[d]]-dcl)/A,lv_pdc=(pl-dcl)/A,
            lv_e9=(pl-dE9.iloc[di])/A,e9_rise=bool(dE9.iloc[di]>dE9.iloc[di-1]),lv_e21=(pl-dE21.iloc[di])/A,
            dt_broken=m.get('dt_broken',False),ago=m.get('dt_break_ago',np.nan),bvol=m.get('dt_break_vol',np.nan),
            cvol=m.get('dt_confirm_vol',np.nan),dist=m.get('dt_dist_atr',np.nan),**res))
    print(t,len(piv),flush=True)
pd.DataFrame(rows).to_pickle(f'h{MODE}_{CH}.pkl')
