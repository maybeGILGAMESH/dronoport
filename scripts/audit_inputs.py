"""Проверка локальных исходников без перемещения и без построения выборки."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
import osmium
from pypdf import PdfReader
import yaml

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    config = yaml.safe_load((ROOT / "config/local_inputs.yaml").read_text())
    variant = yaml.safe_load((ROOT / "config/variant_i.yaml").read_text())
    report = {"checked_at": datetime.now(ZoneInfo("Europe/Moscow")).isoformat(), "files": []}
    output = ROOT / "reports"
    output.mkdir(exist_ok=True)

    pdf = ROOT / config["assignment_pdf"]
    reader = PdfReader(pdf)
    pages = [page.extract_text() or "" for page in reader.pages]
    assert len(pages) == 12, "Изменилось число страниц: нужна повторная сверка задания"
    assert "И Тверская, Смоленская, Московская области" in " ".join(pages[3].split())
    alphabet = list("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЫЭЮЯ")
    index = alphabet.index(variant["variant_letter"])
    letters = [alphabet[(index + shift) % len(alphabet)] for shift in range(-2, 3)]
    assert letters == variant["allowed_initials"] == list("ЖЗИКЛ")
    (output / "assignment_extracted.txt").write_text(
        "\n\n".join(f"СТРАНИЦА {i + 1}\n{text}" for i, text in enumerate(pages)), encoding="utf-8")
    report["files"].append({"path": str(pdf.relative_to(ROOT)), "role": "Первичное задание",
                            "sha256": sha256(pdf), "size_bytes": pdf.stat().st_size,
                            "status": "pdf_text_checked", "pages": len(pages)})
    report["variant"] = {"letter": "И", "letters": letters, "regions": variant["regions"],
                         "pdf_pages": [3, 4], "verified": True}
    region_rows = []
    for path in sorted(ROOT.glob(config["rosstat_workbooks_glob"])):
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = []
        try:
            for sheet in workbook:
                nonempty_rows = 0
                for row_no, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    if any(value is not None for value in row):
                        nonempty_rows += 1
                    if path.name == config["population_workbook"] and row[0] in variant["regions"].values():
                        # Это итоги регионов, НЕ население отдельных населённых пунктов.
                        assert isinstance(row[1], (int, float)) and row[1] >= 0
                        assert row[1] == row[2] + row[3]
                        region_rows.append({"region": row[0], "sheet": sheet.title, "row": row_no,
                                            "region_population_total": row[1]})
                sheets.append({"sheet": sheet.title, "rows": sheet.max_row,
                               "columns": sheet.max_column, "nonempty_rows": nonempty_rows})
        finally:
            workbook.close()
        report["files"].append({"path": str(path.relative_to(ROOT)), "role": "Таблица Росстата",
                                "sha256": sha256(path), "size_bytes": path.stat().st_size,
                                "status": "xlsx_read_all_rows", "sheets": sheets})
    assert {item["region"] for item in region_rows} == set(variant["regions"].values())
    report["population"] = {"workbook": config["population_workbook"], "region_rows": region_rows,
                            "observation_date": config["population_observation_date"],
                            "limitation": "Таблица 5 включает сельские пункты от 3000 жителей и агрегаты муниципалитетов"}
    pbf = ROOT / config["osm_pbf"]
    osm_reader = osmium.io.Reader(str(pbf), osmium.osm.NOTHING)
    try:
        header = osm_reader.header()
        metadata = {key: header.get(key) for key in ("generator", "osmosis_replication_timestamp",
                                                     "osmosis_replication_base_url")}
    finally:
        osm_reader.close()
    report["files"].append({"path": str(pbf.relative_to(ROOT)), "role": "OSM Центрального округа",
                            "sha256": sha256(pbf), "size_bytes": pbf.stat().st_size,
                            "status": "pbf_header_checked", "header": metadata,
                            "limitation": "Заголовок прочитан и SHA-256 вычислен; все объекты PBF ещё не разобраны"})
    report["readiness"] = {"ready_for_ingestion": True, "ready_for_optimization": False,
                           "missing_optional_sources": ["ГАР/ФИАС", "GeoNames"],
                           "remaining": ["Извлечение пунктов и границ трёх регионов",
                                         "Контроль полноты реестра и сопоставление населённых пунктов",
                                         "Обработка отсутствующего населения и фиксация выборки",
                                         "Паспорт спроса и технических/экономических допущений"]}
    (output / "input_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PDF: {len(pages)} страниц; вариант И: {', '.join(letters)}")
    print(f"XLSX: {len(report['files']) - 2} файлов прочитаны полностью; регионы: {len(region_rows)}/3")
    print(f"PBF: {pbf.stat().st_size:,} байт; данные на {metadata['osmosis_replication_timestamp']}")
    print("Готово к подготовке данных; оптимизационная выборка ещё не создана.")
    print("Отчёт: reports/input_audit.json")


if __name__ == "__main__":
    main()
