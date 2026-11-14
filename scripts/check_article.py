"""Check published prose, figures, source hashes and offline rendering independently."""
from pathlib import Path
import argparse, hashlib, json, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pandas as pd
from PIL import Image
from pypdf import PdfReader
from droneport.ingest import ROOT, checksum
from droneport.event_validation import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='reports/article')
    parser.add_argument('--browsers', action='store_true')
    args = parser.parse_args()
    out = Path(args.output).resolve()
    provenance = json.loads((out / 'provenance.json').read_text())
    folder = ROOT / 'runs' / provenance['run_id']
    for name, digest in provenance['source_hashes'].items():
        assert checksum(ROOT / name) == digest, name
    manifest = json.loads((out / 'article_manifest.json').read_text())
    assert checksum(out / 'report.pdf') == manifest['report_sha256']
    assert checksum(out / 'article.md') == manifest['text_sha256']
    for name, digest in manifest['source_files'].items():
        assert checksum(ROOT / name) == digest, name
    towns = pd.read_csv(folder / 'towns_main.csv')
    rows = pd.read_csv(out / 'evidence/variants.csv')
    annual = pd.read_csv(out / 'evidence/annual.csv')
    plans = []
    results = {}
    for row in rows.itertuples():
        path = ROOT / row.result_path
        result = json.loads(path.read_text())
        cfg = json.loads(path.with_name('config.json').read_text())
        check = validate(towns, result, cfg)
        assert check['valid'], check
        assert row.completed_trips == result['completed_trips']
        assert row.cost_rub == sum(b['spend_rub'] for b in result['budget'])
        assert row.ports == sum(y > 0 for y in result['plan']['open_years'])
        assert row.fleet == len(result['plan']['aircraft'])
        for y in annual[annual.variant == row.variant].itertuples():
            assert y.completed_trips == result['annual_completed'][y.year - 1]
            for key, value in result['budget'][y.year - 1].items():
                assert getattr(y, key) == value, (row.variant, key)
        plans.append(dict(variant=row.variant, **check))
        results[row.variant] = result
    # IDs and schedule seeds changed; compare investments and effective bases.
    def investment(plan):
        fleet = sorted((a['year'], tuple(a.get('homes', {}).get(str(y), a['home']) for y in range(a['year'], 4))) for a in plan['aircraft'])
        return plan['open_years'], fleet
    assert investment(results['A']['plan']) == investment(results['B']['plan'])
    c = results['C']
    regional = []
    for region in (50, 67, 69):
        ids = set(towns[towns.region_code == region].place_id)
        ports = sum(0 < y <= 3 and towns.iloc[i].region_code == region for i, y in enumerate(c['plan']['open_years']))
        flights = [f for f in c['flights'] if f['year'] == 3 and (f['origin_id'] in ids or f['destination_id'] in ids)]
        assert ports > 0 and flights and any(f['passengers'] > 0 for f in flights)
        regional.append(dict(region=region, ports=int(ports), daily_flights=len(flights)))
    figures = json.loads((out / 'figure_manifest.json').read_text())
    assert len(figures) == manifest['figures'] == 18
    assert len({f['figure_id'] for f in figures}) == 18
    for f in figures:
        for fmt in ('png', 'pdf', 'svg'):
            assert (out / f[fmt]).is_file()
            if fmt != 'svg':
                assert checksum(out / f[fmt]) == f[fmt + '_sha256']
        im = Image.open(out / f['png']).convert('RGBA')
        for point in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)):
            assert im.getpixel(point) == (255, 255, 255, 255), f['figure_id']
    reader = PdfReader(out / 'report.pdf')
    texts = [p.extract_text() for p in reader.pages]
    assert len(texts) == manifest['pages'] and all(len(t) > 100 for t in texts)
    assert '\u2014' not in ''.join(texts)
    assert '\u2014' not in (out / 'article.md').read_text()
    original = pd.read_csv(folder / 'requirements_matrix.csv')
    pd.testing.assert_frame_equal(original, pd.read_csv(out / 'evidence/source_requirements.csv'))
    assert (original.status == 'partial').sum() == 3
    paper = json.loads((out / 'article.json').read_text())
    table = next(b for b in paper['blocks'] if b.get('title', '').startswith('Таблица B1.'))
    assert len(table['rows']) == len(original)
    assert sum(row[1] == 'частично' for row in table['rows']) == 3
    browser_results = []
    if args.browsers:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            for name, engine, options in [('chromium', p.chromium, {'executable_path': '/usr/bin/google-chrome'}), ('firefox', p.firefox, {})]:
                browser = engine.launch(headless=True, **options)
                context = browser.new_context(offline=True, viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                remote, errors = [], []
                page.on('request', lambda req: remote.append(req.url) if req.url.startswith(('https://', 'http://')) else None)
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto((out / 'report.html').as_uri())
                page.locator('img').evaluate_all("els => els.forEach(e => e.loading = 'eager')")
                page.wait_for_function('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
                assert page.locator('figure').count() == 18
                page.screenshot(path=str(out / (name + '_article.png')))
                for mapname in ('network.html', 'network_cp_ga.html', 'network_regional.html'):
                    page.goto((out / 'maps' / mapname).as_uri())
                    page.wait_for_function('window.mapReady === true')
                    for selector in ('#all', '#y1', '#y2'):
                        page.locator(selector).check()
                    assert page.locator('canvas').count() > 0
                assert not errors and not remote, (errors, remote)
                browser_results.append(dict(browser=name, offline=True, article_figures=18, maps=3, remote_requests=remote, errors=errors))
                browser.close()
    report = dict(valid=True, source_hashes_checked=len(provenance['source_hashes']), plans=plans, regional_service=regional, figures=len(figures), pages=len(texts), em_dashes=0, requirements=len(original), partial_requirements=original[original.status == 'partial'].id.tolist(), browsers=browser_results, report_sha256=checksum(out / 'report.pdf'))
    (out / 'article_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
