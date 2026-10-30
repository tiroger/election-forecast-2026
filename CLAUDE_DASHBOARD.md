# Refreshing the Claude dashboard

The Claude dashboard ("2026 Senate & House forecast by state", slug `9e590051-0d42-4e5c-913d-39ccbc0db98d`) reads the same
JSON files the standalone site does, as attached files. It cannot fetch from the internet itself, so a Claude session has to
upload the new files after each run. A Claude scheduled task can do that every morning.

## Scheduled task prompt (paste into a scheduled task, replacing <REPO>)

> Refresh the 2026 election forecast dashboard.
> 1. Clone or pull https://github.com/<REPO> into the working directory, `pip install -r requirements.txt`, then run `make daily`.
>    If it fails, stop and report the error.
> 2. Run `python scripts/dashboard_manifest.py`. For each entry in `datasets`, upload the file to the dashboard (slug in the
>    manifest) with upload_asset, then update that dataset document's `source` (`kind: file`, the new `url`, `name`) and
>    `updated` (`at` = now, `by` = "forecast pipeline (make daily)"). Read each document first for its version.
> 3. If `page/index.html` changed since the last run, set `files/index.html` `text` to its contents.
> 4. Commit and push `data/` and `site/` back to the repo.
> 5. Report the Senate and House control odds from `site/data/chamber_summary.json` and how they moved since yesterday
>    (`site/data/history.json`).

## Doing it by hand

Ask Claude: "run `make daily` in the forecast repo and refresh the dashboard". Same steps.
