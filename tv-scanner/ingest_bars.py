#!/usr/bin/env python3
"""Ingest bars JSON from stdin or --file into cache and optionally scan one symbol."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from importlib.machinery import SourceFileLoader

BASE = Path('/workspace/tv-scanner')
CACHE = BASE / 'cache'
sc = SourceFileLoader('scanner', str(BASE / 'scanner.py')).load_module()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', required=True)
    ap.add_argument('--file', help='Read MCP JSON from file instead of stdin')
    ap.add_argument('--scan', action='store_true')
    args = ap.parse_args()
    raw = Path(args.file).read_text() if args.file else sys.stdin.read()
    data = json.loads(raw)
    if isinstance(data, list):
        bars = data
        payload = {'symbol': args.symbol, 'bars': bars, 'count': len(bars)}
    else:
        bars = data.get('bars') or data.get('data') or []
        payload = {
            'symbol': data.get('symbol', args.symbol),
            'bars': bars,
            'count': len(bars),
            'success': data.get('success', True),
            'notice': data.get('notice'),
        }
        if data.get('success') is False or data.get('error'):
            err_path = CACHE / f"{args.symbol.replace(':','_')}.error.json"
            err_path.write_text(json.dumps(data, indent=2) + '\n')
            print(json.dumps({'symbol': args.symbol, 'ok': False, 'error': data.get('error', 'failed')}))
            return
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{args.symbol.replace(':','_')}.json"
    out.write_text(json.dumps(payload) + '\n')
    result = {'symbol': args.symbol, 'ok': True, 'bars': len(bars), 'path': str(out)}
    if args.scan:
        sigs, reason = sc.scan_symbol(args.symbol, bars=bars)
        result['reason'] = reason
        result['signals'] = [
            {
                'trigger': s.trigger,
                'price': s.price,
                'ema6': s.ema6,
                'ema20': s.ema20,
                'vwap': s.vwap,
                'sma30_65m': s.sma30_65m,
                'macd': s.macd,
                'signal': s.signal,
                'hist': s.hist,
                'bar_t': s.bar_t,
            }
            for s in sigs
        ]
    print(json.dumps(result))

if __name__ == '__main__':
    main()
