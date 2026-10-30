import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="1 · Data")


@app.cell
def _():
    import marimo as mo
    import sys, os
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import pandas as pd
    from forecast import config as C, fetch as FX, model as M
    return C, FX, M, mo, pd


@app.cell
def _(mo):
    mo.md(
        r"""
        # 1 · Data

        Every source the forecast uses, as downloaded for one day. Daily sources land in `data/raw/<date>/`;
        historical sources (538's poll archive, past House results, past FEC filings) in `data/raw/static/` and are fetched once.

        | Source | What it gives | Refreshed |
        |---|---|---|
        | PollCheck JSON (compiled from Wikipedia) | Every Senate poll and generic-ballot poll, candidates, past results | daily |
        | Wikipedia 2026 House pages | Nominees, incumbents, 2026 Cook PVI, district polls, ratings | daily |
        | Wikipedia 2026 House ratings & Senate pages | Latest ratings from 10–11 forecasters | daily |
        | FEC bulk `webl26` | Money raised by every House and Senate candidate | daily |
        | FiveThirtyEight `raw_polls.csv`, pollster grades | Final-three-week polls 1998–2022 with results | once |
        | Wikipedia 2018–2024 House pages, FEC `webl18–24` | Past results, PVI, incumbency, fundraising | once |
        """
    )
    return


@app.cell
def _(mo):
    fetch_btn = mo.ui.run_button(label="Fetch today's data")
    fetch_btn
    return (fetch_btn,)


@app.cell
def _(C, FX, fetch_btn, mo):
    fetched = None
    if fetch_btn.value:
        with mo.status.spinner(title="Downloading polls, Wikipedia pages and FEC filings…"):
            fetched = FX.fetch_daily()
    snapshots = sorted(p.name for p in C.RAW.iterdir() if p.is_dir() and p.name[:2] == '20')
    mo.md(f"**Snapshots on disk:** {', '.join(snapshots) or 'none yet: press the button'}" + (f"  \nFetched: `{fetched}`" if fetched else ''))
    return (snapshots,)


@app.cell
def _(mo, snapshots):
    day_pick = mo.ui.dropdown(options=snapshots, value=snapshots[-1] if snapshots else None, label="Snapshot")
    day_pick
    return (day_pick,)


@app.cell
def _(C, M, day_pick, mo):
    mo.stop(day_pick.value is None, mo.md("No snapshot yet."))
    inp = M.load_inputs(C.RAW / day_pick.value)
    return (inp,)


@app.cell
def _(inp, mo):
    n_sen_polls = sum(len(r.get('polls', [])) for r in inp['senate_races'])
    mo.hstack([
        mo.stat(label="Senate races", value=len(inp['senate_races'])),
        mo.stat(label="Senate polls", value=n_sen_polls),
        mo.stat(label="Generic-ballot polls", value=len(inp['generic']['polls'])),
        mo.stat(label="House districts", value=len(inp['districts'])),
        mo.stat(label="District polls", value=len(inp['house_polls'])),
        mo.stat(label="Districts with ratings", value=len(inp['house_ratings'])),
        mo.stat(label="FEC candidate rows", value=len(inp['fec26'])),
    ], wrap=True)
    return


@app.cell
def _(inp, mo, pd):
    sen = pd.DataFrame([dict(state=r['state'], special=r['special'], incumbent=r['incumbent'],
                             candidates='; '.join(f"{c['name']} ({c['party']})" for c in r['candidates']),
                             polls=len(r.get('polls', [])), pres_2024_margin=r['pres_2024_margin']) for r in inp['senate_races']])
    mo.vstack([mo.md("### Senate races"), mo.ui.table(sen, page_size=12)])
    return


@app.cell
def _(inp, mo, pd):
    dist = pd.DataFrame([dict(id=d['id'], pvi=d['pvi'], incumbents=', '.join(i['name'] for i in d['incumbents']),
                              running=(d['running_incumbent'] or {}).get('name'),
                              nominees='; '.join(f"{c['name']} ({c['party']})" for c in d['candidates'])) for d in inp['districts']])
    checks = {
        'districts parsed': len(dist), 'missing PVI': int(dist.pvi.isna().sum()),
        'districts without a D or R nominee': int((~dist.nominees.str.contains(r'\(D\)') | ~dist.nominees.str.contains(r'\(R\)')).sum()),
    }
    mo.vstack([mo.md("### House districts"), mo.md(' · '.join(f'**{k}:** {v}' for k, v in checks.items())), mo.ui.table(dist, page_size=12)])
    return


@app.cell
def _(inp, mo, pd):
    hp = pd.DataFrame([dict(district=p['district'], pollster=p['pollster'], end=p['end'], n=p['n'], pop=p['pop'], sponsor=p['partisan'],
                            results='; '.join(f'{k} {v:g}' for k, v in p['results'].items())) for p in inp['house_polls']])
    mo.vstack([mo.md("### District polls (general-election matchups of the actual nominees)"), mo.ui.table(hp, page_size=12)])
    return


if __name__ == "__main__":
    app.run()
