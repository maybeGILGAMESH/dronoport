"""Package the article and three byte-preserved studies without touching numerical runs."""
from pathlib import Path
import argparse, hashlib, json, zipfile

ROOT = Path(__file__).resolve().parents[1]
ORIGINALS = {
    'A_baseline': ('droneport_20261105_181440_v2', 'baf31f65bcb10c118a90a34564670857df0b65428d6a4828029e4bf9fb11e1f3'),
    'B_cp_ga': ('droneport_20261106_142509_cp_ga', 'c018634524f509ad5f4178384ab7aeb8434d8b85838f179318179dc63cc72f92'),
    'C_regional': ('droneport_20261106_154352_regional', '317b7c4fa849cf1763a25a4b6ced36620800573d557f6fdbe3abc1f5e75ecb83'),
}

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--latex', action='store_true')
    args = parser.parse_args()
    target = (ROOT / (args.output or ('artifacts/droneport_three_variants_latex_20261106.zip' if args.latex else 'artifacts/droneport_three_variants_20261106.zip'))).resolve()
    if target.exists():
        raise FileExistsError(f'Existing archive preserved: {target}')
    validation = json.loads((ROOT / ('reports/latex/validation.json' if args.latex else 'reports/article/article_validation.json')).read_text())
    assert validation['valid'] and len(validation['browsers']) == 2
    assert digest(ROOT / 'reports/report.pdf') == validation['pdf_sha256' if args.latex else 'report_sha256']
    if args.latex:
        offline = json.loads((ROOT / 'reports/latex/pipeline_validation.json').read_text())
        assert offline['valid'] and offline['network_namespace'] and offline['network_interfaces'] == ['lo']
    files = {}
    for directory in ('src', 'scripts', 'config', 'tests', 'docs', 'assets', 'data/processed', 'data/processed_v2', 'reports/article', 'runs', 'reports/research_audit', 'reports/historical'):
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files[str(path.relative_to(ROOT))] = path
    for pattern in ('*.md', '*.xlsx', '*.pdf', 'requirements.*', 'environment.json', 'input_inventory.csv', 'pytest.ini'):
        for path in ROOT.glob(pattern):
            files[path.name] = path
    if args.latex:
        for directory in ('reports/latex', 'data/cartography', '.tools/tex-cache'):
            for path in (ROOT / directory).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and not path.name.startswith('warmup'):
                    files[str(path.relative_to(ROOT))] = path
        for name in ('.tools/tectonic', '.tools/tectonic_provenance.json', '.tools/LICENSE_TECTONIC', 'requirements-latex.txt'):
            files[name] = ROOT / name
    for name in ('reports/report.pdf', 'reports/report.md', 'reports/report.html', 'reports/executive_summary.md', 'reports/requirements_matrix.csv', 'results_v2/current_run.txt'):
        files[name] = ROOT / name
    originals = {}
    for variant, (stem, expected) in ORIGINALS.items():
        path = ROOT / 'artifacts' / (stem + '.zip')
        assert digest(path) == expected, variant
        originals[variant] = dict(file=f'variants/{variant}/{path.name}', sha256=expected)
        for suffix in ('.zip', '.sha256.json', '.verification.json'):
            p = path.with_name(stem + suffix)
            files[f'variants/{variant}/{p.name}'] = p
    for path in (ROOT / 'artifacts').glob('droneport_variant_i_20261105_171655*'):
        if path.is_file():
            files[f'variants/supplement_legacy/{path.name}'] = path
    print('Hashing', len(files), 'files', flush=True)
    hashes = {name: digest(path) for name, path in sorted(files.items())}
    manifest = dict(schema='droneport-three-variants-1', edition='latex' if args.latex else 'article', numerical_run='20261106_154352_regional', article='reports/report.pdf', readme='LATEX_README.md' if args.latex else 'COMBINED_README.md', originals=originals, files=hashes, omitted=['.venv', 'temporary caches (offline TeX cache included in LaTeX edition)', 'raw OSM/PBF and GAR/XML', 'none of the seven saved run directories'])
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for i, (name, path) in enumerate(sorted(files.items())):
            z.write(path, name, compress_type=zipfile.ZIP_STORED if path.suffix == '.zip' else zipfile.ZIP_DEFLATED)
            if i % 1000 == 0:
                print('Packed', i, '/', len(files), flush=True)
        z.writestr('delivery_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(target) as z:
        for name, expected in hashes.items():
            with z.open(name) as f:
                assert hashlib.file_digest(f, 'sha256').hexdigest() == expected, name
    sha = digest(target)
    target.with_suffix('.sha256').write_text(f'{sha}  {target.name}\n')
    result = dict(valid=True, archive_sha256=sha, bytes=target.stat().st_size, files=len(files), original_archives_preserved=True, per_file_sha256_verified=True, portable_rebuild_verified=False)
    target.with_suffix('.verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
