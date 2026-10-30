"""Write the page's data files (site/data/*.json) from a forecast run plus the calibration results, and keep the daily history."""
from __future__ import annotations
import json, re, shutil
from pathlib import Path
import numpy as np, pandas as pd
from . import config as C
from . import calibrate as CAL

def mlabel(m):
    if m is None or (isinstance(m, float) and np.isnan(m)): return None
    if abs(m) < 0.05: return 'Even'
    return ('D' if m > 0 else 'R') + '+' + f'{abs(m):.1f}'

def pvilabel(p):
    if p == 0: return 'EVEN'
    return ('D' if p > 0 else 'R') + '+' + (f'{abs(p):.0f}' if float(p).is_integer() else f'{abs(p):.1f}')

def money_label(x):
    if x is None: return None
    x = max(float(x), 0.0)
    return f'${x/1e6:.1f}M' if x >= 1e6 else f'${x/1e3:.0f}K'

def category(p_ch, side):
    lead, p = (side, p_ch) if p_ch >= 0.5 else ('R', 1 - p_ch)
    if p >= 0.95: return f'Safe {lead}', lead
    if p >= 0.80: return f'Likely {lead}', lead
    if p >= 0.60: return f'Lean {lead}', lead
    return 'Toss-up', lead

PN = {'DEM': 'D', 'REP': 'R', 'IND': 'I', 'LIB': 'L', 'GRE': 'G'}

def race_rows(F):
    rows = []
    lean = float(F['summary']['cfg'].get('nat_bias') or 0.0)   # projections include the assumed polling lean
    for r in F['races']:
        side = r['ch_party'] or 'D'; p_ch = r['p_ch']
        cat, lead = category(p_ch, side)
        inc_party = r.get('incumbent_party') or ''
        held_by = 'I' if r['id'] == 'CA-6' else (inc_party.split('/')[0] if inc_party else None)
        if r['chamber'] == 'House' and '/' in inc_party: flip = None          # two incumbents drawn together
        elif held_by:
            winner = lead if cat != 'Toss-up' else None
            flip = 'Yes' if winner and winner != held_by and not (held_by == 'I' and winner == 'R') else 'No'
        else: flip = None
        poll = r['poll'] or {}; w = r['weights']; fixed = r['fixed']
        wp = (w[1] if r['has_poll'] else 0.0) if not fixed else None
        wr = (w[-1] if r['has_rating'] else 0.0) if not fixed else None
        seat_no = r['label'].replace('District ', '') if r['chamber'] == 'House' else r['label']
        rows.append(dict(
            id=r['id'], chamber=r['chamber'], state=r['state'], st=r['st'], seat=r['label'],
            sort_key=(0 if r['chamber'] == 'Senate' else 1) * 1000 + (int(seat_no) if seat_no.isdigit() else 0),
            dem_side=f"{r['ch']} ({side})" if r['ch'] else None,
            gop_side=f"{r['rep']} ({'I' if r['id'] == 'CA-6' else 'R'})" if r['rep'] else None,
            candidates='; '.join(f'{n} ({PN.get(p, p)})' for n, p in r['all_cands']), incumbent=r.get('incumbent'), held_by=held_by,
            pvi=pvilabel(r['pvi']) if r['pvi'] is not None else None,
            poll_avg=round(poll['avg'], 1) if poll else None, poll_avg_label=mlabel(poll['avg']) if poll else None,
            n_polls=int(poll['n']) if poll else 0, last_poll=poll.get('last') if poll else None,
            fundamentals=mlabel(r['fund']) if not fixed else None,
            ratings_avg=mlabel(r['rating_avg']) if (r['rating_avg'] is not None and not fixed) else None, n_ratings=len(r['ratings']),
            projected_margin=round(r['mean'] - lean, 1) if not fixed else None,
            projection=mlabel(r['mean'] - lean) if not fixed else 'Uncontested by ' + ('Republicans' if fixed == 'D' else 'Democrats'),
            range_80=f"{mlabel(r['p10'])} to {mlabel(r['p90'])}" if r.get('p10') is not None else None,
            dem_win_pct=round(100 * p_ch, 1), gop_win_pct=round(100 * (1 - p_ch), 1), rating=cat, leader=lead, flip=flip,
            weight_polls_pct=round(100 * wp) if wp is not None else None, weight_fund_pct=round(100 * w[0]) if not fixed else None,
            weight_ratings_pct=round(100 * wr) if wr is not None else None, closeness=round(abs(p_ch - 0.5), 4),
            dem_raised=money_label(r.get('d_raised')), gop_raised=money_label(r.get('r_raised')),
            personal_vote=mlabel(r['personal_vote']) if r.get('personal_vote') else None))
    return pd.DataFrame(rows).sort_values(['state', 'sort_key'])

def poll_rows(F):
    P = F['polls'].copy(); he = F['house_effects']
    P['race_id'] = P.race.str.replace('^H:', '', regex=True)
    P = P.sort_values(['race_id', 'end'], ascending=[True, False])
    P['poll_id'] = [f'p{i}' for i in range(len(P))]
    P['end_date'] = P.end.dt.strftime('%Y-%m-%d')
    P['margin_label'] = P.margin_raw.map(mlabel)
    P['sponsor'] = P.partisan.fillna('').map({'D': 'Dem-aligned', 'R': 'GOP-aligned', '': 'Nonpartisan'})
    P['pollster_lean'] = P.pkey.map(lambda k: mlabel(he[k]) if k in he else None)
    P['sample'] = P.n.map(lambda x: int(x) if pd.notna(x) else None)
    P['population'] = P['pop']
    return P[['poll_id', 'race_id', 'pollster', 'end_date', 'sample', 'population', 'sponsor', 'margin_label', 'pollster_lean']]

def summary_rows(F):
    s = F['summary']; sen, hou = s['senate'], s['house']
    return [dict(chamber='Senate', dem_control_pct=round(100 * sen['p_D_control'], 1), gop_control_pct=round(100 * sen['p_R_control'], 1),
                 independents_decide_pct=round(100 * sen['p_indep_decide'], 1), dem_median=int(sen['D_median']), gop_median=int(sen['R_median']),
                 dem_p10=int(sen['D_p10']), dem_p90=int(sen['D_p90']), seats_for_control=51, races=sum(1 for r in F['races'] if r['chamber'] == 'Senate'), as_of=s['as_of']),
            dict(chamber='House', dem_control_pct=round(100 * hou['p_D_control'], 1), gop_control_pct=round(100 * (1 - hou['p_D_control']), 1),
                 independents_decide_pct=None, dem_median=int(hou['D_median']), gop_median=int(435 - hou['D_median']),
                 dem_p10=int(hou['D_p10']), dem_p90=int(hou['D_p90']), seats_for_control=218, races=435, as_of=s['as_of'])]

def backtest_rows():
    rows = []
    pa = CAL.load('poll_average_backtest'); hb = CAL.load('hierarchical_backtest'); fb = CAL.load('fundamentals'); hf = CAL.load('house_forecast_backtest')
    t1 = 'Poll averages, 2010–2022 (Senate, governor, House)'
    for r in pa['rows']: rows.append(dict(test=t1, method=r['method'], rmse=r['rmse']))
    if hb: rows.append(dict(test=t1, method='Full Bayesian joint model of all polls (rejected)', rmse=round(min(hb['ml']['rmse'], hb['best_fixed']['rmse']), 2)))
    t2 = f"House fundamentals, {fb['years'][0]}–{fb['years'][-1]}, competitive seats"
    for r in fb['rows']: rows.append(dict(test=t2, method=r['method'], rmse=r['rmse']))
    t3 = 'Every contested House race, 2018–2022'
    rows.append(dict(test=t3, method='Full forecast, old fundamentals', rmse=round(hf['old']['rmse'], 2)))
    rows.append(dict(test=t3, method='Full forecast, new fundamentals (used)', rmse=round(hf['new']['rmse'], 2)))
    return rows

def calibration_rows():
    hf = CAL.load('house_forecast_backtest')['new']
    return [dict(bin=f"{max(b['lo'], 0) * 100:.0f}–{b['hi'] * 100:.0f}%", predicted_dem_win_pct=round(100 * b['predicted'], 1),
                 observed_dem_win_pct=round(100 * b['observed'], 1), races=b['races']) for b in hf['bins']]

def error_rows():
    es = CAL.load('error_structure')
    lab = {'national': 'Nationwide (shared by every race)', 'region': 'Region (Northeast, Midwest, South, West)', 'state': 'State (shared by races in a state)',
           'floor': 'Race-level floor', 'indiv': 'One poll (shrinks with more polls)'}
    return [dict(component=v, sd_points=round(es[k], 1)) for k, v in lab.items()]

def _records(df):
    return df.astype(object).where(pd.notna(df), None).to_dict('records')

def update_history(F):
    """One row per forecast day; re-running a day replaces its row."""
    s = F['summary']; p = C.HISTORY / 'forecast_history.csv'
    row = dict(date=s['as_of'], senate_dem_control_pct=round(100 * s['senate']['p_D_control'], 1), senate_gop_control_pct=round(100 * s['senate']['p_R_control'], 1),
               house_dem_control_pct=round(100 * s['house']['p_D_control'], 1), senate_dem_median=int(s['senate']['D_median']),
               house_dem_median=int(s['house']['D_median']), generic_ballot=round(s['generic']['avg'], 1), polls=s['n_polls'])
    h = pd.read_csv(p) if p.exists() else pd.DataFrame(columns=list(row))
    h = pd.concat([h[h.date != row['date']], pd.DataFrame([row])]).sort_values('date')
    h.to_csv(p, index=False)
    return h

def miss_rows():
    h = CAL.load('poll_miss_history')
    return [dict(cycle=str(r['cycle']), dem_overstatement=r['dem_overstatement'], kind=r['kind'], source=r['source']) for r in h['rows']]

def write_site(F, sens_rows, out_dir: Path = None, scenario_rows=None):
    out = Path(out_dir or C.SITE_DATA); out.mkdir(parents=True, exist_ok=True)
    s = F['summary']
    hist = update_history(F)
    files = {
        'races': _records(race_rows(F)),
        'chamber_summary': summary_rows(F),
        'seat_distribution': [dict(chamber=ch, dem_seats=int(k), prob_pct=round(100 * v, 2)) for ch, key in [('Senate', 'senate'), ('House', 'house')]
                              for k, v in s[key]['D_hist'].items() if v >= 0.0005],
        'national': [dict(measure='Generic ballot average (Dem minus Rep)', value=round(s['generic']['avg'], 1), label=mlabel(s['generic']['avg']),
                          polls=s['generic']['n'], note='Weighted for recency, sample, pollster record; pollster lean removed'),
                     dict(measure='Assumed polling lean (polls overstate Democrats by)', value=round(float(s['cfg'].get('nat_bias') or 0), 1),
                          label=mlabel(-float(s['cfg'].get('nat_bias') or 0)), polls=None, note='Midterm average of past misses, 2010–2022')],
        'polls': _records(poll_rows(F)),
        'backtest': backtest_rows(), 'calibration': calibration_rows(), 'error_structure': error_rows(),
        'sensitivity': sens_rows, 'history': _records(hist),
        'scenarios': scenario_rows or [], 'poll_misses': miss_rows(),
    }
    for name, rows in files.items():
        (out / f'{name}.json').write_text(json.dumps(rows, ensure_ascii=False, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else str(o)))
    # keep a full copy of the day's outputs
    snap = C.HISTORY / s['as_of']; snap.mkdir(parents=True, exist_ok=True)
    for f in out.glob('*.json'): shutil.copy(f, snap / f.name)
    return {k: len(v) for k, v in files.items()}
