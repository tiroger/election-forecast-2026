import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="4 · Uncertainty and calibration")


@app.cell
def _():
    import marimo as mo
    import sys
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import numpy as np, pandas as pd, altair as alt
    from forecast import config as C, calibrate as CAL
    return C, CAL, alt, mo, np, pd


@app.cell
def _(mo):
    mo.md(r"""
    # 4 · Uncertainty and calibration

    Polling misses are not independent: in a bad year every poll leans the same way, and misses cluster by region and state.
    The size of each layer is estimated by **maximum likelihood** from 2010–2022 poll averages and results:

    $$\text{error}_i = \underbrace{\eta_\text{year}}_{\text{national}} + \underbrace{\rho_{\text{year},\text{region}}}_{\text{region}} + \underbrace{\sigma_{\text{year},\text{state}}}_{\text{state}} + \varepsilon_i,\qquad \operatorname{Var}\varepsilon_i = \text{floor}^2 + \frac{\text{indiv}^2}{n_\text{eff}}$$

    with a full covariance matrix per election year. The forecast's simulation draws these same layers (the national layer with
    Student-t tails, 6 d.f.) on top of each race's own uncertainty.
    """)
    return


@app.cell
def _(mo):
    rerun = mo.ui.run_button(label="Re-estimate and re-run the House backtest (≈15 s)")
    rerun
    return (rerun,)


@app.cell
def _(CAL, mo, pd, rerun):
    if rerun.value:
        with mo.status.spinner(title="Estimating error structure and backtesting…"):
            CAL.error_structure(); CAL.house_forecast_backtest()
    es = CAL.load('error_structure'); hf = CAL.load('house_forecast_backtest')
    comp = pd.DataFrame([dict(layer=k, sd_points=round(es[k], 2)) for k in ['national', 'region', 'state', 'floor', 'indiv']])
    mo.vstack([
        mo.md("### Estimated layers (SD, margin points)"), mo.ui.table(comp, selection=None),
        mo.md(f"Check on the same races: z-scores have SD **{es['z_sd']:.2f}** (ideal 1.00); "
              f"**{100*es['cover80']:.0f}%** fall inside the 80% interval and **{100*es['cover95']:.0f}%** inside the 95% interval."),
    ])
    return (hf,)


@app.cell
def _(alt, hf, mo, pd):
    rows = []
    for _label, _name in [('old', 'PVI + incumbency'), ('new', '+ fundraising + personal vote (used)')]:
        for _b in hf[_label]['bins']:
            rows.append(dict(model=_name, predicted=100 * _b['predicted'], observed=100 * _b['observed'], races=_b['races']))
    cal = pd.DataFrame(rows)
    diag = alt.Chart(pd.DataFrame(dict(x=[0, 100], y=[0, 100]))).mark_line(strokeDash=[4, 3], color='gray').encode(x='x', y='y')
    pts = alt.Chart(cal).mark_circle().encode(x=alt.X('predicted:Q', title='Forecast Dem win chance (%)'), y=alt.Y('observed:Q', title='Dems actually won (%)'),
                                              size='races:Q', color='model:N', tooltip=['model', 'predicted', 'observed', 'races'])
    score = pd.DataFrame([dict(model=n, brier=round(hf[k]['brier'], 4), log_loss=round(hf[k]['logloss'], 4), margin_rmse=round(hf[k]['rmse'], 2))
                          for k, n in [('old', 'PVI + incumbency'), ('new', '+ fundraising + personal vote (used)')]])
    seats = pd.DataFrame([dict(model=k, **s) for k in ['old', 'new'] for s in hf[k]['seats']])
    mo.vstack([
        mo.md("### Full House forecast on every contested 2018–2022 race (leave-one-year-out)"),
        mo.ui.altair_chart((diag + pts).properties(height=320, width='container')),
        mo.ui.table(score, selection=None),
        mo.md("Where each year's actual Democratic seat count (contested seats) fell in the forecast's distribution (50 = dead centre):"),
        mo.ui.table(seats, selection=None),
    ])
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What if the polls are wrong?

    The national layer above is estimated as centred on zero. But in 6 of the last 8 cycles the polls overstated Democrats.
    Below: the record, how well "assume the usual lean" would have predicted each cycle from the others, and the forecast
    if the polls miss by a fixed amount (run `make forecast` to refresh; the table is written to `site/data/scenarios.json`).
    """)
    return


@app.cell
def _(C, CAL, alt, mo, pd):
    mh = CAL.load('poll_miss_history')
    misses = pd.DataFrame(mh['rows'])
    bars = alt.Chart(misses).mark_bar().encode(
        x=alt.X('cycle:O', title=None), y=alt.Y('dem_overstatement:Q', title='Polls overstated Democrats by (pts)'),
        color=alt.condition('datum.dem_overstatement > 0', alt.value('#dc2626'), alt.value('#2563eb')), tooltip=['cycle', 'dem_overstatement', 'kind', 'source'])
    _scen_path = C.SITE_DATA / 'scenarios.json'
    scen = pd.read_json(_scen_path) if _scen_path.exists() else pd.DataFrame()
    mo.vstack([
        mo.ui.altair_chart(bars.properties(height=220, width='container')),
        mo.md(f"Mean lean **{mh['mean_all']:+.2f}** pts across all cycles (**{mh['mean_midterm']:+.2f}** in midterms); cycle-to-cycle SD {mh['sd_all']:.2f}. "
              f"Predicting each cycle's miss from the others: RMSE **{mh['loco_rmse_assume_history']:.2f}** if you assume the historical lean vs "
              f"**{mh['loco_rmse_assume_zero']:.2f}** if you assume zero."),
        mo.md("### Forecast if the polls miss by exactly this much"), mo.ui.table(scen, selection=None),
    ])
    return


if __name__ == "__main__":
    app.run()
