#!/usr/bin/env bash
# Daily run for cron on your own machine or a server (e.g. EC2):
#   17 6 * * *  /path/to/election-forecast/scripts/run_daily.sh >> /path/to/election-forecast/data/daily.log 2>&1
# Optional: set FORECAST_S3=s3://your-bucket/forecast to publish the page there.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m forecast.pipeline daily
if [ -n "${FORECAST_S3:-}" ]; then
  aws s3 sync site/ "$FORECAST_S3" --delete --cache-control "max-age=300"
fi
