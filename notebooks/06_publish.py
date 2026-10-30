import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="6 · Publish the page")


@app.cell
def _():
    import marimo as mo
    import sys, json
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import pandas as pd, altair as alt
    from forecast import config as C, fetch as FX, model as M, export as X, site as SITE
    return C, FX, M, SITE, X, alt, json, mo, pd


@app.cell
def _(mo):
    mo.md(r"""
    # 6 · Publish

    This is the daily job in notebook form: **fetch → forecast → write `site/data/*.json` → rebuild `site/index.html`**.
    The page reads only those JSON files, so whenever they are rewritten, the page shows the new forecast.
    The same thing runs headless with `make daily` (or `python -m forecast.pipeline daily`).
    """)
    return


@app.cell
def _(mo):
    fetch_first = mo.ui.checkbox(value=False, label="Fetch fresh data first")
    with_sens = mo.ui.checkbox(value=True, label="Include sensitivity checks (+4 min)")
    go = mo.ui.run_button(label="Run and publish")
    mo.hstack([fetch_first, with_sens, go])
    return fetch_first, go, with_sens


@app.cell
def _(FX, M, SITE, X, fetch_first, go, mo, with_sens):
    result = None
    if go.value:
        with mo.status.spinner(title="Publishing…") as _sp:
            if fetch_first.value:
                _sp.update("Fetching data…"); FX.fetch_daily()
            _day = FX.latest_dir(); _inp = M.load_inputs(_day)
            _sp.update("Running the forecast…"); _F = M.run(_day, inputs=_inp)
            _sens = M.sensitivity(_day, inputs=_inp) if with_sens.value else []
            _sp.update("Writing the page…"); counts = X.write_site(_F, _sens); SITE.build(); SITE.build_inline()
        result = dict(day=_day.name, files=counts)
    mo.md(f"Published `{result}`" if result else "Press **Run and publish** to refresh the page.")
    return (result,)


@app.cell
def _(C, alt, mo, pd, result):
    _p = C.HISTORY / 'forecast_history.csv'
    mo.stop(not _p.exists(), mo.md("No history yet."))
    hist = pd.read_csv(_p)
    _long = hist.melt(id_vars='date', value_vars=['senate_dem_control_pct', 'house_dem_control_pct'], var_name='chamber', value_name='pct')
    _long['chamber'] = _long.chamber.map({'senate_dem_control_pct': 'Senate', 'house_dem_control_pct': 'House'})
    _ch = alt.Chart(_long).mark_line(point=True).encode(x=alt.X('date:T', title=None), y=alt.Y('pct:Q', title='Chance of Democratic control (%)', scale=alt.Scale(domain=[0, 100])),
                                                       color='chamber:N', tooltip=['date', 'chamber', 'pct'])
    mo.vstack([mo.md("### Forecast history"), mo.ui.altair_chart(_ch.properties(height=240, width='container')), mo.ui.table(hist, selection=None)])
    return


@app.cell
def _(C, mo, result):
    _f = C.SITE / 'forecast_standalone.html'
    mo.stop(not _f.exists(), mo.md("Publish once to see the page."))
    mo.vstack([mo.md("### The published page (self-contained preview of `site/index.html`)"),
               mo.iframe(_f.read_text(), height="1100px")])
    return


if __name__ == "__main__":
    app.run()
