import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="3 · Fundamentals")


@app.cell
def _():
    import marimo as mo
    import sys
    from pathlib import Path
    ROOT = Path(mo.notebook_dir()).parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import numpy as np, pandas as pd, altair as alt
    from forecast import config as C, calibrate as CAL, model as M, fetch as FX
    return C, CAL, FX, M, alt, mo, np, pd


@app.cell
def _(mo):
    mo.md(
        r"""
        # 3 · Fundamentals

        What each seat would be expected to do with no polls:

        $$\text{margin} = c_0 + 0.85\cdot\text{generic ballot} + \beta_1\,(2\cdot\text{PVI}) + \beta_2\,\text{incumbent} + \beta_3\,\log\frac{1+\$D}{1+\$R} + \beta_4\,\text{personal vote}$$

        * **PVI**: Cook partisan lean on the district's current lines (Dem positive).
        * **Incumbent**: +1 Democrat running, −1 Republican running, 0 open.
        * **Money**: money each nominee raised from others (FEC receipts minus self-funding), log ratio clipped to ±6.
        * **Personal vote**: the incumbent's last result minus what the same model expected, where the lines did not change.
        * Slopes come from 2018–2024 with a separate national level per year; $c_0$ is then set so the generic-ballot *poll average*
          five days out (not the actual result) predicts the national level, which absorbs the polls' typical miss.
        """
    )
    return


@app.cell
def _(mo):
    rerun = mo.ui.run_button(label="Re-fit on 2018–2024 (≈10 s)")
    rerun
    return (rerun,)


@app.cell
def _(CAL, mo, pd, rerun):
    if rerun.value:
        with mo.status.spinner(title="Fitting fundamentals…"):
            CAL.generic_ballot_history(); CAL.fundamentals_backtest()
    fb = CAL.load('fundamentals')
    t = pd.DataFrame([dict(features=r['method'], rmse_mean=r['rmse'], **{str(y): v for y, v in zip(fb['years'], r['by_year'])}) for r in fb['rows']])
    coef = fb['coef']
    mo.vstack([
        mo.md("### Leave-one-year-out error, competitive seats (national level taken as known)"), mo.ui.table(t, selection=None),
        mo.md(f"**Coefficients:** c₀ = {coef['c0']:.2f}, 2·PVI × {coef['slope'][0]:.3f}, incumbent × {coef['slope'][1]:.2f}, "
              f"money × {coef['slope'][2]:.2f}, personal vote × {coef['slope'][3]:.2f}; residual SD {coef['resid_sd']:.2f} points."),
    ])
    return


@app.cell
def _(C, alt, mo, np, pd):
    Fd = pd.read_csv(C.CALIB / 'house_features.csv')
    Fd['resid_no_money'] = 0.0
    for _y in Fd.year.unique():
        _m = Fd.year == _y; _d = Fd[_m]
        _X = np.c_[np.ones(len(_d)), 2 * _d.pvi, _d.inc]; _b, *_ = np.linalg.lstsq(_X, _d.margin, rcond=None)
        Fd.loc[_m, 'resid_no_money'] = _d.margin - _X @ _b
    ch = alt.Chart(Fd).mark_circle(opacity=0.35, size=18).encode(
        x=alt.X('money:Q', title='log money ratio (Dem / Rep)'), y=alt.Y('resid_no_money:Q', title='margin left unexplained by PVI + incumbency'),
        color=alt.Color('year:N'), tooltip=['year', 'id', 'margin', 'money'])
    mo.vstack([mo.md("### Money tracks what partisanship and incumbency miss"), mo.ui.altair_chart(ch.properties(height=300, width='container'))])
    return


@app.cell
def _(FX, M, mo, pd):
    day = FX.latest_dir(); inp = M.load_inputs(day); cfg = M.settings()
    HF = M.HouseFundamentals(inp, cfg)
    rows = []
    for _d in inp['districts']:
        _dc, _rc = M.house_sides(_d); _ri = _d['running_incumbent']
        _inc = (1.0 if _ri['party'] == 'D' else -1.0) if _ri else 0.0
        _money, _md, _mr = HF.money(_d['id'], _dc[0]['name'] if _dc else None, _rc[0]['name'] if _rc else None)
        rows.append(dict(id=_d['id'], pvi=_d['pvi'], incumbent=_inc, dem_raised=round(_md[0]), gop_raised=round(_mr[0]), money=round(_money, 2),
                         personal_vote=round(HF.personal_vote(_d['id'], _inc, _ri['name'] if _ri else None), 1)))
    mo.vstack([mo.md(f"### 2026 inputs by district (snapshot {day.name})"), mo.ui.table(pd.DataFrame(rows), page_size=15, selection=None)])
    return


if __name__ == "__main__":
    app.run()
