"""The forecast for one day: inputs -> poll averages -> fundamentals -> ratings -> blend -> correlated simulation."""
from __future__ import annotations
import json, math, logging
from pathlib import Path
import numpy as np, pandas as pd
from . import config as C
from . import calibrate as CAL
from . import fec as F_
from .pollavg import average, estimate_house_effects, norm_pollster
from .parse_wiki import parse_house_overview, parse_state_pages, parse_house_ratings, parse_senate_ratings, nz

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ settings
def settings(overrides=None):
    """Model settings, with calibrated values taken from data/calibration when present."""
    cfg = dict(C.MODEL)
    es = CAL.load('error_structure')
    if es:
        cfg.update(nat_sd=es['national'], region_sd=es['region'], state_sd=es['state'], sigma_floor=es['floor'], sigma_indiv=es['indiv'])
    cfg.update(overrides or {})
    if isinstance(cfg.get('nat_bias'), str):
        h = CAL.load('poll_miss_history') or {}
        cfg['nat_bias'] = float(h.get('mean_all' if cfg['nat_bias'] == 'history_all' else 'mean_midterm', 0.0))
    return cfg

# ------------------------------------------------------------------ inputs
def load_inputs(day: Path):
    w = day / 'wikipedia'
    districts = parse_house_overview(w / 'house_overview.txt')
    house_polls, _, _ = parse_state_pages(w / 'house_states', districts)
    sen = json.loads((day / 'pollcheck' / 'senate.json').read_text())
    races = [json.loads((day / 'pollcheck' / 'races' / f"{r['id']}.json").read_text())['race'] for r in sen['races']]
    return dict(day=day.name, districts=districts, house_polls=house_polls,
                house_ratings=parse_house_ratings(w / 'house_ratings.txt'), senate_ratings=parse_senate_ratings(w / 'senate_overview.txt'),
                senate=sen, senate_races=races, generic=json.loads((day / 'pollcheck' / 'generic_ballot.json').read_text()),
                fec26=F_.load(day / 'fec' / 'webl26.txt'))

def senate_sides(R):
    """Republican nominee and main challenger (Democrat, or the leading independent)."""
    pc = R['poll_candidates'] or []
    avg = R.get('average') or {}
    rep = next((c for c in pc if c['party'] == 'REP'), None) or next((c for c in R['candidates'] if c['party'] == 'REP'), None)
    chall = sorted([c for c in pc if c['party'] != 'REP'], key=lambda c: -(avg.get(c['name']) or 0))
    if not chall:
        chall = [c for c in R['candidates'] if c['party'] == 'DEM'] or [c for c in R['candidates'] if c['party'] != 'REP']
    return rep, (chall[0] if chall else None)

def house_sides(d):
    dc = [c for c in d['candidates'] if c['party'] == 'D']
    rc = [c for c in d['candidates'] if c['party'] == 'R']
    if not rc:  # an independent who caucuses with Republicans (e.g. CA-6 in 2026)
        rc = [c for c in d['candidates'] if c['party'] == 'I' and 'republican' in (c.get('party_label') or '').lower()]
        if d['id'] == 'CA-6': rc = [c for c in d['candidates'] if c['name'] == 'Kevin Kiley']
    return dc, rc

def collect_polls(inp, asof, cfg):
    rows = []
    for p in inp['generic']['polls']:
        if p.get('excluded'): continue
        res = p['results']
        if res.get('dem') is None or res.get('rep') is None: continue
        rows.append(dict(race='US', pollster=p['pollster'], end=p['date'], n=p['sample'], pop=p['population'], partisan=p['partisan'], margin=res['dem'] - res['rep']))
    for R in inp['senate_races']:
        rep, ch = senate_sides(R)
        for p in R.get('polls', []):
            ex = p.get('excluded') or ''
            if ex and not ex.startswith('taken before the primary') and not ex.startswith('first choices'): continue
            res = p['results']
            if not rep or not ch or res.get(rep['name']) is None or res.get(ch['name']) is None: continue
            rows.append(dict(race=R['id'], pollster=p['pollster'], end=p['date'], n=p['sample'], pop=p['population'], partisan=p['partisan'], margin=res[ch['name']] - res[rep['name']]))
    byid = {d['id']: d for d in inp['districts']}
    for p in inp['house_polls']:
        dc, rc = house_sides(byid[p['district']])
        if not dc or not rc or p['end'] is None: continue
        dv, rv = p['results'].get(dc[0]['name']), p['results'].get(rc[0]['name'])
        if dv is None or rv is None: continue
        rows.append(dict(race='H:' + p['district'], pollster=p['pollster'], end=p['end'], n=p['n'], pop=p['pop'], partisan=p['partisan'], margin=dv - rv))
    P = pd.DataFrame(rows)
    P['end'] = pd.to_datetime(P['end'])
    P = P[(P['end'] <= asof) & ((asof - P['end']).dt.days <= cfg['max_poll_age_days'])].copy()
    P['pkey'] = P.pollster.map(norm_pollster)
    P['partisan'] = P['partisan'].where(P['partisan'].isin(['D', 'R']), None)
    P['margin_raw'] = P['margin']
    s = cfg['partisan_shift']
    P['margin'] = P['margin'] - np.where(P.partisan == 'D', s, 0) + np.where(P.partisan == 'R', s, 0)
    return P.reset_index(drop=True)

def poll_model(P, asof, cfg):
    avg_cfg = dict(partisan_shift=0.0, partisan_w=cfg['partisan_weight'])
    house = estimate_house_effects(P, {r: asof for r in P.race.unique()}, k=cfg['house_effect_k'], cap=cfg['house_effect_cap'], iters=2, cfg=avg_cfg)
    npart = P[P.partisan.isna()].pkey.map(lambda k: house.get(k)).dropna()
    center = float(npart.mean()) if len(npart) else 0.0      # nonpartisan pollsters average zero lean
    house = {k: v - center for k, v in house.items()}
    gen, gen_neff, _ = average(P[P.race == 'US'], asof, half_life=cfg['gen_half_life'], house=house, cfg=avg_cfg)
    def summary(race):
        g = P[P.race == race]
        if not len(g): return None
        m, neff, _ = average(g, asof, half_life=cfg['half_life'], house=house, cfg=avg_cfg)
        return dict(avg=m, neff=neff, n=len(g), sd=math.sqrt(cfg['sigma_floor'] ** 2 + cfg['sigma_indiv'] ** 2 / max(neff, 1e-6)),
                    last=g['end'].max().date().isoformat())
    return house, center, gen, gen_neff, summary

# ------------------------------------------------------------------ House fundamentals for 2026
class HouseFundamentals:
    def __init__(self, inp, cfg):
        f = CAL.load('fundamentals')
        if f is None: raise RuntimeError('run `python -m forecast.pipeline calibrate` first')
        self.coef = f['coef']; self.natc = cfg['natc']; self.fec = inp['fec26']
        # incumbents' 2024 personal vote, re-measured against the 2026 PVI where the lines did not change
        Fd = pd.read_csv(C.CALIB / 'house_features.csv')
        d26 = {d['id']: d for d in inp['districts']}
        f24 = Fd[(Fd.year == 2024) & ~Fd.id.str.split('-').str[0].isin(C.REDISTRICTED_2026) & Fd.id.isin(d26)].copy()
        f24['pvi26'] = f24.id.map(lambda i: d26[i]['pvi'])
        X = np.c_[np.ones(len(f24)), 2 * f24.pvi26, f24.inc]; b, *_ = np.linalg.lstsq(X, f24.margin, rcond=None)
        f24['resid26'] = f24.margin - X @ b
        self.f24 = f24.set_index('id')

    def money(self, did, dname, rname):
        out = {}
        for party, name in (('D', dname), ('R', rname)):
            d = self.fec[(self.fec.did == did) & (self.fec.p == party) & (self.fec.office == 'H')]
            if not name or not len(d): out[party] = (0.0, bool(name)); continue
            last = nz(name).replace(' jr.', '').replace(' jr', '').replace(' iii', '').replace(' ii', '').split()[-1]
            m = d[d['last'] == last]
            if not len(m): m = d[d['last'].str.contains(last, regex=False)]
            if len(m): out[party] = (float(m.sort_values('receipts', ascending=False).iloc[0].raised), True)
            else: out[party] = (float(d.sort_values('receipts', ascending=False).iloc[0].raised), False)
        md, mr = out['D'], out['R']
        return float(np.clip(np.log1p(max(md[0], 0)) - np.log1p(max(mr[0], 0)), -6, 6)), md, mr

    def personal_vote(self, did, inc, inc_name):
        if inc == 0 or did.split('-')[0] in C.REDISTRICTED_2026 or did not in self.f24.index: return 0.0
        p = self.f24.loc[did]
        if p.inc != inc or not isinstance(p.inc_name, str) or not inc_name: return 0.0
        if nz(p.inc_name).split()[-1] != nz(inc_name).split()[-1]: return 0.0
        return float(p.resid26)

    def predict(self, pvi, inc, money, pv, gen):
        s = self.coef['slope']
        return self.coef['c0'] + self.natc * gen + s[0] * 2 * pvi + s[1] * inc + s[2] * money + s[3] * pv

def blend(parts):
    parts = [(m, s) for m, s in parts if m is not None and s]
    w = np.array([1 / s ** 2 for _, s in parts]); mu = np.array([m for m, _ in parts])
    return float((w * mu).sum() / w.sum()), float(1 / math.sqrt(w.sum())), [float(x) for x in w / w.sum()]

# ------------------------------------------------------------------ the forecast
def run(day: Path | None = None, overrides=None, inputs=None):
    from .fetch import latest_dir
    day = Path(day) if day else latest_dir()
    cfg = settings(overrides)
    inp = inputs or load_inputs(day)
    asof = pd.Timestamp(inp['day'])
    P = collect_polls(inp, asof, cfg)
    house, center, gen, gen_neff, poll_summary = poll_model(P, asof, cfg)
    HF = HouseFundamentals(inp, cfg)
    coef = HF.coef
    sen_meta = inp['senate']['meta']

    def rating_part(vals):
        if not cfg['use_ratings'] or not vals: return None
        m = float(np.mean(vals)); return (m, cfg['sigma_rating'] if abs(m) < 17 else cfg['sigma_rating_safe'])

    races = []
    for R in inp['senate_races']:
        key = R['state'] + (' special' if R['special'] else '')
        rat = inp['senate_ratings'].get(key, {})
        pvi = rat.get('pvi')
        if pvi is None:
            pvi = (R['pres_2024_margin'] - sen_meta['national_2024_pres_margin']) / 2 if R['pres_2024_margin'] is not None else 0
        rep, ch = senate_sides(R)
        ch_party = {'DEM': 'D', 'IND': 'I', 'REP': 'R', 'LIB': 'L'}.get(ch['party'], 'I') if ch else None
        inc = 0.0
        names = {nz(c['name']) for c in (R['poll_candidates'] or R['candidates'])}
        if R['incumbent'] and any(nz(R['incumbent']).split()[-1] == n.split()[-1] for n in names):
            inc = 1.0 if R['incumbent_party'] == 'DEM' else -1.0
            if 'appointee' in (R.get('status') or '').lower() or R['special']: inc *= 0.5
        three_way = ch_party == 'I' and any(c['party'] == 'DEM' for c in (R['poll_candidates'] or []))
        f_sd = cfg['sigma_fund_three_way'] if three_way else cfg['sigma_fund_senate'] if ch_party == 'D' else cfg['sigma_fund_indep']
        f_m = coef['c0'] + coef['slope'][0] * 2 * pvi + cfg['sen_inc'] * inc + cfg['natc'] * gen
        ps = poll_summary(R['id']); rv = rat.get('ratings') or []
        parts = [(f_m, f_sd)] + ([(ps['avg'], ps['sd'])] if ps else []) + ([rating_part(rv)] if rating_part(rv) else [])
        mu, sd, wts = blend(parts)
        races.append(dict(id=R['id'], chamber='Senate', st=R['state_abbr'], state=R['state'], label=('Senate (special)' if R['special'] else 'Senate'),
                          rep=rep['name'] if rep else None, ch=ch['name'] if ch else None, ch_party=ch_party,
                          incumbent=R['incumbent'], incumbent_party=R['incumbent_party'][0] if R['incumbent_party'] else None,
                          inc_running=inc, pvi=pvi, fund=f_m, fund_sd=f_sd, poll=ps, ratings=rv, rating_avg=float(np.mean(rv)) if rv else None,
                          mean=mu, sd=sd, weights=wts, has_poll=bool(ps), has_rating=bool(rating_part(rv)), fixed=None,
                          all_cands=[(c['name'], c['party']) for c in R['candidates']], source=R['source']['url']))

    for d in inp['districts']:
        did = d['id']; dc, rc = house_sides(d)
        fixed = 'R' if (not dc and rc) else 'D' if (dc and not rc) else None
        ri = d['running_incumbent']
        inc = (1.0 if ri['party'] == 'D' else -1.0) if ri else 0.0
        if did == 'CA-6' and ri: inc = -1.0
        money, md, mr = HF.money(did, dc[0]['name'] if dc else None, rc[0]['name'] if rc else None)
        pv = HF.personal_vote(did, inc, ri['name'] if ri else None)
        f_m = HF.predict(d['pvi'], inc, money, pv, gen)
        ps = poll_summary('H:' + did); rv = inp['house_ratings'].get(did, [])
        parts = [(f_m, cfg['sigma_fund_house'])] + ([(ps['avg'], ps['sd'])] if ps else []) + ([rating_part(rv)] if rating_part(rv) else [])
        mu, sd, wts = blend(parts)
        races.append(dict(id=did, chamber='House', st=d['st'], state=d['state'], label=f"District {d['district']}" if d['district'] != 'AL' else 'At-large',
                          rep=rc[0]['name'] if rc else None, ch=dc[0]['name'] if dc else None, ch_party='D',
                          incumbent=', '.join(i['name'] for i in d['incumbents']) or None, incumbent_party='/'.join(i['party'] for i in d['incumbents']) or None,
                          inc_running=inc, pvi=d['pvi'], fund=f_m, fund_sd=cfg['sigma_fund_house'], poll=ps, ratings=rv,
                          rating_avg=float(np.mean(rv)) if rv else None, mean=mu, sd=sd, weights=wts, has_poll=bool(ps), has_rating=bool(rating_part(rv)),
                          fixed=fixed, all_cands=[(c['name'], c['party']) for c in d['candidates']], rep_party=('I' if did == 'CA-6' else 'R'),
                          d_raised=md[0] if md[1] else None, r_raised=mr[0] if mr[1] else None, money=money, personal_vote=pv))
    summary = simulate(races, cfg, inp['senate']['composition'])
    summary['composition'] = inp['senate']['composition']
    summary.update(generic=dict(avg=gen, neff=gen_neff, n=int((P.race == 'US').sum())), as_of=inp['day'], cfg=cfg, coef=coef,
                   n_polls=int(len(P)), n_polls_senate=int(P.race.str.startswith('senate').sum()), n_polls_house=int(P.race.str.startswith('H:').sum()),
                   house_effect_center=center)
    return dict(summary=summary, races=races, house_effects=house, polls=P)

def simulate(races, cfg, composition):
    rng = np.random.default_rng(cfg['seed']); N = cfg['nsims']; df = cfg['t_df']; ts = math.sqrt(df / (df - 2))
    nat = cfg['nat_sd'] * rng.standard_t(df, N) / ts - cfg.get('nat_bias', 0.0)   # nat_bias > 0: polls assumed to overstate Democrats
    if cfg.get('nat_fixed') is not None:
        nat = np.full(N, -float(cfg['nat_fixed']))                                 # scenario: polls miss by exactly this much
    regs = {r: cfg['region_sd'] * rng.standard_normal(N) for r in sorted(set(C.REGION.values()))}
    sts = {s: cfg['state_sd'] * rng.standard_normal(N) for s in sorted(C.REGION)}
    sen_R = np.full(N, composition['not_up']['R']); sen_D = np.full(N, composition['not_up']['D'] + composition['not_up']['I'])
    sen_I = np.zeros(N); house_D = np.zeros(N)
    for r in races:
        if r['fixed']:
            win = np.full(N, r['fixed'] == 'D'); r['p_ch'] = float(r['fixed'] == 'D'); r['p10'] = r['p90'] = None
        else:
            draw = r['mean'] + nat + regs[C.REGION[r['st']]] + sts[r['st']] + r['sd'] * rng.standard_t(df, N) / ts
            win = draw > 0; r['p_ch'] = float(win.mean())
            r['p10'], r['p90'] = float(np.percentile(draw, 10)), float(np.percentile(draw, 90))
        if r['chamber'] == 'Senate':
            if r['ch_party'] == 'D': sen_D += win
            else: sen_I += win
            sen_R += ~win
        else:
            house_D += win
    hist = lambda x: {int(k): float(v) for k, v in pd.Series(x).value_counts(normalize=True).sort_index().items()}
    return dict(
        senate=dict(p_R_control=float((sen_R >= 50).mean()), p_D_control=float((sen_D >= 51).mean()), p_indep_decide=float(((sen_R < 50) & (sen_D < 51)).mean()),
                    R_median=float(np.median(sen_R)), D_median=float(np.median(sen_D)), I_mean=float(sen_I.mean()),
                    D_p10=float(np.percentile(sen_D, 10)), D_p90=float(np.percentile(sen_D, 90)), D_hist=hist(sen_D)),
        house=dict(p_D_control=float((house_D >= 218).mean()), D_median=float(np.median(house_D)),
                   D_p10=float(np.percentile(house_D, 10)), D_p90=float(np.percentile(house_D, 90)), D_hist=hist(house_D)))

def scenarios(F, shifts=(-3, -2, -1, 0, 1, 2, 3, 4, 5, 6), nsims=20000):
    """Chamber control if every poll-based estimate is off by exactly `shift` margin points (positive = Democrats overstated).
    Regional, state and race-level errors are still simulated on top. Also: how likely a miss at least that large is under the model."""
    from scipy import stats
    cfg = dict(F['summary']['cfg']); comp = F['summary'].get('composition')
    races = [dict(r) for r in F['races']]
    df = cfg['t_df']; scale = cfg['nat_sd'] / math.sqrt(df / (df - 2))
    rows = []
    for s in shifts:
        S = simulate(races, dict(cfg, nat_fixed=float(s), nsims=nsims), comp)
        bias = float(cfg.get('nat_bias') or 0.0)                              # expected miss (polls overstate Democrats by this much)
        p_tail = None if s == 0 else float(stats.t.sf((s - bias) / scale, df) if s > 0 else stats.t.cdf((s - bias) / scale, df))
        rows.append(dict(shift=s, label=('No miss' if s == 0 else f"Polls overstate {'Democrats' if s > 0 else 'Republicans'} by {abs(s)}"),
                         senate_dem_control_pct=round(100 * S['senate']['p_D_control'], 1), senate_gop_control_pct=round(100 * S['senate']['p_R_control'], 1),
                         senate_dem_median=int(S['senate']['D_median']), house_dem_control_pct=round(100 * S['house']['p_D_control'], 1),
                         house_dem_median=int(S['house']['D_median']), chance_miss_this_big_pct=round(100 * p_tail, 1) if p_tail is not None else None))
    return rows

SENSITIVITY = {
    'Published model (polls lean D by the midterm average)': {},
    'No polling lean assumed': {'nat_bias': 0.0},
    'Without expert ratings': {'use_ratings': False},
    'Full generic-ballot swing to every seat': {'natc': 1.0},
    'Larger national polling error (4.5 pts)': {'nat_sd': 4.5},
    'Lean = 2010–2024 average of all cycles': {'nat_bias': 'history_all'},
    'Slower poll decay (21-day half-life)': {'half_life': 21.0},
    'Less trust in fundamentals': {'sigma_fund_house': 8.0, 'sigma_fund_senate': 10.0},
}
def sensitivity(day=None, inputs=None):
    rows = []
    for name, ov in SENSITIVITY.items():
        s = run(day, ov, inputs)['summary']
        rows.append(dict(variant=name, senate_dem_control_pct=round(100 * s['senate']['p_D_control'], 1),
                         house_dem_control_pct=round(100 * s['house']['p_D_control'], 1), house_dem_median=int(s['house']['D_median'])))
    return rows
