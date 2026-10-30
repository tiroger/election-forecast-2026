"""Download every source. Daily sources go to data/raw/<date>/, fixed historical sources to data/raw/static/ (fetched once)."""
from __future__ import annotations
import io, json, time, zipfile, logging
from pathlib import Path
import requests
from . import config as C

log = logging.getLogger(__name__)
S = requests.Session()
S.headers['User-Agent'] = C.USER_AGENT

PC = 'https://www.pollcheck.co.uk/us-midterms-2026'
WIKI = 'https://en.wikipedia.org/wiki/{}?action=raw'
FEC = 'https://www.fec.gov/files/bulk-downloads/20{yy}/webl{yy}.zip'
G538 = 'https://raw.githubusercontent.com/fivethirtyeight/data/master/pollster-ratings/{}'

def day_dir(d=None) -> Path:
    p = C.RAW / (d or C.as_of()).isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _get(url, tries=6, pause=0.0, binary=False):
    wait = 5
    for i in range(tries):
        r = S.get(url, timeout=60)
        if r.status_code == 200:
            if pause: time.sleep(pause)
            return r.content if binary else r.text
        if r.status_code == 404:
            return None
        if r.status_code in (429, 500, 502, 503, 504):
            log.warning('%s -> %s, retrying in %ss', url, r.status_code, wait)
            time.sleep(wait); wait = min(wait * 2, 120); continue
        r.raise_for_status()
    raise RuntimeError(f'gave up on {url}')

def wiki(title: str, dest: Path, force=False) -> bool:
    if dest.exists() and not force:
        return True
    t = _get(WIKI.format(title.replace(' ', '_')), pause=1.2)
    if t is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(t)
    return True

# ---------------------------------------------------------------- daily sources
def fetch_pollcheck(d: Path):
    out = d / 'pollcheck'; (out / 'races').mkdir(parents=True, exist_ok=True)
    sen = json.loads(_get(f'{PC}/data/senate.json'))
    (out / 'senate.json').write_text(json.dumps(sen))
    for r in sen['races']:
        (out / 'races' / f"{r['id']}.json").write_text(_get(f"{PC}/data/races/{r['id']}.json"))
    (out / 'generic_ballot.json').write_text(_get(f'{PC}/data/generic_ballot.json'))
    return len(sen['races'])

def fetch_wikipedia_2026(d: Path, force=False):
    w = d / 'wikipedia'
    ok = []
    ok.append(wiki('2026 United States House of Representatives elections', w / 'house_overview.txt', force))
    ok.append(wiki('2026 United States House of Representatives election ratings', w / 'house_ratings.txt', force))
    ok.append(wiki('2026 United States Senate elections', w / 'senate_overview.txt', force))
    for s in C.STATES:
        kind = 'election' if s in C.AT_LARGE else 'elections'
        ok.append(wiki(f'2026 United States House of Representatives {kind} in {s}', w / 'house_states' / f"{s.replace(' ', '_')}.txt", force))
    return sum(ok), len(ok)

def fetch_fec(yy: str, dest_dir: Path, force=False):
    dest = dest_dir / f'webl{yy}.txt'
    if dest.exists() and not force:
        return dest
    z = zipfile.ZipFile(io.BytesIO(_get(FEC.format(yy=yy), binary=True)))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(z.read(f'webl{yy}.txt'))
    return dest

# ---------------------------------------------------------------- static (historical) sources
def fetch_static(force=False):
    st = C.STATIC
    for f in ['raw_polls.csv', 'pollster-ratings-combined.csv']:
        p = st / '538' / f
        if force or not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(_get(G538.format(f), binary=True))
    for y in C.HIST_HOUSE_YEARS:
        wiki(f'{y} United States House of Representatives elections', st / 'wikipedia' / f'house{y}.txt', force)
    for yy in ['18', '20', '22', '24']:
        fetch_fec(yy, st / 'fec', force)

def fetch_daily(d=None, force=False):
    """Everything that changes day to day. Safe to re-run: Wikipedia pages already saved today are kept unless force."""
    C.ensure_dirs()
    dd = day_dir(d)
    fetch_static()
    n_pc = fetch_pollcheck(dd)
    n_ok, n_w = fetch_wikipedia_2026(dd, force)
    fetch_fec('26', dd / 'fec', force=True)
    (C.RAW / 'LATEST').write_text(dd.name)
    return dict(dir=str(dd), pollcheck_races=n_pc, wikipedia_pages=f'{n_ok}/{n_w}')

def latest_dir() -> Path:
    """Most recent complete daily snapshot (or the one named by FORECAST_ASOF)."""
    import os
    if os.environ.get('FORECAST_ASOF'):
        return C.RAW / os.environ['FORECAST_ASOF']
    p = C.RAW / 'LATEST'
    if p.exists():
        return C.RAW / p.read_text().strip()
    days = sorted(x for x in C.RAW.iterdir() if x.is_dir() and x.name[:2] == '20')
    return days[-1]
