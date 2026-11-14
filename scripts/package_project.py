"""Архив текущего запуска без .venv, кэшей и PBF."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    manifest = json.loads((ROOT / "results/run_manifest.json").read_text())
    run_id = manifest["run_id"]
    run_folder = ROOT / "runs" / run_id
    for relative, expected in manifest["artifact_hashes"].items():
        assert sha256(run_folder / relative) == expected, f"Артефакт изменён: {relative}"
    for relative, expected in manifest["code_and_config_hashes"].items():
        assert sha256(ROOT / relative) == expected, f"Код изменён после расчёта: {relative}; выполните новый запуск"
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    paths = []
    for directory in ("src", "scripts", "config", "tests", "docs", "reports", "results", "data/processed", f"runs/{run_id}"):
        paths += [p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    for pattern in ("*.md", "*.xlsx", "*.pdf", "requirements.*", "environment.json", "input_inventory.csv"):
        paths += list(ROOT.glob(pattern))
    paths = sorted(set(paths))
    delivery = {"run_id": run_id, "files": {str(p.relative_to(ROOT)): sha256(p) for p in paths},
                "omitted": [".venv", "caches", "old runs", "central-fed-district-261103.osm.pbf"]}
    archive = output / f"droneport_variant_i_{run_id}.zip"
    if archive.exists():
        raise FileExistsError(f"Архив уже существует: {archive}; оставлен без перезаписи")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in paths:
            zipped.write(path, arcname=str(path.relative_to(ROOT)))
        zipped.writestr("delivery_manifest.json", json.dumps(delivery, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
    print(f"Архив: {archive}\nФайлов: {len(paths)}; размер: {archive.stat().st_size / 2**20:.2f} МиБ\nSHA-256: {sha256(archive)}")


if __name__ == "__main__":
    main()
