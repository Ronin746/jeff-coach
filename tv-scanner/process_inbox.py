#!/usr/bin/env python3
"""Process any MCP OHLCV JSON files dropped in mcp_inbox/ into cache + scan results."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
from importlib.machinery import SourceFileLoader

BASE = Path('/workspace/tv-scanner')
INBOX = BASE / 'mcp_inbox'
CACHE = BASE / 'cache'
RESULTS = BASE / 'results'
sc = SourceFileLoader('scanner', str(BASE / 'scanner.py')).load_module()

def process_file(path: Path):
    data = json.loads(path.read_text())
    symbol = data.get('symbol') or path.stem.replace('_', ':', 1)
    if data.get('success') is False or data.get('error'):
        out = {'symbol': symbol, 'ok': False, 'error': data.get('error', 'failed')}
        (RESULTS / f"{symbol.replace(':','_')}.json").write_text(json.dumps(out, indent=2)+'\n')
        return out
    bars = data.get('bars') or []
    # verify summary if present
    summary = data.get('summary') or {}
    if summary.get('count') and len(bars) != summary['count']:
        out = {'symbol': symbol, 'ok': False, 'error': f"count mismatch {len(bars)}!={summary['count']}"}
        (RESULTS / f"{symbol.replace(':','_')}.json").write_text(json.dumps(out, indent=2)+'\n')
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{symbol.replace(':','_')}.json").write_text(json.dumps({
        'symbol': symbol, 'bars': bars, 'count': len(bars), 'summary': summary,
        'source': 'user-TradingView:mcp-tv-get-ohlcv'
    })+'\n')
    sigs, reason = sc.scan_symbol(symbol, bars=bars)
    out = {
        'symbol': symbol,
        'ok': True,
        'bars': len(bars),
        'reason': reason,
        'signals': [
            {
                'trigger': s.trigger, 'price': s.price, 'ema6': s.ema6, 'ema20': s.ema20,
                'vwap': s.vwap, 'sma30_65m': s.sma30_65m, 'macd': s.macd, 'signal': s.signal,
                'hist': s.hist, 'bar_t': s.bar_t,
            } for s in sigs
        ],
    }
    (RESULTS / f"{symbol.replace(':','_')}.json").write_text(json.dumps(out, indent=2)+'\n')
    # move processed
    done = INBOX / 'done'
    done.mkdir(exist_ok=True)
    path.rename(done / path.name)
    return out

def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    files = sorted(INBOX.glob('*.json'))
    outs = []
    for f in files:
        try:
            outs.append(process_file(f))
        except Exception as e:
            outs.append({'file': str(f), 'ok': False, 'error': str(e)})
    print(json.dumps(outs, indent=2))

if __name__ == '__main__':
    main()
