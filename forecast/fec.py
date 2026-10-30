"""FEC bulk 'House/Senate current campaigns' summaries (webl files)."""
import pandas as pd, numpy as np, unicodedata
from pathlib import Path
COLS = ['cand_id','name','ici','pty_cd','party','receipts','trans_from','disb','trans_to','coh_bop','coh_cop','cand_contrib','cand_loans','other_loans','cand_loan_repay','other_loan_repay','debts','indiv','st','dist','spec','prim','run','gen','gen_pct','other_pol','pty_contrib','cvg_end','indiv_ref','cmte_ref']
def load(path):
    d = pd.read_csv(path, sep='|', header=None, names=COLS, dtype=str, encoding='latin-1')
    for c in ['receipts','indiv','cand_contrib','cand_loans','disb','coh_cop','other_pol','pty_contrib']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0)
    d['office'] = d.cand_id.str[0]
    d['dist'] = d.dist.fillna('00')
    d['did'] = np.where(d.office=='H', d.st + '-' + d.dist.str.lstrip('0').replace('', 'AL'), d.st + '-SEN')
    d['p'] = d.party.map(lambda x: 'D' if x in ('DEM','DFL') else 'R' if x=='REP' else 'O')
    d['raised'] = d.receipts - d.cand_contrib - d.cand_loans   # money raised from others (excludes self-funding)
    d['last'] = d.name.fillna('').map(lambda n: unicodedata.normalize('NFKD', n).encode('ascii','ignore').decode().split(',')[0].strip().lower())
    return d
