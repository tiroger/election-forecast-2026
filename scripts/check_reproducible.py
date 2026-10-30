"""Re-run the forecast on a stored snapshot and confirm it reproduces the stored outputs exactly.
Usage: python scripts/check_reproducible.py [YYYY-MM-DD]   (default: latest day in data/history)"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forecast import config as C, model as M, export as X

days = sorted(p.name for p in C.HISTORY.iterdir() if p.is_dir())
day = sys.argv[1] if len(sys.argv) > 1 else days[-1]
F = M.run(C.RAW / day)
new = {r['id']: r for r in X._records(X.race_rows(F))}
old = {r['id']: r for r in json.loads((C.HISTORY / day / 'races.json').read_text())}
diff = [(k, old[k]['dem_win_pct'], new[k]['dem_win_pct']) for k in old if old[k]['dem_win_pct'] != new.get(k, {}).get('dem_win_pct')]
summ = json.loads((C.HISTORY / day / 'chamber_summary.json').read_text())
s = F['summary']
same_summary = (round(100 * s['senate']['p_D_control'], 1) == summ[0]['dem_control_pct'] and round(100 * s['house']['p_D_control'], 1) == summ[1]['dem_control_pct'])
print(f'{day}: {len(old)} races, {len(diff)} differ; chamber odds identical: {same_summary}')
sys.exit(0 if (not diff and same_summary) else 1)
