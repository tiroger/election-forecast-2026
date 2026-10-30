"""Poll averaging shared by the backtest and the forecast: recency, sample size, population, pollster grade,
per-pollster cap, sponsor adjustment and shrunken pollster house effects."""
import numpy as np, pandas as pd, re
from . import config as C

def norm_pollster(s):
    s = (s or '').lower()
    s = re.sub(r'\(.*?\)|\bpoll(ing|s)?\b|\buniversity\b|\bcollege\b|\binc\.?|\bllc\b|[^a-z0-9 /&]', ' ', s)
    s = s.replace('the ', ' ')
    return re.sub(r'\s+', ' ', s).strip()

def load_grades():
    c = pd.read_csv(C.STATIC / '538' / 'pollster-ratings-combined.csv')
    g = {}
    for _, r in c.iterrows():
        for part in re.split(r'/', str(r.pollster)):
            k = norm_pollster(part)
            if k and k not in g:
                g[k] = r.numeric_grade if pd.notna(r.numeric_grade) else None
    return g

GRADES = None
def grade_of(name):
    global GRADES
    if GRADES is None:
        GRADES = load_grades()
    k = norm_pollster(name)
    if k in GRADES:
        return GRADES[k]
    for part in re.split(r'/|\bfor\b|,', k):
        p = part.strip()
        if p in GRADES:
            return GRADES[p]
    # prefix match
    for kk, v in GRADES.items():
        if len(kk) > 5 and (k.startswith(kk) or kk.startswith(k)) and len(k) > 5:
            return v
    return None

def poll_weights(df, asof, half_life=14.0, cfg=None):
    """df columns: pollster, end (Timestamp), n, pop, partisan(D/R/None)."""
    cfg = cfg or {}
    age = (asof - df['end']).dt.days.clip(lower=0).astype(float)
    w = 0.5 ** (age / half_life)
    n = df['n'].fillna(500).clip(lower=150)
    w *= np.clip(np.sqrt(n / 600.0), 0.5, 2.0)
    popw = {'LV': 1.0, 'RV': 0.8, 'A': 0.6, 'V': 1.0}
    w *= df['pop'].map(lambda p: popw.get(p, 0.9)).astype(float)
    if cfg.get('grades', True):
        g = df['pollster'].map(grade_of)
        w *= g.map(lambda x: 0.75 if x is None or pd.isna(x) else 0.55 + 0.15 * x).astype(float)
    w *= np.where(df['partisan'].notna(), cfg.get('partisan_w', 0.5), 1.0)
    # limit dominance of one pollster: divide by sqrt(#polls by pollster in race)
    if cfg.get('pollster_cap', True):
        cnt = df.groupby('pkey')['pkey'].transform('size').astype(float)
        w /= np.sqrt(cnt)
    return w

def average(df, asof, half_life=14.0, cfg=None, house=None, sigma_indiv=5.0):
    """Return (avg margin, n_eff, sd of avg sampling-ish component). margin col = D minus R (or challenger minus R)."""
    cfg = cfg or {}
    if len(df) == 0:
        return None, 0.0, None
    d = df.copy()
    adj = d['margin'].astype(float).copy()
    ps = cfg.get('partisan_shift', 3.0)
    if ps:
        adj -= np.where(d['partisan'] == 'D', ps, 0) - np.where(d['partisan'] == 'R', ps, 0)
    if house is not None and cfg.get('house_effects', True):
        adj -= d['pkey'].map(lambda k: house.get(k, 0.0)).astype(float)
    # if few recent polls, lengthen half-life so old polls still count
    hl = half_life
    recent = ((asof - d['end']).dt.days <= 21).sum()
    if recent < 3:
        hl = half_life * 2
    w = poll_weights(d, asof, hl, cfg)
    if w.sum() <= 0:
        return None, 0.0, None
    m = float((w * adj).sum() / w.sum())
    neff = float(w.sum() ** 2 / (w ** 2).sum())
    return m, neff, sigma_indiv / np.sqrt(neff)

def estimate_house_effects(all_polls, asof_map, k=4.0, cap=4.0, iters=2, cfg=None):
    """all_polls: DataFrame with race, pkey, margin, end, ... ; asof_map race->Timestamp.
    House effect = shrunken mean deviation of a pollster from race averages that exclude it."""
    house = {}
    for _ in range(iters):
        devs = []
        for race, g in all_polls.groupby('race'):
            if g['pkey'].nunique() < 3:
                continue
            for pk, gp in g.groupby('pkey'):
                others = g[g['pkey'] != pk]
                m, _, _ = average(others, asof_map[race], cfg=dict(cfg or {}, house_effects=True), house=house)
                if m is None:
                    continue
                for v in gp['margin']:
                    devs.append((pk, v - m))
        dv = pd.DataFrame(devs, columns=['pkey', 'dev'])
        agg = dv.groupby('pkey')['dev'].agg(['sum', 'count'])
        house = {pk: float(np.clip(r['sum'] / (r['count'] + k), -cap, cap)) for pk, r in agg.iterrows() if r['count'] >= 2}
    return house
