"""Bayesian hierarchical poll model (Gaussian, solved exactly).

poll margin_p = alpha[race_p] + h[pollster_p] + s[sponsor_p] + lv*[RV/A]_p + g[week_p] + e_p
  alpha[r]  ~ N(prior_mean_r, prior_sd_r^2)          election-day true margin (fundamentals prior)
  h[k]      ~ N(0, tau_h^2)                           pollster house effect
  s_D ~ N(+2, 2^2), s_R ~ N(-2, 2^2)                  campaign/party-sponsored poll effect
  rv        ~ N(0, 2^2)                               registered/all-adult vs likely-voter difference
  g[0] = 0 (election week); g[w] - g[w-1] ~ N(0, tau_g^2)   national trend, shared by all races
  e_p ~ N(0, samp^2*600/n + sig_m^2 + omega^2*age_days/30)  sampling + method noise + race-level drift
Hyperparameters (tau_h, sig_m, omega, tau_g) by maximising the marginal likelihood.
"""
import numpy as np, pandas as pd
from scipy.optimize import minimize

SAMP = 4.3
NCLIP = (150, 5000)
EXTRA_POLLSTER_CORR = False  # sd of a margin from a pure random sample of 600 (2*sqrt(.25/600)*100 ~ 4.1, rounded up for design effect)

def build(P, races, pollsters, asof, nweeks):
    R, K, W = len(races), len(pollsters), nweeks
    ri = {r: i for i, r in enumerate(races)}; ki = {k: i for i, k in enumerate(pollsters)}
    n = len(P); p = R + K + 3 + W
    X = np.zeros((n, p))
    rows = np.arange(n)
    X[rows, P.race.map(ri).values] = 1
    X[rows, R + P.pkey.map(ki).values] = 1
    X[P.partisan.values == 'D', R + K] = 1
    X[P.partisan.values == 'R', R + K + 1] = 1
    X[np.isin(P['pop'].values, ['RV', 'A']), R + K + 2] = 1
    age = np.clip((asof - P.end).dt.days.values, 0, None)
    wk = np.minimum(age // 7, W)  # week 0 = last 7 days -> g fixed 0
    for j, w in enumerate(wk):
        if w > 0: X[j, R + K + 3 + w - 1] = 1
    nn = P.n.fillna(500).clip(*NCLIP).values
    return X, nn, age

def prior(races, prior_mean, prior_sd, K, W, tau_h, tau_g):
    R = len(races); p = R + K + 3 + W
    m0 = np.zeros(p); Pinv = np.zeros((p, p))  # prior precision
    for i, r in enumerate(races):
        m0[i] = prior_mean[r]; Pinv[i, i] = 1 / prior_sd[r] ** 2
    Pinv[R:R + K, R:R + K] = np.eye(K) / tau_h ** 2
    m0[R + K] = 2.0; m0[R + K + 1] = -2.0
    Pinv[R + K, R + K] = Pinv[R + K + 1, R + K + 1] = 1 / 2.0 ** 2
    Pinv[R + K + 2, R + K + 2] = 1 / 2.0 ** 2
    # random walk precision on g[1..W] with g[0]=0: D g ~ N(0, tau_g^2 I)
    D = np.zeros((W, W))
    for w in range(W):
        D[w, w] = 1
        if w > 0: D[w, w - 1] = -1
    Pinv[R + K + 3:, R + K + 3:] = D.T @ D / tau_g ** 2
    return m0, Pinv

GRADE_MULT = None  # optional per-poll multiplier on method noise (lower-rated pollsters noisier)
def noise_var(nn, age, sig_m, omega):
    gm = 1.0 if GRADE_MULT is None else GRADE_MULT
    return SAMP ** 2 * 600 / nn + (sig_m * gm) ** 2 + omega ** 2 * age / 30.0

def posterior(X, y, v, m0, Pinv):
    Wt = 1 / v
    Q = Pinv + (X.T * Wt) @ X
    b = Pinv @ m0 + X.T @ (Wt * y)
    L = np.linalg.cholesky(Q)
    mu = np.linalg.solve(L.T, np.linalg.solve(L, b))
    Linv = np.linalg.inv(L)
    cov = Linv.T @ Linv
    return mu, cov

def group(X, y, v, gid, tau_kr):
    G = gid.max() + 1
    cnt = np.bincount(gid, minlength=G).astype(float)
    Xg = np.zeros((G, X.shape[1])); np.add.at(Xg, gid, X); Xg /= cnt[:, None]
    yg = np.bincount(gid, weights=y, minlength=G) / cnt
    vg = np.bincount(gid, weights=v, minlength=G) / cnt ** 2 + tau_kr ** 2
    return Xg, yg, vg

def neg_marglik(theta, X, y, nn, age, races, prior_mean, prior_sd, K, W, gid=None, tau_kr=None):
    tau_h, sig_m, omega, tau_g = np.exp(theta[:4])
    m0, Pinv = prior(races, prior_mean, prior_sd, K, W, tau_h, tau_g)
    v = noise_var(nn, age, sig_m, omega)
    if gid is not None:
        X, y, v = group(X, y, v, gid, np.exp(theta[4]) if len(theta) > 4 else tau_kr)
    # marginal: y ~ N(X m0, X Pinv^-1 X' + diag v) ; use matrix determinant lemma via Q
    Wt = 1 / v
    Q = Pinv + (X.T * Wt) @ X
    r = y - X @ m0
    # Woodbury: (V + X S X')^-1 = W - W X Q^-1 X' W ;  logdet = logdet(Q) - logdet(Pinv) + sum log v
    WX = X * Wt[:, None]
    L = np.linalg.cholesky(Q)
    z = np.linalg.solve(L, WX.T @ r)
    quad = r @ (Wt * r) - z @ z
    # logdet(Pinv) (block diagonal, all positive definite)
    sign, ld_P = np.linalg.slogdet(Pinv)
    ld = 2 * np.log(np.diag(L)).sum() - ld_P + np.log(v).sum()
    return 0.5 * (quad + ld)

def fit(P, prior_mean, prior_sd, asof, nweeks=26, theta0=(1.0, 1.0, 1.0, 0.5, 2.0), optimize=True, fixed=None, grouped=True):
    """P: DataFrame with race, pkey, margin, end (Timestamp), n, pop, partisan. Returns dict."""
    P = P.copy().reset_index(drop=True)
    P['partisan'] = P['partisan'].where(P['partisan'].isin(['D', 'R']), None)
    P['pop'] = P['pop'].fillna('LV')
    races = sorted(P.race.unique().tolist() + [r for r in prior_mean if r not in set(P.race)])
    pollsters = sorted(P.pkey.unique())
    K, W = len(pollsters), nweeks
    X, nn, age = build(P, races, pollsters, asof, W)
    y = P.margin.values.astype(float)
    gid = pd.factorize(P.pkey + '|' + P.race)[0] if grouped else None
    th = np.log(np.array(theta0, float))
    if fixed is not None:
        th = np.log(np.array(fixed, float))
    elif optimize:
        res = minimize(neg_marglik, th, args=(X, y, nn, age, races, prior_mean, prior_sd, K, W, gid), method='L-BFGS-B',
                       bounds=[(np.log(0.3), np.log(8)), (np.log(0.5), np.log(10)), (np.log(0.1), np.log(6)), (np.log(0.05), np.log(3)), (np.log(0.3), np.log(8))])
        th = res.x
    tau_h, sig_m, omega, tau_g, tau_kr = np.exp(th)
    m0, Pinv = prior(races, prior_mean, prior_sd, K, W, tau_h, tau_g)
    v = noise_var(nn, age, sig_m, omega)
    Xf, yf, vf = (X, y, v) if gid is None else group(X, y, v, gid, tau_kr)
    mu, cov = posterior(Xf, yf, vf, m0, Pinv)
    R = len(races)
    return dict(races=races, alpha=mu[:R], alpha_cov=cov[:R, :R], house={k: mu[R + i] for i, k in enumerate(pollsters)},
                house_sd={k: np.sqrt(cov[R + i, R + i]) for i, k in enumerate(pollsters)},
                sponsor=(mu[R + K], mu[R + K + 1]), rv=mu[R + K + 2], trend=np.r_[0, mu[R + K + 3:]],
                hyper=dict(tau_h=tau_h, sig_m=sig_m, omega=omega, tau_g=tau_g, tau_kr=tau_kr), npolls=len(P),
                resid=y - X @ mu, X=X, mu=mu)
