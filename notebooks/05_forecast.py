import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="5 · Forecast")


@app.cell
def _():
    import marimo as mo
    import sys
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import numpy as np, pandas as pd, altair as alt
    from forecast import config as C, model as M, export as X
    return C, M, X, alt, mo, pd


@app.cell
def _(mo):
    mo.md(r"""
    # 5 · Forecast

    For every race the three estimates (poll average, fundamentals, published ratings) are combined by precision weighting,
    then the election is simulated with shared national, regional and state errors. Change a setting below to see how much it
    matters; **publishing always uses the default settings**.
    """)
    return


@app.cell
def _(C, mo):
    snaps = sorted(p.name for p in C.RAW.iterdir() if p.is_dir() and p.name[:2] == '20')
    day_pick = mo.ui.dropdown(options=snaps, value=snaps[-1], label="Snapshot")
    natc = mo.ui.slider(0.6, 1.1, step=0.05, value=C.MODEL['natc'], label="Share of generic-ballot swing per seat", show_value=True)
    nat_sd = mo.ui.slider(1.5, 6.0, step=0.25, value=3.0, label="National polling error SD (pts, default = estimated)", show_value=True)
    use_ratings = mo.ui.checkbox(value=True, label="Use published ratings")
    use_default = mo.ui.checkbox(value=True, label="Use default (calibrated) settings")
    mo.vstack([day_pick, use_default, mo.hstack([natc, nat_sd]), use_ratings])
    return day_pick, nat_sd, natc, use_default, use_ratings


@app.cell
def _(C, M, day_pick, mo, nat_sd, natc, use_default, use_ratings):
    overrides = {} if use_default.value else dict(natc=natc.value, nat_sd=nat_sd.value, use_ratings=use_ratings.value)
    with mo.status.spinner(title="Running 40,000 simulated elections…"):
        inp = M.load_inputs(C.RAW / day_pick.value)
        F = M.run(C.RAW / day_pick.value, overrides, inputs=inp)
    S = F['summary']
    return F, S, inp, overrides


@app.cell
def _(S, mo):
    mo.hstack([
        mo.stat(label="Senate: Dem control", value=f"{100*S['senate']['p_D_control']:.1f}%"),
        mo.stat(label="Senate: GOP control", value=f"{100*S['senate']['p_R_control']:.1f}%"),
        mo.stat(label="Senate: Dem seats (median)", value=f"{S['senate']['D_median']:.0f}", caption=f"80%: {S['senate']['D_p10']:.0f}–{S['senate']['D_p90']:.0f}"),
        mo.stat(label="House: Dem control", value=f"{100*S['house']['p_D_control']:.1f}%"),
        mo.stat(label="House: Dem seats (median)", value=f"{S['house']['D_median']:.0f}", caption=f"80%: {S['house']['D_p10']:.0f}–{S['house']['D_p90']:.0f}"),
        mo.stat(label="Generic ballot", value=f"{S['generic']['avg']:+.1f}"),
    ], wrap=True)
    return


@app.cell
def _(S, alt, mo, pd):
    _rows = [dict(chamber=c, dem_seats=k, prob=100 * v, majority=k >= (51 if c == 'Senate' else 218))
             for c, key in [('Senate', 'senate'), ('House', 'house')] for k, v in S[key]['D_hist'].items()]
    dist = pd.DataFrame(_rows)
    charts = [alt.Chart(dist[dist.chamber == c]).mark_bar().encode(
        x=alt.X('dem_seats:O', title=f'{c}: Democratic seats', axis=alt.Axis(labelOverlap=True)), y=alt.Y('prob:Q', title='% of simulations'),
        color=alt.Color('majority:N', scale=alt.Scale(domain=[True, False], range=['#2563eb', '#dc2626']), legend=None),
        tooltip=['dem_seats', alt.Tooltip('prob:Q', format='.1f')]).properties(height=220, width=360) for c in ['Senate', 'House']]
    mo.hstack([mo.ui.altair_chart(charts[0]), mo.ui.altair_chart(charts[1])], wrap=True)
    return


@app.cell
def _(F, X, mo):
    races = X.race_rows(F)
    state_pick = mo.ui.dropdown(options=['All'] + sorted(races.state.unique()), value='All', label='State')
    chamber_pick = mo.ui.radio(options=['Both', 'Senate', 'House'], value='Both', inline=True)
    competitive = mo.ui.checkbox(value=False, label='Competitive only (5–95%)')
    mo.hstack([state_pick, chamber_pick, competitive])
    return chamber_pick, competitive, races, state_pick


@app.cell
def _(chamber_pick, competitive, mo, races, state_pick):
    _v = races
    if state_pick.value != 'All': _v = _v[_v.state == state_pick.value]
    if chamber_pick.value != 'Both': _v = _v[_v.chamber == chamber_pick.value]
    if competitive.value: _v = _v[(_v.dem_win_pct >= 5) & (_v.dem_win_pct <= 95)]
    cols = ['state', 'seat', 'dem_side', 'gop_side', 'pvi', 'poll_avg_label', 'n_polls', 'fundamentals', 'ratings_avg', 'projection',
            'range_80', 'dem_win_pct', 'rating', 'flip', 'weight_polls_pct', 'weight_fund_pct', 'weight_ratings_pct', 'dem_raised', 'gop_raised', 'personal_vote']
    mo.ui.table(_v[cols], page_size=20, selection=None)
    return


@app.cell
def _(mo):
    sens_btn = mo.ui.run_button(label="Run sensitivity checks (≈4 min)")
    sens_btn
    return (sens_btn,)


@app.cell
def _(M, day_pick, C, inp, mo, pd, sens_btn):
    mo.stop(not sens_btn.value)
    with mo.status.spinner(title="Re-running under other settings…"):
        sens = M.sensitivity(C.RAW / day_pick.value, inputs=inp)
    mo.ui.table(pd.DataFrame(sens), selection=None)
    return


if __name__ == "__main__":
    app.run()
