#!/usr/bin/env python3
"""Run full scan over cached OHLCV (RTH: yfinance via refresh_yfinance.py; no TV browser)."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import json

BASE = Path(__import__("os").environ.get("TV_SCANNER_HOME") or Path(__file__).resolve().parent)  # locale o box
sc = SourceFileLoader('scanner', str(BASE / 'scanner.py')).load_module()

def main():
    uni = sc.build_scan_universes()
    symbols = list(uni["fetch"])
    # Only scan symbols that have cache (fetched)
    cached = []
    missing = []
    for s in symbols:
        p = BASE / 'cache' / f"{s.replace(':', '_')}.json"
        if p.exists():
            cached.append(s)
        else:
            missing.append(s)
    summary = sc.scan_all(cached, universes=uni)
    summary['symbols_requested'] = len(symbols)
    summary['symbols_cached'] = len(cached)
    summary['symbols_missing_cache'] = missing
    summary['universes'] = uni['counts']
    (BASE / 'last_scan_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({
        'universes': uni['counts'],
        'symbols_requested': len(symbols),
        'symbols_cached': len(cached),
        'missing_count': len(missing),
        'symbols_scanned': summary.get('symbols_scanned'),
        'new_signals': summary.get('new_signals'),
        'discord': summary.get('discord'),
    }, indent=2))

if __name__ == '__main__':
    main()
