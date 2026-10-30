"""Backtests on past elections. Each function writes data/calibration/<name>.json, which the forecast reads.

Run all with `python -m forecast.pipeline calibrate` (a few minutes; only needed when methods change, not daily).
"""
from __future__ import annotations
import json, logging
import numpy as np, pandas as pd
from scipy.optimize import minimize
from . import config as C
from .pollavg import average, estimate_house_effects, norm_pollster
from .parse_wiki import parse_house_history, nz
from . import fec as F_
from . import hier

log = logging.getLogger(__name__)
RMSE = lambda e: float(np.sqrt(np.mean(np.square(np.asarray(e, float)))))

def _save(name, obj):
    C.CALIB.mkdir(parents=True, exist_ok=True)
    (C.CALIB / f'{name}.json').write_text(json.dumps(obj, indent=1, default=float))
    return obj

def load(name):
    p = C.CALIB / f'{name}.json'
    return json.loads(p.read_text()) if p.exists() else None

# ------------------------------------------------------------------ 538 archive of final-three-week polls
def raw_polls(types=('Sen-G', 'Gov-G', 'House-G'), cycles=None):
    r = pd.read_csv(C.STATIC / '538' / 'raw_polls.csv', low_memory=False)
    r = r[(r.cand1_party == 'DEM') & (r.cand2_party == 'REP') & (r.cycle % 2 == 0) & r.type_simple.isin(types)].copy()
    if cycles: r = r[r.cycle.isin(cycles)]
    r['end'] = pd.to_datetime(r.polldate, format='mixed'); r['eday'] = pd.to_datetime(r.electiondate, format='mixed')
    r = r[r.end <= r.eday - pd.Timedelta(days=5)]          # forecast made five days out
    r['margin'] = r.margin_poll; r['pkey'] = r.pollster.map(norm_pollster); r['n'] = r.samplesize
    r['pop'] = None; r['partisan'] = None; r['race'] = r.race_id
    return r

def poll_average_backtest():
    """Compare averaging methods on 2010-2022 Senate, governor and House polls."""
    r = raw_polls(cycles=range(2010, 2023))
    asof = (r.groupby('race_id').eday.first() - pd.Timedelta(days=5)).to_dict()
    truth = r.groupby('race_id').margin_actual.first(); rtype = r.groupby('race_id').type_simple.first()
    variants = {'Simple mean of polls': None,
                'Weighted (recency, sample, pollster grade, per-pollster cap)': dict(grades=True, pollster_cap=True, house_effects=False),
                'Weighted + pollster lean removed (used)': dict(grades=True, pollster_cap=True, house_effects=True)}
    rows, keep = [], None
    for name, cfg in variants.items():
        out = []
        for cy, rc in r.groupby('cycle'):
            house = estimate_house_effects(rc, asof, cfg=cfg) if cfg and cfg.get('house_effects') else None
            for rid, g in rc.groupby('race_id'):
                if cfg is None: m, ne = g.margin.mean(), len(g)
                else: m, ne, _ = average(g, asof[rid], cfg=cfg, house=house)
                out.append((rid, cy, rtype[rid], m, ne, len(g), truth[rid]))
        df = pd.DataFrame(out, columns=['race', 'cycle', 'type', 'avg', 'neff', 'npolls', 'actual']); df['err'] = df.avg - df.actual
        rows.append(dict(method=name, rmse=round(RMSE(df.err), 2), **{t: round(RMSE(df[df.type == t].err), 2) for t in ['Sen-G', 'Gov-G', 'House-G']}))
        keep = df
    # flat shift toward Republicans, estimated leave-one-cycle-out
    e = pd.concat([keep[keep.cycle == c].err - keep[keep.cycle != c].err.mean() for c in keep.cycle.unique()])
    rows.append(dict(method='Same + flat shift to GOP, leave-one-cycle-out (rejected)', rmse=round(RMSE(e), 2)))
    loc = pd.read_csv(C.STATIC / '538' / 'raw_polls.csv', low_memory=False, usecols=['race_id', 'location']).groupby('race_id').location.first()
    keep['st'] = keep.race.map(loc).str[:2]
    keep.to_csv(C.CALIB / 'poll_average_errors.csv', index=False)
    return _save('poll_average_backtest', dict(rows=rows))

def hierarchical_backtest():
    """Full Bayesian joint model of all polls (hier.py) on the same races, for comparison."""
    r = raw_polls(cycles=range(2010, 2023)); r['pop'] = 'LV'; r['race'] = r.race_id.astype(str)
    truth = r.groupby('race').margin_actual.first()
    out = {}
    for label, fixed in [('ml', None), ('best_fixed', (3, 3, 0.1, 0.05, 2))]:
        errs, hyp = [], []
        for cy, rc in r.groupby('cycle'):
            asof = rc.eday.max() - pd.Timedelta(days=5)
            pm = {k: 0.0 for k in rc.race.unique()}; ps = {k: 25.0 for k in rc.race.unique()}
            f = hier.fit(rc.reset_index(drop=True), pm, ps, asof, nweeks=3, fixed=fixed, optimize=fixed is None)
            hyp.append(dict(cycle=int(cy), **{k: float(v) for k, v in f['hyper'].items()}))
            errs += [f['alpha'][i] - truth[race] for i, race in enumerate(f['races'])]
        out[label] = dict(rmse=RMSE(errs), hyper=hyp)
    return _save('hierarchical_backtest', out)

def error_structure():
    """Maximum-likelihood sizes of shared polling error: national, region, state, plus floor and per-poll noise."""
    df = pd.read_csv(C.CALIB / 'poll_average_errors.csv').dropna(subset=['st'])
    df['reg'] = df.st.map(C.REGION); df = df.dropna(subset=['reg'])
    blocks = []
    for c, g in df.groupby('cycle'):
        reg = np.asarray(g.reg, dtype=object); st = np.asarray(g.st, dtype=object)
        blocks.append((g.err.values, g.neff.values, (reg[:, None] == reg[None, :]).astype(float), (st[:, None] == st[None, :]).astype(float)))
    def nll(th):
        N, Rg, St, fl, ind = np.exp(th); tot = 0
        for e, ne, R, S in blocks:
            Cm = N ** 2 + Rg ** 2 * R + St ** 2 * S + np.diag(fl ** 2 + ind ** 2 / ne)
            L = np.linalg.cholesky(Cm); z = np.linalg.solve(L, e)
            tot += 0.5 * z @ z + np.log(np.diag(L)).sum()
        return tot
    res = minimize(nll, np.log([3, 1.5, 2, 2, 8]), method='L-BFGS-B', bounds=[(np.log(0.3), np.log(10))] * 5)
    N, Rg, St, fl, ind = np.exp(res.x)
    sd = np.sqrt(N ** 2 + Rg ** 2 + St ** 2 + fl ** 2 + ind ** 2 / df.neff); z = df.err / sd
    return _save('error_structure', dict(national=N, region=Rg, state=St, floor=fl, indiv=ind,
                                         z_sd=float(z.std()), cover80=float((z.abs() < 1.2816).mean()), cover95=float((z.abs() < 1.96).mean())))

def generic_ballot_history():
    """What the generic-ballot poll average said five days out in 2018-2022 (feeds the fundamentals fit)."""
    r = raw_polls(types=('House-G-US',), cycles=[2018, 2020, 2022]); r['race'] = 'US'
    out = {}
    for cy, g in r.groupby('cycle'):
        out[int(cy)] = average(g, g.eday.max() - pd.Timedelta(days=5), half_life=10, cfg=dict(house_effects=False))[0]
    return _save('generic_ballot_history', out)

# ------------------------------------------------------------------ House fundamentals
def _fec_money(fec, did, name, party):
    d = fec[(fec.did == did) & (fec.p == party) & (fec.office == 'H')]
    if not len(d): return None
    last = nz(name).replace('jr.', '').replace(' jr', '').split()[-1] if name else ''
    m = d[d['last'] == last] if last else d.iloc[0:0]
    if not len(m) and last: m = d[d['last'].str.contains(last, regex=False)]
    row = (m if len(m) else d).sort_values('receipts', ascending=False).iloc[0]
    return float(row.raised), bool(len(m))

def house_features():
    """Per-district features for 2018-2024: PVI, incumbency, FEC money ratio, incumbent personal vote."""
    H = pd.DataFrame(parse_house_history(C.STATIC / 'wikipedia', C.HIST_HOUSE_YEARS))
    fec = {y: F_.load(C.STATIC / 'fec' / f'webl{str(y)[2:]}.txt') for y in C.HIST_HOUSE_YEARS}
    rows = []
    for _, r in H.iterrows():
        if not r.contested or r.pvi is None or pd.isna(r.pvi) or abs(r.margin) >= 60: continue
        dc = max([c for c in r.cands if c['party'] == 'D'], key=lambda c: c['pct']); rc = max([c for c in r.cands if c['party'] == 'R'], key=lambda c: c['pct'])
        md = _fec_money(fec[r.year], r.id, dc['name'], 'D'); mr = _fec_money(fec[r.year], r.id, rc['name'], 'R')
        rows.append(dict(year=r.year, id=r.id, pvi=r.pvi, inc=r.inc_running, margin=r.margin,
                         d_raised=md[0] if md else 0.0, r_raised=mr[0] if mr else 0.0,
                         inc_name=(dc['name'] if r.inc_running == 1 else rc['name'] if r.inc_running == -1 else None)))
    Fd = pd.DataFrame(rows)
    Fd['money'] = (np.log1p(Fd.d_raised.clip(lower=0)) - np.log1p(Fd.r_raised.clip(lower=0))).clip(-6, 6)
    Fd['resid0'] = 0.0
    for y in Fd.year.unique():
        m = Fd.year == y; d = Fd[m]
        X = np.c_[np.ones(len(d)), 2 * d.pvi, d.inc]; b, *_ = np.linalg.lstsq(X, d.margin, rcond=None)
        Fd.loc[m, 'resid0'] = (d.margin - X @ b).values
    prev = {(r.year, r.id): r for r in Fd.itertuples()}
    redist = {2024: {'AL', 'GA', 'LA', 'NY', 'NC'}}
    pv = []
    for r in Fd.itertuples():
        p = prev.get((r.year - 2, r.id))
        ok = (r.inc != 0 and p is not None and p.inc == r.inc and isinstance(p.inc_name, str) and isinstance(r.inc_name, str)
              and nz(p.inc_name).split()[-1] == nz(r.inc_name).split()[-1] and r.year != 2022
              and r.id.split('-')[0] not in redist.get(r.year, set()))
        pv.append(p.resid0 if ok else 0.0)
    Fd['pv'] = pv
    Fd.to_csv(C.CALIB / 'house_features.csv', index=False)
    return Fd

FEATS = ['money', 'pv']
def fit_fundamentals(df, gen_hist, natc):
    yrs = sorted(df.year.unique())
    X = np.c_[pd.get_dummies(df.year).reindex(columns=yrs).values.astype(float), 2 * df.pvi, df.inc, df[FEATS].values]
    b, *_ = np.linalg.lstsq(X, df.margin, rcond=None)
    fe = dict(zip(yrs, b[:len(yrs)])); slope = b[len(yrs):]
    c0 = np.mean([fe[y] - natc * gen_hist[y] for y in yrs if y in gen_hist])
    return dict(c0=float(c0), slope=[float(s) for s in slope], resid_sd=float((df.margin - X @ b).std()))

def fundamentals_backtest():
    """Leave-one-year-out error of House fundamentals with and without the new features; final coefficients."""
    Fd = house_features()
    gen = {int(k): v for k, v in load('generic_ballot_history').items()}
    rows = []
    for name, feats in [('Partisan lean + incumbency', []), ('+ FEC fundraising ratio', ['money']), ('+ incumbent personal vote', ['pv']), ('+ both (used)', ['money', 'pv'])]:
        per = []
        for y in sorted(Fd.year.unique()):
            tr, te = Fd[Fd.year != y], Fd[Fd.year == y]
            cols = lambda d: np.c_[2 * d.pvi, d.inc, d[feats].values] if feats else np.c_[2 * d.pvi, d.inc]
            X = np.c_[pd.get_dummies(tr.year).values.astype(float), cols(tr)]
            b, *_ = np.linalg.lstsq(X, tr.margin, rcond=None)
            p0 = cols(te) @ b[len(tr.year.unique()):]
            e = te.margin - p0 - (te.margin - p0).mean()          # national level taken as known: isolates seat-level skill
            comp = (2 * te.pvi).abs() < 20
            per.append(RMSE(e[comp]))
        rows.append(dict(method=name, rmse=round(float(np.mean(per)), 2), by_year=[round(x, 2) for x in per]))
    coef = fit_fundamentals(Fd, gen, C.MODEL['natc'])
    return _save('fundamentals', dict(rows=rows, coef=coef, years=sorted(int(y) for y in Fd.year.unique())))

def house_forecast_backtest(nsim=20000):
    """The whole House forecast (fundamentals + district polls + shared-error simulation) on 2018-2022, leave-one-year-out."""
    Fd = pd.read_csv(C.CALIB / 'house_features.csv')
    gen = {int(k): v for k, v in load('generic_ballot_history').items()}
    comp = load('error_structure'); natc = C.MODEL['natc']
    r = raw_polls(types=('House-G',), cycles=[2018, 2020, 2022])
    asof = (r.groupby('race_id').eday.first() - pd.Timedelta(days=5)).to_dict()
    pav = {}
    for cy, rc in r.groupby('cycle'):
        house = estimate_house_effects(rc, asof, iters=1)
        for rid, g in rc.groupby('race_id'):
            m, ne, _ = average(g, asof[rid], half_life=C.MODEL['half_life'], house=house); pav[(cy, g.location.iloc[0])] = (m, ne)
    rng = np.random.default_rng(1)
    out = {}
    for label, use_feats, sf in [('old', False, 7.0), ('new', True, C.MODEL['sigma_fund_house'])]:
        P_, O_, E_, seats = [], [], [], []
        for y in [2018, 2020, 2022]:
            tr, te = Fd[Fd.year != y], Fd[Fd.year == y]
            c = fit_fundamentals(tr, gen, natc)
            if not use_feats:
                yrs = sorted(tr.year.unique())
                X = np.c_[pd.get_dummies(tr.year).reindex(columns=yrs).values.astype(float), 2 * tr.pvi, tr.inc]
                b, *_ = np.linalg.lstsq(X, tr.margin, rcond=None); fe = dict(zip(yrs, b[:len(yrs)]))
                c = dict(c0=np.mean([fe[t] - natc * gen[t] for t in yrs if t in gen]), slope=[b[len(yrs)], b[len(yrs) + 1], 0, 0])
            s = c['slope']
            f = (c['c0'] + natc * gen[y] + s[0] * 2 * te.pvi + s[1] * te.inc + s[2] * te.money + s[3] * te.pv).values
            pm = np.array([pav.get((y, d), (np.nan, 0))[0] for d in te.id]); ne = np.array([pav.get((y, d), (np.nan, 0))[1] for d in te.id])
            psd = np.sqrt(comp['floor'] ** 2 + comp['indiv'] ** 2 / np.maximum(ne, 1e-9))
            wp = np.where(np.isnan(pm), 0, (1 / psd ** 2) / (1 / psd ** 2 + 1 / sf ** 2))
            mu = np.where(np.isnan(pm), f, wp * np.nan_to_num(pm) + (1 - wp) * f)
            sd = np.where(np.isnan(pm), sf, 1 / np.sqrt(1 / psd ** 2 + 1 / sf ** 2))
            stv = [d.split('-')[0] for d in te.id]
            nat = comp['national'] * rng.standard_normal(nsim)
            regs = {g: comp['region'] * rng.standard_normal(nsim) for g in sorted(set(C.REGION.values()))}
            sts = {k: comp['state'] * rng.standard_normal(nsim) for k in sorted(C.REGION)}
            draws = mu[:, None] + nat + np.array([regs[C.REGION[k]] for k in stv]) + np.array([sts[k] for k in stv]) + sd[:, None] * rng.standard_normal((len(te), nsim))
            p = (draws > 0).mean(1); o = (te.margin.values > 0).astype(int)
            P_ += list(p); O_ += list(o); E_ += list(mu - te.margin.values)
            tot = (draws > 0).sum(0); seats.append(dict(year=y, actual=int(o.sum()), median=int(np.median(tot)), pctile=float((tot < o.sum()).mean() * 100)))
        P_, O_ = np.array(P_), np.array(O_)
        bins = pd.cut(P_, [0, .05, .2, .35, .5, .65, .8, .95, 1], include_lowest=True)
        cal = pd.DataFrame(dict(p=P_, o=O_, b=bins)).groupby('b', observed=True).agg(pred=('p', 'mean'), obs=('o', 'mean'), n=('o', 'size'))
        out[label] = dict(brier=float(np.mean((P_ - O_) ** 2)), rmse=RMSE(E_),
                          logloss=float(-np.mean(O_ * np.log(np.clip(P_, 1e-4, 1)) + (1 - O_) * np.log(np.clip(1 - P_, 1e-4, 1)))),
                          seats=seats, bins=[dict(lo=float(i.left), hi=float(i.right), predicted=float(rw.pred), observed=float(rw.obs), races=int(rw.n)) for i, rw in cal.iterrows()])
    return _save('house_forecast_backtest', out)

def poll_miss_history():
    """Average polling miss per cycle (positive = polls overstated Democrats), 2010-2022 from the backtest, later cycles from config."""
    d = pd.read_csv(C.CALIB / 'poll_average_errors.csv')
    rows = []
    for cy, g in d.groupby('cycle'):
        rows.append(dict(cycle=int(cy), dem_overstatement=round(float(g.err.mean()), 1), kind='Midterm' if cy % 4 == 2 else 'Presidential year',
                         races=int(len(g)), source='FiveThirtyEight poll archive; weighted averages five days out, Senate, governor and House'))
    rows += [dict(r, races=None) for r in C.EXTRA_POLL_MISSES]
    rows.sort(key=lambda r: r['cycle'])
    vals = [r['dem_overstatement'] for r in rows]
    mids = [r['dem_overstatement'] for r in rows if r['kind'] == 'Midterm']
    v = np.array(vals)
    loco = np.array([v[i] - np.delete(v, i).mean() for i in range(len(v))])   # predict each cycle's miss from the others
    return _save('poll_miss_history', dict(rows=rows, mean_all=float(v.mean()), mean_midterm=float(np.mean(mids)),
                                           share_overstating_dems=float(np.mean(v > 0)), sd_all=float(v.std(ddof=1)),
                                           loco_rmse_assume_zero=float(np.sqrt(np.mean(v ** 2))), loco_rmse_assume_history=float(np.sqrt(np.mean(loco ** 2)))))

def run_all(include_hierarchical=True):
    steps = [poll_average_backtest, poll_miss_history, error_structure, generic_ballot_history, fundamentals_backtest, house_forecast_backtest]
    if include_hierarchical: steps.append(hierarchical_backtest)
    for s in steps:
        log.info('calibrate: %s', s.__name__); s()
