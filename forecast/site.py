"""Build site/index.html: the same page source the Claude dashboard uses (page/index.html), wrapped with
a small loader that reads site/data/*.json, plus theme variables and d3. Host the site/ folder anywhere
(GitHub Pages, S3, a local `python -m http.server`)."""
from pathlib import Path
from . import config as C

DATASETS = ['races', 'chamber_summary', 'seat_distribution', 'national', 'polls', 'backtest', 'calibration',
            'error_structure', 'sensitivity', 'history', 'scenarios', 'poll_misses']

SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>2026 Senate &amp; House forecast by state</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<style>
:root {
  --font-anthropic-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --color-fg: #1f1e1c; --color-fg-muted: #6b6862; --color-bg: #ffffff; --color-panel: #faf9f7; --color-border-line: #e6e3de;
  --color-ok: #2f7d4f; --color-warn: #a86b12; --color-bad: #b42318;
  --cds-font-size-caption: 0.8125rem; --cds-font-size-body: 0.9375rem; --cds-font-size-heading: 1.0625rem; --cds-font-size-title: 1.75rem;
  --cds-font-weight-medium: 550;
  --cds-gap-xs: 4px; --cds-gap-sm: 8px; --cds-gap-md: 16px; --cds-gap-lg: 24px; --cds-gap-xl: 36px;
  --cds-pad-xs: 4px; --cds-pad-sm: 8px; --cds-pad-md: 12px; --cds-pad-lg: 18px; --cds-pad-xl: 28px;
  --cds-radius: 8px; --cds-dur-slow: 300ms;
  --cds-chart-grid: #ece9e4; --cds-chart-axis: #c9c5be; --cds-chart-reference: #8a867f; --cds-chart-muted: #c9c5be;
  --cds-surface-popover: #ffffff; --cds-border: #e6e3de; --cds-shadow-popover: 0 4px 16px rgba(0,0,0,.12); --cds-text-secondary: #6b6862;
}
@media (prefers-color-scheme: dark) {
  :root { --color-fg: #ecebe8; --color-fg-muted: #a5a29c; --color-bg: #1c1b1a; --color-panel: #242321; --color-border-line: #383633;
    --cds-chart-grid: #33312e; --cds-chart-axis: #55524d; --cds-chart-reference: #8a867f; --cds-surface-popover: #2a2927; --cds-border: #383633; --cds-text-secondary: #a5a29c; }
}
body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
#dash-root { padding: var(--dash-gutter, 18px); }
</style>
<script>
/* Minimal stand-in for the dashboard runtime: loads data/<id>.json and runs the page's drawings. */
window.dash = (function () {
  const ids = __DATASETS__;
  const store = {}, draws = {}, hooks = [];
  ids.forEach((id) => { store[id] = { status: 'loading', data: [] }; });
  const run = (name) => document.querySelectorAll('[data-draw="' + name + '"]').forEach((el) => {
    try { draws[name](el); } catch (e) { console.error(name, e); }
  });
  const runAll = () => { hooks.forEach((f) => { try { f(); } catch (e) { console.error(e); } }); Object.keys(draws).forEach(run); };
  const api = {
    colors: ['#2563eb', '#b45309', '#059669', '#7c3aed', '#db2777', '#0891b2', '#65a30d', '#dc2626'],
    data: (id) => store[id] || { status: 'missing', data: [] },
    draw: (name, fn) => { if (fn) draws[name] = fn; if (draws[name]) run(name); },
    onData: (fn) => { hooks.push(fn); fn(); },
    setLink: (name) => { try { history.replaceState(null, '', '#' + name); } catch (e) {} },
    params: () => ({}), setParams: () => {}, resetParams: () => {}, refresh: () => {}, calc: () => {}, loader: () => {},
  };
  const embedded = window.__FORECAST_DATA__;
  if (embedded) { ids.forEach((id) => { store[id] = embedded[id] ? { status: 'ok', data: embedded[id] } : { status: 'missing', data: [] }; });
    setTimeout(runAll, 0); return api; }
  const v = Date.now();
  Promise.all(ids.map((id) => fetch('data/' + id + '.json?v=' + v).then((r) => r.ok ? r.json() : Promise.reject(r.status))
    .then((d) => { store[id] = { status: 'ok', data: d }; }).catch(() => { store[id] = { status: 'error', data: [] }; })))
    .then(runAll);
  let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(runAll, 150); });
  return api;
})();
</script>
</head>
<body>
<div id="dash-root">
__PAGE__
</div>
</body>
</html>
"""

def build(out: Path = None):
    out = Path(out or C.SITE / 'index.html')
    page = (C.PAGE / 'index.html').read_text()
    page = page.replace('<meta name="dash-one-writer">\n', '')
    html = SHELL.replace('__DATASETS__', repr(DATASETS).replace("'", '"')).replace('__PAGE__', page)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return out


def build_inline(out: Path = None):
    """Single self-contained HTML file with today's data embedded (for previews, email, or opening from disk)."""
    import json
    out = Path(out or C.SITE / 'forecast_standalone.html')
    data = {d: json.loads((C.SITE_DATA / f'{d}.json').read_text()) for d in DATASETS if (C.SITE_DATA / f'{d}.json').exists()}
    page = (C.PAGE / 'index.html').read_text().replace('<meta name="dash-one-writer">\n', '')
    blob = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    html = SHELL.replace('__DATASETS__', repr(DATASETS).replace("'", '"')).replace('__PAGE__', page)
    html = html.replace('<script>\n/* Minimal stand-in', '<script>window.__FORECAST_DATA__ = ' + blob + ';</script>\n<script>\n/* Minimal stand-in', 1)
    out.write_text(html)
    return out
