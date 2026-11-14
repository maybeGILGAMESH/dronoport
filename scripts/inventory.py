"""Инвентаризация документов и сырья; файлы данных читаются потоково."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "droneport_variant_i_one_day_rtx3090_prompt.md": ("Рабочее описание варианта И", "read"),
    "droneport_variant_i_sources_research_roadmap.md": ("Исследовательский обзор", "read"),
    "droneport_variant_i_budget_roadmap.html": ("Обзор и учебный бюджет", "reviewed_key_sections"),
    "droneport_variant_i_budget_roadmap(1).html": ("Побайтовый дубликат бюджетного HTML", "duplicate_verified"),
    "droneport_product_roadmap.html": ("Дополнительный продуктовый обзор", "reviewed_key_sections"),
}
DIRECTORIES = [
    "data/raw/assignment", "data/raw/osm", "data/raw/rosstat", "data/raw/gar",
    "data/raw/geonames", "data/raw/prices", "data/processed", "src", "tests",
    "runs", "results", "reports", ".cache/matplotlib",
]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    for directory in DIRECTORIES:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    inputs = [ROOT / name for name in INPUTS if (ROOT / name).is_file()]
    for pattern in ("*.pdf", "*.xlsx", "*.xls", "*.osm.pbf", "*.zip", "*.7z"):
        inputs += sorted(ROOT.glob(pattern))
    inputs += sorted(p for p in (ROOT / "data/raw").rglob("*")
                     if p.is_file() and not p.name.startswith("."))
    audit_path = ROOT / "reports/input_audit.json"
    audited = {row["path"]: row for row in json.loads(audit_path.read_text())["files"]} if audit_path.exists() else {}
    with (ROOT / "input_inventory.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["filename", "size_bytes", "sha256", "role", "reading_status"])
        writer.writeheader()
        for path in inputs:
            role, status = INPUTS.get(path.name, ("Новый исходный файл; содержание требует проверки", "not_read"))
            checksum = digest(path)
            audit = audited.get(str(path.relative_to(ROOT)))
            if audit and audit["sha256"] == checksum:
                role, status = audit["role"], audit["status"]
            writer.writerow(dict(filename=str(path.relative_to(ROOT)), size_bytes=path.stat().st_size,
                                 sha256=checksum, role=role, reading_status=status))
    pdfs = list((ROOT / "data/raw/assignment").glob("*.pdf")) + list(ROOT.glob("*.pdf"))
    print(f"Инвентарь: {len(inputs)} файлов → input_inventory.csv")
    print("PDF: найден; состояние проверки см. input_inventory.csv" if pdfs else "PDF задания: отсутствует")
    for folder in ("osm", "rosstat", "gar", "geonames"):
        count = sum(p.is_file() and not p.name.startswith(".") for p in (ROOT / "data/raw" / folder).rglob("*"))
        print(f"data/raw/{folder}: {count} файлов (наличие не доказывает полноту)")
    print("Файлы в корне также учтены; рабочие пути указаны в config/local_inputs.yaml.")


if __name__ == "__main__":
    main()
