"""Wikipedia wikitext parsers: 2026 House overview, state pages (district polls), ratings tables, past House results."""
from __future__ import annotations
import re, json, glob, os, unicodedata
from datetime import date
from pathlib import Path

def nz(x):
    return unicodedata.normalize('NFKD', x or '').encode('ascii', 'ignore').decode().lower()

def parse_house_overview(path):
    """2026 House overview page -> one record per district (PVI, incumbents, nominees)."""
    txt = Path(path).read_text().replace('&nbsp;', ' ')
    start = txt.index('\n==Alabama==')
    end = txt.index('\n==Non-voting delegates==')
    body = txt[start:end]
    
    STATE_ABBR = {}
    districts = []
    sections = re.split(r'\n==([A-Z][A-Za-z ]+)==\n', body)
    # sections: ['', name, content, name, content ...]
    for i in range(1, len(sections), 2):
        state = sections[i].strip()
        content = sections[i + 1]
        m = content.find('{|')
        table = content[m:content.find('\n|}', m)]
        rows = re.split(r'\n\|-[^\n]*', table)
        cur = None
        for row in rows:
            mu = re.search(r'\{\{ushr\|([A-Z]{2})\|([^|}]+)', row)
            is_new = bool(mu) and re.match(r'\s*!', row.strip('\n')) is not None and 'Redistricted from' not in row.split('\n')[0]
            if mu and row.lstrip().startswith('!'):
                st, num = mu.group(1), mu.group(2)
                STATE_ABBR[state] = st
                num = 'AL' if num.upper() in ('AL', 'AT-LARGE') else num
                cur = {'state': state, 'st': st, 'district': num, 'id': f'{st}-{num}',
                       'pvi': None, 'incumbents': [], 'candidates': [], 'status': []}
                districts.append(cur)
                mp = re.search(r'shading PVI\|(EVEN|([RD])\|([\d.]+))', row)
                if mp:
                    cur['pvi'] = 0.0 if mp.group(1) == 'EVEN' else (float(mp.group(3)) * (1 if mp.group(2) == 'D' else -1))
            if cur is None:
                continue
            # incumbent
            lines = row.split('\n')
            name = None
            ms = re.search(r'\{\{sortname\|([^|}]+)\|([^|}]+)', row)
            if ms:
                name = f'{ms.group(1)} {ms.group(2)}'
            else:
                ml = re.search(r'^\|\s*\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', row, re.M)
                if ml and 'Party' not in ml.group(1) and 'elections' not in ml.group(1):
                    name = ml.group(1)
            party = None
            for ln in lines:
                if re.search(r'background-color:#(FFB6B6|B0CEFF|DCDCDC|[0-9A-F]{6})', ln) or 'Party shading/Text' in ln:
                    if 'Republican' in ln: party = 'R'
                    elif 'Democratic' in ln: party = 'D'
                    elif 'Independent' in ln: party = 'I'
                if '|DFL' in ln.replace(' ', ''): party = 'D'
            if 'colspan=3|None' in row.replace(' ', ''):
                name = None
            status = ''
            for ln in lines:
                if re.search(r'Incumbent|New representative|Representative|retir|lost', ln) and 'Redistricted' not in ln and not ln.startswith('*'):
                    status = re.sub(r'<ref[^>]*/>|<ref.*?</ref>|\{\{[^}]*\}\}|\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', lambda m: m.group(1) or '', ln)
                    status = re.sub(r'<[^>]+>|^\|?\s*(style="[^"]*"\s*\|)?|nowrap\s*\|', '', status).strip(' |')
            if name and party:
                cur['incumbents'].append({'name': name, 'party': party, 'status': status,
                                          'redistricted_from': bool(re.search('Redistricted from', row))})
            elif status:
                cur['status'].append(status)
            for cm in re.finditer(r'^\*\{\{[Pp]arty stripe\|([^}]*)\}\}(.*)$', row, re.M):
                raw = cm.group(2)
                nm = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', raw)
                nm = re.sub(r"<ref.*?(</ref>|/>)|\{\{[^}]*\}\}|'''", '', nm).strip()
                mpar = re.search(r'\(([^)]*)\)\s*$', nm)
                ptxt = (mpar.group(1) if mpar else cm.group(1))
                nm = re.sub(r'\s*\([^)]*\)\s*$', '', nm).strip()
                st_ = cm.group(1).lower()
                pl = ptxt.lower()
                if 'independent republican' in st_: p = 'I'
                elif 'democratic' in st_ or 'farmer' in st_: p = 'D'
                elif st_.startswith('republican'): p = 'R'
                else: p = None
                if p: 
                    cur['candidates'].append({'name': nm, 'party': p, 'party_label': ptxt}); continue
                p = 'D' if 'democrat' in pl else 'R' if 'republican' in pl else 'L' if 'libertarian' in pl else 'G' if 'green' in pl else 'I'
                cur['candidates'].append({'name': nm, 'party': p, 'party_label': ptxt})
    
    for d in districts:
        d['running_incumbent'] = None
        cands = {nz(c['name']) for c in d['candidates']}
        for inc in d['incumbents']:
            iname = nz(inc['name']); last = iname.split()[-1]
            if any(iname == c or c.endswith(' ' + last) and c.split()[0][:3] == iname.split()[0][:3] for c in cands):
                d['running_incumbent'] = inc
    return districts




def strip_markup(s):
    s = s.replace('&nbsp;', ' ')
    s = re.sub(r'<ref[^>]*/>', '', s)
    s = re.sub(r'<ref.*?</ref>', '', s, flags=re.S)
    s = re.sub(r'\{\{efn[^{}]*(\{\{[^{}]*\}\}[^{}]*)*\}\}', '', s)
    s = re.sub(r'\{\{party shading/[^}]*\}\}\s*\|', '', s)
    s = re.sub(r'\{\{nowrap\|([^}]*)\}\}', r'\1', s)
    s = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', s)
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace("'''", '').replace("''", '')
    return re.sub(r'\s+', ' ', s).strip()

MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}

def parse_date(s):
    """Return end date of a field period like 'September 17–21, 2026' or 'Sep 30 – Oct 2, 2026'."""
    s = strip_markup(s).replace('–', '-').replace('—', '-')
    my = re.findall(r'(\d{4})', s)
    year = int(my[-1]) if my else 2026
    toks = re.findall(r'([A-Za-z]+)\.?\s*(\d{1,2})?', s)
    # find last month name and last day
    parts = re.split(r'\s*-\s*', re.sub(r',?\s*\d{4}', '', s))
    last = parts[-1].strip()
    mm = re.match(r'([A-Za-z]+)\.?\s+(\d{1,2})', last)
    if mm and mm.group(1)[:3].lower() in MON3:
        return date(year, MON3[mm.group(1)[:3].lower()], int(mm.group(2)))
    md = re.match(r'(\d{1,2})$', last)
    if md:
        mm0 = re.search(r'([A-Za-z]+)\.?\s+\d', parts[0])
        if mm0 and mm0.group(1)[:3].lower() in MON3:
            return date(year, MON3[mm0.group(1)[:3].lower()], int(md.group(1)))
    mm = re.match(r'([A-Za-z]+)\.?$', last)
    if mm and mm.group(1)[:3].lower() in MON3:
        return date(year, MON3[mm.group(1)[:3].lower()], 15)
    return None

def num(s):
    m = re.search(r'(\d+(?:\.\d+)?)', strip_markup(s).replace(',', ''))
    return float(m.group(1)) if m else None

def split_cells(row):
    cells = []
    for ln in row.split('\n'):
        ln = ln.rstrip()
        if not ln or ln.startswith('|-') or ln.startswith('|}') or ln.startswith('{|'):
            continue
        if ln.startswith('|') or ln.startswith('!'):
            body = ln[1:]
            for part in re.split(r'\|\||!!', body):
                # drop attribute prefix "style=...|"
                if re.match(r'\s*(style|rowspan|colspan|align|width|class|data-sort-value)[^|\[{]*\|', part) and not part.strip().startswith('{{'):
                    part = part.split('|', 1)[1]
                cells.append(part)
        elif cells:
            cells[-1] += '\n' + ln
    return cells

def parse_tables(text):
    out = []
    for m in re.finditer(r'\{\|(.*?)\n\|\}', text, flags=re.S):
        t = m.group(0)
        if 'Poll source' not in t:
            continue
        hidden = False
        pre = text[:m.start()]
        hb, he = pre.rfind('{{hidden begin'), pre.rfind('{{hidden end')
        if hb > he:
            hidden = True
        rows = re.split(r'\n\|-[^\n]*', t)
        header = None
        polls = []
        for r in rows:
            if 'Poll source' in r:
                hdr = [strip_markup(c) for c in split_cells(r)]
                header = hdr
                continue
            if header is None:
                continue
            cells = split_cells(r)
            if len(cells) < 5:
                continue
            polls.append({'cells_raw': cells, 'cells': [strip_markup(c) for c in cells]})
        out.append({'header': header, 'polls': polls, 'hidden': hidden, 'pos': m.start()})
    return out

def cand_key(colname, cands):
    """Match a header column like 'Chellie Pingree (D)' to a nominee."""
    cn = nz(re.sub(r'\([^)]*\)', '', colname)).strip()
    for c in cands:
        nm = nz(c['name'])
        last = re.sub(r'\b(jr|sr|ii|iii|iv)\.?$', '', nm).strip().split()[-1]
        if last and last in cn.split():
            return c
    return None

PARTISAN_PAT = re.compile(r'\((D|R)\)')

def extract_polls(section, cands, did):
    res = []
    for tb in parse_tables(section):
        hdr = tb['header']
        if not hdr:
            continue
        # candidate columns are after poll source/date/sample/moe
        try:
            ic = next(i for i, h in enumerate(hdr) if re.search(r'error', h, re.I)) + 1
        except StopIteration:
            ic = 4
        cols = []
        for j in range(ic, len(hdr)):
            h = hdr[j]
            if re.search(r'other|undecided|lean|someone', h, re.I):
                cols.append(('other' if re.search('other|someone', h, re.I) else 'und', None))
            else:
                cols.append(('cand', cand_key(h, cands)))
        matched = [c for k, c in cols if k == 'cand' and c]
        cand_cols = [c for k, c in cols if k == 'cand']
        parties = {c['party'] for c in matched}
        # require both top nominees present and no unmatched candidate columns
        if len(matched) < 2 or any(c is None for c in cand_cols):
            continue
        for p in tb['polls']:
            cells, raw = p['cells'], p['cells_raw']
            if len(cells) < ic + len(matched):
                continue
            src = cells[0]
            if re.search(r'^\s*(Aggregate|Average|Decision Desk|RealClear|270toWin|Race to the WH|Silver Bulletin|VoteHub)', src, re.I):
                continue
            d_end = parse_date(cells[1])
            ss = cells[2]
            n = num(ss)
            pop = re.search(r'\((LV|RV|A|V)\)', ss)
            vals = {}
            other = und = 0.0
            for (k, c), v in zip(cols, cells[ic:]):
                x = num(v)
                if k == 'cand' and c:
                    vals[c['name']] = x
                elif k == 'other':
                    other += x or 0
                elif k == 'und':
                    und += x or 0
            if any(v is None for v in vals.values()):
                continue
            partisan = None
            mp = PARTISAN_PAT.search(strip_markup(raw[0]).split('  ')[0])
            if mp:
                partisan = mp.group(1)
            sponsor = None
            ms = re.search(r'efn(?:-ua)?\|(?:name=[^|]*\|)?([^}]*)', raw[0])
            if ms:
                sponsor = strip_markup(ms.group(1))
            res.append({'district': did, 'pollster': re.sub(r'\s*\((D|R)\)\s*$', '', src).strip(), 'end': d_end.isoformat() if d_end else None,
                        'n': n, 'pop': pop.group(1) if pop else None, 'results': vals, 'other': other, 'und': und,
                        'partisan': partisan, 'sponsor': sponsor, 'hidden_table': tb['hidden']})
    # dedupe (same poll could appear twice)
    seen, out = set(), []
    for r in res:
        k = (r['pollster'], r['end'], tuple(sorted(r['results'].items())))
        if k in seen:
            continue
        seen.add(k); out.append(r)
    return out

RATING_PAT = re.compile(r'\{\{(?:USRaceRating|US political race rating|US Race Rating)\|([A-Za-z\- ]+)\|?([A-Z]*)')

def extract_ratings(section):
    out = []
    m = re.search(r'=+\s*Predictions\s*=+(.*?)(\n=|\Z)', section, flags=re.S)
    if not m:
        return out
    for row in re.split(r'\n\|-', m.group(1)):
        rm = RATING_PAT.search(row)
        if not rm:
            continue
        src = strip_markup(row.split('\n')[1] if row.startswith('\n') else row.split('\n')[0])
        src = strip_markup(re.sub(r'^\|?\s*(align=left|style="[^"]*")\s*\|', '', row.strip().split('\n')[0]))
        out.append({'source': src[:40], 'rating': rm.group(1).strip(), 'party': rm.group(2)})
    return out

def extract_money(section, cands):
    m = re.search(r'=+\s*Fundraising\s*=+(.*?)(\n=|\Z)', section, flags=re.S)
    if not m:
        return {}
    out = {}
    for row in re.split(r'\n\|-', m.group(1)):
        cells = [strip_markup(c) for c in split_cells(row)]
        if len(cells) >= 2 and '$' in ''.join(cells[1:2]):
            c = cand_key(cells[0], cands)
            if c:
                out[c['name']] = num(cells[1])
    return out


def parse_state_pages(states_dir, districts):
    """Per-state House pages -> general-election district polls, ratings and fundraising tables."""
    byid = {d['id']: d for d in districts}
    STATE_ST = {d['state']: d['st'] for d in districts}
    all_polls, ratings, money = [], {}, {}
    for f in sorted(glob.glob(str(Path(states_dir) / '*.txt'))):
        state = os.path.basename(f)[:-4].replace('_', ' ')
        st = STATE_ST.get(state)
        txt = open(f).read()
        parts = re.split(r'\n==\s*District (\d+)\s*==\s*\n', txt)
        if len(parts) == 1:
            secs = [('AL', txt)]
        else:
            secs = [(parts[i], parts[i + 1]) for i in range(1, len(parts), 2)]
        for num_, sec in secs:
            did = f'{st}-{num_}'
            if did not in byid:
                # at-large districts in multi-district? skip
                continue
            cands = byid[did]['candidates']
            gm = re.search(r'\n===\s*General election\s*===(.*?)(?=\n===[^=]|\Z)', sec, flags=re.S)
            gsec = gm.group(1) if gm else sec
            all_polls += extract_polls(gsec, cands, did)
            r = extract_ratings(gsec)
            if r: ratings[did] = r
            mo = extract_money(gsec, cands)
            if mo: money[did] = mo
    return all_polls, ratings, money

def parse_house_history(static_dir, years=(2018, 2020, 2022, 2024)):
    """Past House pages -> per-district PVI, incumbent running, two-party margin."""
    out = []
    for y in years:
        t = (Path(static_dir) / f'house{y}.txt').read_text().replace('&nbsp;', ' ')
        t = re.sub(r'\{\{[Ss]ortname\|([^|}]+)\|([^|}]+)[^}]*\}\}', r'[[\1 \2]]', t)
        import re as _r; t = t[_r.search(r'\n== ?Alabama ?==', t).start():]
        rows = re.split(r'\n\|-[^\n]*', t)
        cur = None
        recs = {}
        for row in rows:
            r0 = row.lstrip('\n')
            mu = re.match(r'!\s*(?:rowspan=\d+\s*\|\s*)?\{\{ushr\|([A-Z]{2})\|([^|}]+)\|X\}\}', r0)
            if mu:
                st, n = mu.group(1), mu.group(2)
                n = 'AL' if n.upper() in ('AL', 'AT-LARGE') else n
                cur = {'year': y, 'id': f'{st}-{n}', 'pvi': None, 'incs': [], 'cands': [], 'status': ''}
                recs[cur['id']] = cur
                mp = re.search(r'[Ss]hading PVI\|(EVEN|([RD])\|([\d.]+))', row)
                if mp:
                    cur['pvi'] = 0.0 if mp.group(1) == 'EVEN' else float(mp.group(3)) * (1 if mp.group(2) == 'D' else -1)
            if cur is None:
                continue
            nm = None
            if True:
                ml = re.search(r'^\|\s*\[\[(?:[^|\]]+\|)?([^\]]+)\]\]\s*$', row, re.M)
                nm = ml.group(1) if ml else None
            pty = None
            mpty = re.search(r'[Pp]arty shading/(?:Text/)?(Republican|Democratic)|\|\s*(Republican|Democratic)\s*$', row, re.M)
            if mpty:
                pty = (mpty.group(1) or mpty.group(2))[0]
            stat = ' '.join(l for l in row.split('\n') if re.search(r'Incumbent|retired|re-elected|New member|lost', l) and not l.lstrip().startswith('*'))
            if nm and pty:
                cur['incs'].append({'name': nm, 'party': pty, 'status': stat})
            for cm in re.finditer(r'^\*\s*\{\{[Pp]arty stripe\|([^}]*)\}\}(.*?)(\d+(?:\.\d+)?)\s*%', row, re.M):
                ps, rest, pct = cm.group(1).lower(), cm.group(2), float(cm.group(3))
                p = 'D' if ('democratic' in ps or 'farmer' in ps) else 'R' if ps.startswith('republican') else 'O'
                cn = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', rest)
                cn = re.sub(r"\{\{[^}]*\}\}|'''|\([^)]*\)", '', cn).strip()
                cur['cands'].append({'name': cn, 'party': p, 'pct': pct})
        for r in recs.values():
            d = max([c['pct'] for c in r['cands'] if c['party'] == 'D'], default=None)
            rp = max([c['pct'] for c in r['cands'] if c['party'] == 'R'], default=None)
            r['margin'] = (d - rp) if (d is not None and rp is not None) else None
            r['contested'] = r['margin'] is not None
            r['inc_running'] = 0
            cn = [nz(c['name']) for c in r['cands']]
            for inc in r['incs']:
                last = nz(inc['name']).split()[-1]
                st_ = inc['status'].lower()
                ran = bool(re.search(r're-elected|lost re-election|incumbent lost\.|defeated', st_)) and not re.search(r'renomination|primary|runoff', st_)
                if any(c.split() and c.split()[-1] == last for c in cn) or ran:
                    r['inc_running'] += 1 if inc['party'] == 'D' else -1 if inc['party'] == 'R' else 0
            r['inc_running'] = max(-1, min(1, r['inc_running']))
            out.append(r)
    return out

# ---------------------------------------------------------------- ratings
# Rating -> implied margin (D positive): Tossup 0, Tilt 2, Lean 5, Likely 10, Safe/Solid 18
RSCORE = {'tossup': 0, 'tilt': 2, 'lean': 5, 'likely': 10, 'safe': 18, 'solid': 18}
def rating_margin(txt):
    m = re.search(r'\{\{USRaceRating\|([A-Za-z]+)\|?([A-Z]?)', txt)
    if not m: return None
    k = m.group(1).lower(); p = m.group(2)
    if k not in RSCORE: return None
    v = RSCORE[k]
    return 0.0 if k == 'tossup' else (-v if p == 'R' else v)

def parse_house_ratings(path):
    """Latest published ratings table for competitive House seats -> {district: [implied margins]}."""
    t = Path(path).read_text()
    t = t[t.index('===Latest published ratings'):t.index('==Party listings==')]
    out = {}
    for row in re.split(r'\n\|-[^\n]*', t):
        mu = re.search(r'^!\{\{ushr\|([A-Z]{2})\|([^|}]+)\|X\}\}', row.strip(), re.M)
        if not mu: continue
        n = 'AL' if mu.group(2).upper() in ('AL', 'AT-LARGE') else mu.group(2)
        vals = [rating_margin(l) for l in row.split('\n') if 'USRaceRating' in l]
        vals = [v for v in vals if v is not None]
        if vals: out[f'{mu.group(1)}-{n}'] = vals
    return out

def parse_senate_ratings(path):
    """Senate ratings table -> {'State' or 'State special': {ratings: [implied margins], pvi}}."""
    t = Path(path).read_text()
    i = t.index('== Predictions ==')
    t = t[i:t.index('\n|}', i)]
    out = {}
    for row in re.split(r'\n\|-[^\n]*', t):
        ms = re.search(r'^!\s*\[\[2026 United States Senate (special )?election in ([^|\]]+)\|', row.strip(), re.M)
        if not ms: continue
        pvi = re.search(r'[Ss]hading PVI\|(EVEN|([RD])\|([\d.]+))', row)
        pv = None if not pvi else (0.0 if pvi.group(1) == 'EVEN' else float(pvi.group(3)) * (1 if pvi.group(2) == 'D' else -1))
        vals = []
        for l in row.split('\n'):
            if 'USRaceRating' in l:
                m = re.search(r'\{\{USRaceRating\|([A-Za-z]+)\|?([A-Z]?)', l)
                k = m.group(1).lower(); p = m.group(2)
                if k in RSCORE:
                    v = RSCORE[k]; vals.append(0.0 if k == 'tossup' else (-v if p == 'R' else v))
        key = ms.group(2) + (' special' if ms.group(1) else '')
        out[key] = {'ratings': vals, 'pvi': pv}
    return out

