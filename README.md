# 2026 Senate & House forecast

A reproducible forecast of every 2026 U.S. Senate and House race. It fetches the latest public polls, ratings and campaign-finance filings, re-runs the model, and rewrites the data files the web page reads, so the page updates whenever the data is refreshed.

```
make install      # dependencies (Python 3.11+)
make all          # first run: fetch everything, run every backtest, forecast, build the page   (~8 min)
make daily        # each day after: fetch today's data, forecast, rebuild the page              (~5 min)
make serve        # view the page at http://localhost:8000
make edit         # open the marimo notebooks
make reports      # run every notebook and save HTML reports to reports/
make test         # re-run a stored day and confirm the numbers are identical
```

## How it fits together

```
fetch ──► data/raw/<date>/            PollCheck JSON (Senate + generic-ballot polls), 53 Wikipedia pages, FEC filings
      ──► data/raw/static/            538 poll archive + pollster grades, 2018–2024 House pages, 2018–2024 FEC (fetched once)

calibrate ──► data/calibration/*.json  backtests that SET the model's numbers (error sizes, fundamentals coefficients)

forecast ──► site/data/*.json          what the page reads (races, chamber odds, seat distributions, polls, backtests, history)
         ──► data/history/<date>/      a full copy of each day's outputs
         ──► data/history/forecast_history.csv   one row per day (the "forecast over time" chart)

site ──► site/index.html               page/index.html + a small loader that reads site/data/*.json
     ──► site/forecast_standalone.html the same page with the data embedded (one file you can email or open from disk)
```

`page/index.html` is the single page source. It is used as-is by the Claude dashboard and wrapped by `forecast/site.py` for the standalone site, so both always show the same thing.

## Notebooks (marimo)

Each notebook runs on its own (`marimo edit notebooks/05_forecast.py`), as a read-only app (`marimo run …`), or as a script (`python notebooks/05_forecast.py`). Every number comes from the `forecast` package, so the notebooks, the daily job and the page can't drift apart.

| Notebook | What it shows | Re-runs |
|---|---|---|
| `01_data.py` | Every source, a fetch button, snapshot picker, parsing checks, all polls | `fetch` |
| `02_poll_averages.py` | Poll-average method, 2010–2022 backtest (incl. the rejected Bayesian joint model), 2026 pollster house effects, generic-ballot trend | `poll_average_backtest`, `hierarchical_backtest` |
| `03_fundamentals.py` | Fundamentals formula, leave-one-year-out tests of fundraising and personal vote, coefficients, 2026 inputs by district | `generic_ballot_history`, `fundamentals_backtest` |
| `04_uncertainty.py` | Maximum-likelihood error layers (national/region/state), calibration of win chances on 2018–2022 | `error_structure`, `house_forecast_backtest` |
| `05_forecast.py` | The forecast for any stored day, what-if settings, race explorer, sensitivity checks | `model.run` |
| `06_publish.py` | The daily job as buttons: fetch → forecast → write the page; forecast history; page preview | `export.write_site`, `site.build` |

## The model in brief

* **Poll average** per race: recency (14-day half-life), √sample, likely-voter preference, FiveThirtyEight pollster grade, per-pollster cap, sponsored polls discounted 2 points and half weight, pollster house effects estimated across all 2026 races (shrunk, centred on nonpartisan pollsters). Backtest RMSE 7.40 vs 7.77 for a simple mean.
* **Fundamentals**: Cook PVI on the 2026 maps, incumbency, generic ballot; House adds the FEC money ratio and the incumbent's personal vote. Leave-one-year-out error 5.71 vs 6.53 without the two new features.
* **Ratings**: average of up to 11 published ratings, converted to an implied margin (light weight).
* **Blend** by precision; **simulate** 40,000 elections with national (t-distributed), regional, state and race errors whose sizes were estimated by maximum likelihood from 2010–2022.
* Win chances on 2018–2022 House races are well calibrated (see notebook 4).
* **Polling-miss scenarios**: the forecast re-run with the polls off by a fixed −3 … +6 points (`site/data/scenarios.json`), the record of past misses
  (2010–2022 from the 538 archive, 2024 from Silver Bulletin; edit `EXTRA_POLL_MISSES` in `config.py` to add cycles), and two sensitivity variants
  that build the polls' historical lean into every simulation. To make a lean the default, set `nat_bias` in `MODEL` (a number, or
  `'history_all'` / `'history_midterm'`).

Settings live in `forecast/config.py` (`MODEL`); calibrated ones are overwritten from `data/calibration/` at run time.

## Running it every day — pick one

1. **GitHub Actions + GitHub Pages** (no machine needed). Push this folder to a GitHub repo, enable Pages with "GitHub Actions" as the source. `.github/workflows/daily.yml` runs at 6:17 am Pacific: `make daily`, `make reports`, commits the day's data, and publishes `site/` (with the notebook reports under `/reports/`).
2. **Your own machine or a server.** `scripts/run_daily.sh` runs the pipeline; add it to cron. Set `FORECAST_S3=s3://bucket/path` to sync the page to S3.
3. **A Claude scheduled task** that refreshes the Claude dashboard. See `CLAUDE_DASHBOARD.md`.

## Reproducing a past day

Every daily snapshot is kept in `data/raw/<date>/`. `python -m forecast.pipeline forecast --date 2026-10-29` re-runs that day; the simulation uses a fixed seed, so results are identical (`make test` checks this).

## Sources

PollCheck (pollcheck.co.uk, compiled from Wikipedia) · Wikipedia 2026 House, House ratings and Senate pages (CC BY-SA) · FiveThirtyEight `pollster-ratings` data (CC BY 4.0) · FEC bulk candidate summaries · Wikipedia 2018–2024 House results. Be polite to Wikipedia: the fetcher pauses between pages and backs off on rate limits; set `FORECAST_UA` to a contact address.
