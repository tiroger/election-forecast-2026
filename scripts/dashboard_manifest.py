"""List what a Claude session must upload to refresh the Claude dashboard after `make daily`."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forecast.site import DATASETS
print(json.dumps(dict(
    dashboard_slug='9e590051-0d42-4e5c-913d-39ccbc0db98d',
    as_of=(ROOT / 'data/raw/LATEST').read_text().strip(),
    datasets=[dict(dataset=f'datasets/{d}', file=str(ROOT / 'site/data' / f'{d}.json')) for d in DATASETS],
    page=dict(document='files/index.html', file=str(ROOT / 'page/index.html')),
), indent=1))
