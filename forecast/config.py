"""Paths, model settings and constants shared by every stage."""
from __future__ import annotations
import os
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get('FORECAST_ROOT', Path(__file__).resolve().parents[1]))
DATA = ROOT / 'data'
RAW = DATA / 'raw'                 # raw/<YYYY-MM-DD>/... daily snapshots; raw/static/... sources that never change
STATIC = RAW / 'static'
PROCESSED = DATA / 'processed'     # parsed tables for the latest run
CALIB = DATA / 'calibration'       # backtest outputs that feed model settings
HISTORY = DATA / 'history'         # one forecast summary per day + full daily outputs
SITE = ROOT / 'site'               # the published page
SITE_DATA = SITE / 'data'
PAGE = ROOT / 'page'               # page source (shared with the Claude dashboard)

USER_AGENT = os.environ.get('FORECAST_UA', 'ElectionForecast2026/1.0 (research; contact via repository)')

ELECTION_DAY = date(2026, 11, 3)

def as_of() -> date:
    """Forecast date: FORECAST_ASOF=YYYY-MM-DD to replay a past day, else today."""
    v = os.environ.get('FORECAST_ASOF')
    return date.fromisoformat(v) if v else date.today()

# Model settings. Values marked (calibrated) are overwritten at run time by data/calibration/*.json.
MODEL = dict(
    half_life=14.0, gen_half_life=10.0,          # poll recency, days (backtest: flat between 10 and 21)
    house_effect_k=4.0, house_effect_cap=4.0,    # shrinkage and cap on pollster lean
    partisan_shift=2.0, partisan_weight=0.5,     # campaign/party-sponsored polls
    natc=0.85,                                   # share of the generic-ballot margin that flows to a seat
    sigma_indiv=8.53, sigma_floor=0.77,          # (calibrated) race-specific poll-average error
    sigma_fund_house=6.0, sigma_fund_senate=8.0, sigma_fund_indep=11.0, sigma_fund_three_way=14.0,
    sigma_rating=8.0, sigma_rating_safe=12.0, use_ratings=True,
    sen_inc=3.0,                                 # Senate incumbency, margin points; appointees get half
    nat_sd=3.02, region_sd=1.47, state_sd=2.79,  # (calibrated) layers of shared polling error
    t_df=6, nsims=40000, seed=7, max_poll_age_days=200,
    nat_bias='history_midterm',                  # assumed polling lean (midterm average of past misses), pts (>0: polls overstate Democrats); or 'history_all' / 'history_midterm'
)

REGION = {}
for _r, _sts in {'NE': 'CT ME MA NH RI VT NJ NY PA', 'MW': 'IL IN MI OH WI IA KS MN MO NE ND SD',
                 'S': 'DE FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX DC',
                 'W': 'AZ CO ID MT NV NM UT WY AK CA HI OR WA'}.items():
    for _s in _sts.split():
        REGION[_s] = _r

STATES = ['Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
          'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts',
          'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
          'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island',
          'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
          'Wisconsin', 'Wyoming']
AT_LARGE = {'Alaska', 'Delaware', 'North Dakota', 'South Dakota', 'Vermont', 'Wyoming'}

# States whose House map changed for 2026 (mid-decade redistricting in effect)
REDISTRICTED_2026 = {'TX', 'NC', 'OH', 'FL', 'TN', 'LA', 'AL', 'CA', 'UT'}

# Historical cycles used for calibration
HIST_HOUSE_YEARS = [2018, 2020, 2022, 2024]
NATIONAL_HOUSE_VOTE = {2018: 8.6, 2020: 3.1, 2022: -2.7, 2024: -2.6}   # D minus R, two-party-ish, for reference only

# Polling misses not covered by the 538 archive (which ends in 2022). Positive = polls overstated Democrats (margin points).
EXTRA_POLL_MISSES = [
    dict(cycle=2024, dem_overstatement=3.0, kind='Presidential year',
         source='Silver Bulletin, "So, how did the polls do in 2024?": about 3 points of Democratic bias in presidential, Senate and House polls'),
]

def ensure_dirs():
    for p in (RAW, STATIC, PROCESSED, CALIB, HISTORY, SITE_DATA):
        p.mkdir(parents=True, exist_ok=True)
