import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="2 · Poll averages")


@app.cell
def _():
    import marimo as mo
    import sys, json
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import numpy as np, pandas as pd, altair as alt
    from forecast import config as C, calibrate as CAL, model as M, fetch as FX
    from forecast.pollavg import average
    return C, CAL, FX, M, alt, average, mo, np, pd


@app.cell
def _(mo):
    mo.md(
        r"""
        # 2 · Poll averages

        **Method.** Each poll's weight is the product of: recency (half-life 14 days; doubled when a race has fewer than three polls
        in the last three weeks), √(sample/600) clipped to [0.5, 2], population (likely voters 1.0, registered 0.8, adults 0.6),
        pollster grade from FiveThirtyEight (0.55 + 0.15 × grade), ½ for campaign- or party-sponsored polls, and 1/√(polls by that
        pollster in the race). Sponsored polls are first moved 2 points against their sponsor. Each pollster's *house effect* (its
        typical gap from the other polls of the same races) is estimated across every 2026 race, shrunk toward zero
        (k = 4, cap ±4) and removed; the effects are centred so nonpartisan pollsters average zero.

        **Backtest.** The same code run five days before each 2010–2022 election on FiveThirtyEight's archive of final-three-week polls.
        """
    )
    return


@app.cell
def _(mo):
    rerun = mo.ui.run_button(label="Re-run the poll backtest (≈1 min)")
    rerun
    return (rerun,)


@app.cell
def _(CAL, mo, pd, rerun):
    if rerun.value:
        with mo.status.spinner(title="Backtesting poll averages on 2010–2022…"):
            CAL.poll_average_backtest(); CAL.hierarchical_backtest()
    pa = CAL.load('poll_average_backtest'); hb = CAL.load('hierarchical_backtest')
    bt = pd.DataFrame(pa['rows'])
    if hb:
        bt = pd.concat([bt, pd.DataFrame([dict(method='Full Bayesian joint model, ML hyperparameters (rejected)', rmse=round(hb['ml']['rmse'], 2)),
                                          dict(method='Full Bayesian joint model, best fixed hyperparameters (rejected)', rmse=round(hb['best_fixed']['rmse'], 2))])])
    mo.vstack([mo.md("### Average miss of the final margin (RMSE, points), 2010–2022"), mo.ui.table(bt, selection=None)])
    return


@app.cell
def _(mo):
    mo.md(
        r"""
        The joint Bayesian model (`forecast/hier.py`: race means + pollster, sponsor, population and national-trend effects, solved exactly with
        hyperparameters by marginal likelihood) was tested as an upgrade and **lost**: it weights individual polls by their sampling
        error, which over-trusts large online panels and repeat trackers. The heuristic average with a per-pollster cap is kept.
        """
    )
    return


@app.cell
def _(FX, M, pd):
    day = FX.latest_dir()
    cfg = M.settings()
    inp = M.load_inputs(day)
    asof = pd.Timestamp(inp['day'])
    P = M.collect_polls(inp, asof, cfg)
    house, center, gen, gen_neff, poll_summary = M.poll_model(P, asof, cfg)
    return P, asof, cfg, day, gen, house, inp, poll_summary


@app.cell
def _(P, day, gen, mo):
    mo.hstack([mo.stat(label="Snapshot", value=day.name), mo.stat(label="Polls used", value=len(P)),
               mo.stat(label="Generic ballot (Dem − Rep)", value=f"{gen:+.1f}")])
    return


@app.cell
def _(P, alt, asof, average, cfg, house, mo, pd):
    g = P[P.race == 'US']
    days = pd.date_range(asof - pd.Timedelta(days=120), asof, freq='3D')
    trend = pd.DataFrame([dict(date=d, avg=average(g[g.end <= d], d, half_life=cfg['gen_half_life'], house=house,
                                                    cfg=dict(partisan_shift=0.0, partisan_w=cfg['partisan_weight']))[0]) for d in days])
    pts = alt.Chart(g[g.end >= asof - pd.Timedelta(days=120)]).mark_circle(opacity=0.35).encode(
        x=alt.X('end:T', title=None), y=alt.Y('margin_raw:Q', title='Dem minus Rep, points'), tooltip=['pollster', 'end', 'margin_raw', 'n'])
    line = alt.Chart(trend).mark_line(strokeWidth=2).encode(x='date:T', y='avg:Q', tooltip=[alt.Tooltip('avg:Q', format='.1f')])
    mo.vstack([mo.md("### Generic ballot: polls and the running average"), mo.ui.altair_chart((pts + line).properties(height=280, width='container'))])
    return


@app.cell
def _(P, house, mo, pd):
    he = pd.DataFrame([dict(pollster_key=k, house_effect=round(v, 2), polls=int((P.pkey == k).sum())) for k, v in house.items()])
    he = he.sort_values('house_effect')
    mo.vstack([mo.md("### Pollster house effects in 2026 (positive = leans Democratic)"), mo.ui.table(he, page_size=15, selection=None)])
    return


@app.cell
def _(inp, mo, pd, poll_summary):
    rows = []
    for _r in inp['senate_races']:
        _s = poll_summary(_r['id'])
        if _s: rows.append(dict(race=_r['id'], polls=_s['n'], effective_polls=round(_s['neff'], 1), average=round(_s['avg'], 1), race_sd=round(_s['sd'], 1), last=_s['last']))
    mo.vstack([mo.md("### Senate poll averages (challenger minus Republican)"), mo.ui.table(pd.DataFrame(rows).sort_values('average'), page_size=20, selection=None)])
    return


if __name__ == "__main__":
    app.run()
