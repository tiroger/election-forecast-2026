PY ?= python3
NB := notebooks/01_data.py notebooks/02_poll_averages.py notebooks/03_fundamentals.py notebooks/04_uncertainty.py notebooks/05_forecast.py notebooks/06_publish.py

.PHONY: install daily all fetch calibrate forecast site reports serve edit test

install:            ## install dependencies
	$(PY) -m pip install -r requirements.txt

daily:              ## fetch today's data, re-run the forecast, rebuild the page
	$(PY) -m forecast.pipeline daily

all:                ## first run: fetch, re-run every backtest, forecast, page
	$(PY) -m forecast.pipeline all

fetch calibrate forecast site:
	$(PY) -m forecast.pipeline $@

reports:            ## execute every notebook and save HTML reports to reports/
	mkdir -p reports
	for nb in $(NB); do marimo -y export html $$nb -o reports/$$(basename $$nb .py).html || exit 1; done

serve:              ## view the page at http://localhost:8000
	cd site && $(PY) -m http.server 8000

edit:               ## open the notebooks
	marimo edit notebooks/

test:               ## re-run the forecast on the stored 2026-10-29 snapshot and compare with the stored outputs
	$(PY) scripts/check_reproducible.py
