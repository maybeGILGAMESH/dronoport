"""Verify every archived byte and optionally rebuild the paper in a fresh directory."""
from pathlib import Path
import argparse, hashlib, json, subprocess, sys, tempfile, zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    archive = Path(args.archive).resolve()
    with archive.open('rb') as f:
        archive_sha = hashlib.file_digest(f, 'sha256').hexdigest()
    expected = archive.with_suffix('.sha256').read_text().split()[0]
    assert archive_sha == expected, 'Archive checksum mismatch'
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('delivery_manifest.json'))
        assert len(z.namelist()) == len(set(z.namelist()))
        assert set(z.namelist()) == set(manifest['files']) | {'delivery_manifest.json'}
        for i, (name, digest) in enumerate(manifest['files'].items()):
            with z.open(name) as f:
                assert hashlib.file_digest(f, 'sha256').hexdigest() == digest, name
            if i % 1500 == 0:
                print('Verified', i, '/', len(manifest['files']), flush=True)
        for record in manifest['originals'].values():
            assert manifest['files'][record['file']] == record['sha256']
        result = dict(valid=True, archive_sha256=archive_sha, bytes=archive.stat().st_size, files=len(manifest['files']), original_archives_preserved=True, per_file_sha256_verified=True, portable_rebuild_verified=False)
        if args.rebuild:
            parent = archive.parent.parent / '.cache'
            parent.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='three_variants_verify_', dir=parent) as temp:
                root = Path(temp).resolve()
                print('Extracting shared project for isolated rebuild', flush=True)
                for name in z.namelist():
                    if name.startswith('variants/'):
                        continue
                    target = (root / name).resolve()
                    assert target.is_relative_to(root), name
                    z.extract(name, root)
                print('Rebuilding article from extracted sources', flush=True)
                if manifest.get('edition') == 'latex':
                    (root / '.tools/tectonic').chmod(0o755)
                    published = root / 'reports/latex'
                    expected_tex = (published / 'report.tex').read_text()
                    expected_md = (published / 'article.md').read_text()
                    if (root/'reports/research_audit/summary.json').exists():
                        expected_tables={p.name:p.read_bytes() for p in (root/'reports/research_audit').glob('*.csv')}
                        subprocess.run(['unshare','-Urn',sys.executable,'scripts/audit_research.py'],cwd=root,check=True)
                        for name,data in expected_tables.items():assert (root/'reports/research_audit'/name).read_bytes()==data,name
                    subprocess.run(['unshare', '-Urn', sys.executable, 'scripts/build_latex_report.py'], cwd=root, check=True)
                    subprocess.run(['unshare', '-Urn', sys.executable, 'scripts/check_latex_report.py', '--browsers'], cwd=root, check=True)
                    assert (published / 'report.tex').read_text() == expected_tex
                    assert (published / 'article.md').read_text() == expected_md
                    result.update(portable_rebuild_verified=True, tex_source_identical=True, article_text_identical=True, offline_network_namespace=True, rebuild_environment='Fresh extraction, bundled Linux x86_64 Tectonic and TeX cache, existing Python environment, unshare -Urn; no downloads or optimization')
                else:
                    subprocess.run([sys.executable, 'scripts/build_article.py', '--run-dir', 'runs/' + manifest['numerical_run'], '--output', 'reports/rebuilt_verification'], cwd=root, check=True)
                    subprocess.run([sys.executable, 'scripts/check_article.py', '--output', 'reports/rebuilt_verification'], cwd=root, check=True)
                    published = root / 'reports/article'
                    rebuilt = root / 'reports/rebuilt_verification'
                    assert (published / 'article.md').read_text() == (rebuilt / 'article.md').read_text()
                    import pandas as pd
                    tables = sorted((published / 'evidence').glob('*.csv'))
                    for table in tables:
                        pd.testing.assert_frame_equal(pd.read_csv(table), pd.read_csv(rebuilt / 'evidence' / table.name))
                    result.update(portable_rebuild_verified=True, rebuilt_tables=len(tables), article_text_identical=True, rebuild_environment='Fresh extraction, existing pinned Python environment; no optimization or raw-source download')
    archive.with_suffix('.verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
