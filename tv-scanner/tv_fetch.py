import websocket, json, random, string, time, re, sys

def sid(prefix): return prefix+''.join(random.choice(string.ascii_lowercase) for _ in range(12))
def msg(m,p):
    s=json.dumps({'m':m,'p':p},separators=(',',':'))
    return f'~m~{len(s)}~m~{s}'
def fetch(symbol,interval='5',count=420):
    cs=sid('cs_')
    ws=websocket.create_connection('wss://data.tradingview.com/socket.io/websocket', timeout=20, origin='https://www.tradingview.com', host='data.tradingview.com')
    ws.send(msg('set_auth_token',['unauthorized_user_token']))
    ws.send(msg('chart_create_session',[cs,'']))
    ws.send(msg('quote_create_session',[sid('qs_'),'']))
    desc=json.dumps({'symbol':symbol,'adjustment':'splits'})
    ws.send(msg('resolve_symbol',[cs,'symbol_1','='+desc]))
    ws.send(msg('create_series',[cs,'s1','s1','symbol_1',interval,count]))
    bars=[]; end=time.time()+30
    while time.time()<end:
        raw=ws.recv()
        for part in re.findall(r'~m~\d+~m~(\{.*?\})(?=~m~|$)',raw):
            try: x=json.loads(part)
            except: continue
            if x.get('m')=='timescale_update':
                d=x.get('p',[None,{}])[1]
                ss=(d.get('sds_1') or d.get('s1') or {}).get('s',[])
                for item in ss:
                    v=item.get('v') if isinstance(item,dict) else None
                    if isinstance(v,list) and len(v)>=6:
                        # [timestamp, open, high, low, close, volume]
                        bars.append({'t':int(v[0]),'o':v[1],'h':v[2],'l':v[3],'c':v[4],'v':v[5]})
            if x.get('m')=='series_completed':
                ws.close(); bars=bars[-count:]
                return {'bars':bars,'count':len(bars),'interval':'5m','success':True,'symbol':symbol}
    ws.close(); raise RuntimeError('timeout')
if __name__=='__main__':
 print(json.dumps(fetch(sys.argv[1], '5', int(sys.argv[2]) if len(sys.argv)>2 else 420)))
