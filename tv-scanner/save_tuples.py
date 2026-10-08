#!/usr/bin/env python3
"""Save OHLCV from compact tuples and verify against MCP summary fields."""
from __future__ import annotations
import json, sys
from pathlib import Path

def save(symbol: str, tuples, summary: dict, cache_dir=Path('/workspace/tv-scanner/cache')):
    bars = [{"t":int(t),"o":float(o),"h":float(h),"l":float(l),"c":float(c),"v":float(v)}
            for t,o,h,l,c,v in tuples]
    errs = []
    if summary.get('count') is not None and len(bars) != summary['count']:
        errs.append(f"count {len(bars)}!={summary['count']}")
    if bars and summary.get('first_t') is not None and bars[0]['t'] != summary['first_t']:
        errs.append(f"first_t {bars[0]['t']}!={summary['first_t']}")
    if bars and summary.get('first_open') is not None and abs(bars[0]['o']-summary['first_open'])>1e-6:
        errs.append(f"first_open {bars[0]['o']}!={summary['first_open']}")
    if bars and summary.get('last_t') is not None and bars[-1]['t'] != summary['last_t']:
        errs.append(f"last_t {bars[-1]['t']}!={summary['last_t']}")
    if bars and summary.get('last_close') is not None and abs(bars[-1]['c']-summary['last_close'])>1e-6:
        errs.append(f"last_close {bars[-1]['c']}!={summary['last_close']}")
    if bars and summary.get('high') is not None:
        mh = max(b['h'] for b in bars)
        if abs(mh-summary['high'])>1e-6:
            errs.append(f"high {mh}!={summary['high']}")
    if bars and summary.get('low') is not None:
        ml = min(b['l'] for b in bars)
        if abs(ml-summary['low'])>1e-6:
            errs.append(f"low {ml}!={summary['low']}")
    if bars and summary.get('total_volume') is not None:
        tv = sum(b['v'] for b in bars)
        if abs(tv-summary['total_volume'])>0.5:
            errs.append(f"total_volume {tv}!={summary['total_volume']}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{symbol.replace(':','_')}.json"
    if errs:
        (cache_dir / f"{symbol.replace(':','_')}.verify_fail.json").write_text(
            json.dumps({'symbol':symbol,'errors':errs}, indent=2)+'\n')
        print(json.dumps({'ok':False,'symbol':symbol,'errors':errs}))
        return False
    payload = {'symbol':symbol,'bars':bars,'count':len(bars),'summary':summary,'source':'user-TradingView:mcp-tv-get-ohlcv'}
    out.write_text(json.dumps(payload)+'\n')
    print(json.dumps({'ok':True,'symbol':symbol,'bars':len(bars),'path':str(out)}))
    return True

if __name__ == '__main__':
    data = json.load(sys.stdin)
    save(data['symbol'], data['tuples'], data.get('summary') or {})
