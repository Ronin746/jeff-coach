#!/usr/bin/env python3
"""Ingest one MCP OHLCV response from stdin -> cache + per-symbol result + trend row."""
from __future__ import annotations
import json, sys
from pathlib import Path
from importlib.machinery import SourceFileLoader

BASE = Path('/workspace/tv-scanner')
CACHE = BASE / 'cache'
RESULTS = BASE / 'results'
TREND = BASE / 'results' / 'trend_rows.jsonl'
sc = SourceFileLoader('scanner', str(BASE / 'scanner.py')).load_module()

def main():
    data = json.load(sys.stdin)
    symbol = data.get('symbol') or sys.argv[1]
    bars = data.get('bars') or []
    CACHE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not bars and not (data.get('success') is False or data.get('error')):
        out = {'symbol': symbol, 'ok': False, 'error': 'empty_bars_refused'}
        print(json.dumps(out)); return
    if data.get('success') is False or data.get('error'):
        out = {'symbol': symbol, 'ok': False, 'error': data.get('error', 'failed')}
        (RESULTS / f"{symbol.replace(':','_')}.json").write_text(json.dumps(out)+'\n')
        print(json.dumps(out)); return
    payload = {
        'symbol': symbol,
        'bars': bars,
        'count': len(bars),
        'summary': data.get('summary'),
        'source': 'user-TradingView:mcp-tv-get-ohlcv',
    }
    (CACHE / f"{symbol.replace(':','_')}.json").write_text(json.dumps(payload)+'\n')
    # trend filter
    sma = sc.rebuild_sma30_65m(bars)
    closed = sc.closed_rth_5m(bars)
    price = float(closed[-1]['c']) if closed else None
    pass_trend = (sma is not None and price is not None and price > sma)
    trend_row = {
        'symbol': symbol,
        'price': price,
        'sma30_65m': sma,
        'pass': pass_trend,
    }
    with TREND.open('a') as f:
        f.write(json.dumps(trend_row)+'\n')
    sigs, reason = sc.scan_symbol(symbol, bars=bars)
    out = {
        'symbol': symbol,
        'ok': True,
        'bars': len(bars),
        'trend': trend_row,
        'reason': reason,
        'signals': [
            {
                'trigger': s.trigger, 'price': s.price, 'ema6': s.ema6, 'ema20': s.ema20,
                'vwap': s.vwap, 'sma30_65m': s.sma30_65m, 'macd': s.macd, 'signal': s.signal,
                'hist': s.hist, 'bar_t': s.bar_t,
            } for s in sigs
        ],
    }
    (RESULTS / f"{symbol.replace(':','_')}.json").write_text(json.dumps(out)+'\n')
    print(json.dumps({'symbol': symbol, 'ok': True, 'bars': len(bars), 'pass': pass_trend, 'price': price, 'sma30_65m': sma, 'signals': len(sigs), 'reason': reason}))

if __name__ == '__main__':
    main()
