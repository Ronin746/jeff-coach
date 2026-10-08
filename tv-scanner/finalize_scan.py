#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from importlib.machinery import SourceFileLoader

BASE = Path('/workspace/tv-scanner')
ET = ZoneInfo('America/New_York')
sc = SourceFileLoader('scanner', str(BASE / 'scanner.py')).load_module()

def main():
    symbols = sc.load_watchlist()
    state = sc.load_state()
    emitted = state.setdefault('emitted', {})
    results_dir = BASE / 'results'
    scanned = 0
    skipped = []
    errors = []
    new_signals = []
    missing = []

    for sym in symbols:
        rp = results_dir / f"{sym.replace(':','_')}.json"
        if not rp.exists():
            missing.append(sym)
            continue
        r = json.loads(rp.read_text())
        if not r.get('ok'):
            errors.append({'symbol': sym, 'error': r.get('error', 'unknown')})
            continue
        if r.get('reason'):
            skipped.append({'symbol': sym, 'reason': r['reason']})
            continue
        scanned += 1
        for s in r.get('signals') or []:
            # rebuild Signal-like for keying
            class S: pass
            sig = S()
            sig.symbol = sym
            sig.trigger = s['trigger']
            sig.bar_t = s['bar_t']
            sig.price = s['price']
            sig.ema6 = s['ema6']
            sig.ema20 = s['ema20']
            sig.vwap = s['vwap']
            sig.sma30_65m = s['sma30_65m']
            sig.macd = s['macd']
            sig.signal = s['signal']
            sig.hist = s['hist']
            key = sc.signal_key(sig)
            if key in emitted:
                continue
            emitted[key] = {'symbol': sym, 'trigger': s['trigger'], 'bar_t': s['bar_t'],
                            'price': s['price'], 'ts_emitted': int(datetime.now().timestamp())}
            new_signals.append(sig)

    if new_signals:
        sc.append_signals_md(new_signals)
    sc.save_state(state)

    summary = {
        'timestamp': datetime.now(tz=ET).isoformat(),
        'symbols_scanned': scanned,
        'symbols_skipped': skipped,
        'new_signals': [{'symbol': s.symbol, 'trigger': s.trigger, 'bar_t': s.bar_t, 'price': s.price} for s in new_signals],
        'errors': errors,
        'symbols_missing_results': missing,
        'symbols_requested': len(symbols),
        'note': 'EARLY disabled due to delayed data (delayed_streaming_900); CONFIRMED-only on last fully closed 5m',
    }
    (BASE / 'last_scan_summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
