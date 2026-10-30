"""Command line:  python -m forecast.pipeline <step> [--date YYYY-MM-DD]

  fetch       download today's polls, ratings, candidate lists and FEC filings (plus historical data once)
  calibrate   re-run the backtests that set the model's error sizes and fundamentals coefficients
  forecast    run the forecast on the latest snapshot and write site/data/*.json
  site        rebuild site/index.html from page/index.html
  daily       fetch + forecast + site            (what the scheduler runs)
  all         fetch + calibrate + forecast + site (first run, or after changing methods)
"""
from __future__ import annotations
import argparse, json, logging, os, sys, time
from . import config as C

log = logging.getLogger('forecast')

def step_fetch(args):
    from .fetch import fetch_daily
    from datetime import date
    info = fetch_daily(date.fromisoformat(args.date) if args.date else None, force=args.force)
    log.info('fetched %s', info)

def step_calibrate(args):
    from .calibrate import run_all
    run_all(include_hierarchical=not args.quick)

def step_forecast(args):
    from .fetch import latest_dir
    from .model import run, load_inputs, sensitivity, scenarios
    from .export import write_site
    day = C.RAW / args.date if args.date else latest_dir()
    inp = load_inputs(day)
    validate(inp)
    t = time.time(); F = run(day, inputs=inp)
    sens = sensitivity(day, inputs=inp) if not args.quick else []
    counts = write_site(F, sens, scenario_rows=scenarios(F))
    s = F['summary']
    log.info('forecast %s in %.0fs: Senate D %.1f%% | House D %.1f%% (median %d) | generic D%+.1f | files %s', s['as_of'], time.time() - t,
             100 * s['senate']['p_D_control'], 100 * s['house']['p_D_control'], s['house']['D_median'], s['generic']['avg'], counts)

def validate(inp):
    """Refuse to publish if a source changed format and parsing silently broke."""
    import pandas as pd
    problems = []
    if len(inp['districts']) != 435: problems.append(f"{len(inp['districts'])} House districts parsed (expected 435)")
    if sum(1 for d in inp['districts'] if d['pvi'] is None) > 5: problems.append('PVI missing for many districts')
    if sum(1 for d in inp['districts'] if not d['candidates']) > 5: problems.append('nominees missing for many districts')
    if len(inp['senate_races']) < 33: problems.append(f"only {len(inp['senate_races'])} Senate races")
    if len(inp['house_ratings']) < 60: problems.append(f"only {len(inp['house_ratings'])} House districts with ratings")
    if len(inp['senate_ratings']) < 30: problems.append(f"only {len(inp['senate_ratings'])} Senate races with ratings")
    h = C.HISTORY / 'forecast_history.csv'
    if h.exists():
        prev = pd.read_csv(h)
        prev = prev[prev.date < inp['day']]
        n_now = sum(len(r.get('polls', [])) for r in inp['senate_races']) + len(inp['generic']['polls']) + len(inp['house_polls'])
        if len(prev) and n_now < 0.5 * prev.polls.iloc[-1]: problems.append(f'poll count fell sharply ({n_now} vs {prev.polls.iloc[-1]} used last run)')
    if problems:
        raise SystemExit('Not publishing, inputs look wrong: ' + '; '.join(problems))
    log.info('inputs look sane: %d districts, %d Senate races, %d district polls', len(inp['districts']), len(inp['senate_races']), len(inp['house_polls']))

def step_site(args):
    from .site import build, build_inline
    log.info('site written to %s and %s', build(), build_inline())

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('step', choices=['fetch', 'calibrate', 'forecast', 'site', 'daily', 'all'])
    ap.add_argument('--date', help='use (or fetch into) the snapshot for this date')
    ap.add_argument('--force', action='store_true', help='re-download pages already saved today')
    ap.add_argument('--quick', action='store_true', help='skip the slow parts (sensitivity runs, joint-model backtest)')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.date: os.environ['FORECAST_ASOF'] = args.date
    C.ensure_dirs()
    plan = {'fetch': [step_fetch], 'calibrate': [step_calibrate], 'forecast': [step_forecast], 'site': [step_site],
            'daily': [step_fetch, step_forecast, step_site], 'all': [step_fetch, step_calibrate, step_forecast, step_site]}[args.step]
    for f in plan: f(args)

if __name__ == '__main__':
    main()
