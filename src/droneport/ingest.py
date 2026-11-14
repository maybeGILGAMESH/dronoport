"""OSM → географический реестр → Росстат → фиксированные экземпляры."""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import time

import networkx as nx
import numpy as np
import openpyxl
import osmium
import pandas as pd
from pyproj import Geod
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import polygonize, unary_union
from shapely.prepared import prep
import yaml

ROOT = Path(__file__).resolve().parents[2]
GEOD = Geod(ellps="WGS84")


def normalize(text):
    return re.sub(r"\s+", " ", str(text).strip()).upper().replace("Ё", "Е").replace("Й", "И")


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def boundary_geometry(relation, ways, coords):
    polygons = {}
    for role in ("outer", "inner"):
        segments = []
        for way_id, member_role in relation["ways"]:
            if (member_role or "outer") == role:
                segments.append(LineString([coords[node] for node in ways[way_id]]))
        polygons[role] = unary_union(list(polygonize(segments)))
    result = polygons["outer"].difference(polygons["inner"])
    if result.is_empty or not result.is_valid:
        raise ValueError(f"Невалидная граница {relation['name']}")
    return result


def extract_osm(pbf, regions, policy, out):
    print("OSM: читаю региональные и муниципальные границы", flush=True)
    relations = {}
    for rel in osmium.FileProcessor(str(pbf), entities=osmium.osm.RELATION).with_filter(
            osmium.filter.TagFilter(("boundary", "administrative"))):
        tags = dict(rel.tags)
        if tags.get("admin_level") not in ("4", "6"):
            continue
        relations[rel.id] = {"id": rel.id, "name": tags.get("name:ru", tags.get("name", "")),
                             "level": tags["admin_level"],
                             "ways": [(m.ref, m.role) for m in rel.members if m.type == "w" and m.role in ("", "outer", "inner")],
                             "subareas": [m.ref for m in rel.members if m.type == "r" and m.role == "subarea"]}
    regional = {code: next(r for r in relations.values() if r["level"] == "4" and r["name"] == name)
                for code, name in {**regions, "77": "Москва"}.items()}
    selected = {r["id"]: r for r in regional.values()}
    for region in regional.values():
        for sub in region["subareas"]:
            if sub in relations:
                selected[sub] = relations[sub]
    way_ids = {way for rel in selected.values() for way, _ in rel["ways"]}
    ways = {w.id: [node.ref for node in w.nodes] for w in
            osmium.FileProcessor(str(pbf), entities=osmium.osm.WAY).with_filter(osmium.filter.IdFilter(way_ids))}
    assert set(ways) == way_ids, "В экстракте отсутствуют линии границ"
    node_ids = {node for refs in ways.values() for node in refs}
    coords = {n.id: (n.location.lon, n.location.lat) for n in
              osmium.FileProcessor(str(pbf), entities=osmium.osm.NODE).with_filter(osmium.filter.IdFilter(node_ids))}
    assert set(coords) == node_ids, "В экстракте отсутствуют координаты границ"
    geometries = {rid: boundary_geometry(rel, ways, coords) for rid, rel in selected.items()}
    features = [{"type": "Feature", "properties": {"region_code": code, "name": rel["name"], "osm_id": rel["id"]},
                 "geometry": mapping(geometries[rel["id"]])} for code, rel in regional.items()]
    save_json(out / "region_boundaries.geojson", {"type": "FeatureCollection", "features": features})
    prepared = {code: prep(geometries[rel["id"]]) for code, rel in regional.items()}
    municipalities = {code: [(selected[rid]["name"], prep(geometries[rid])) for rid in rel["subareas"] if rid in selected]
                      for code, rel in regional.items()}
    print("OSM: извлекаю place-узлы; принадлежность региону проверяется полигоном", flush=True)
    rows = []
    for node in osmium.FileProcessor(str(pbf), entities=osmium.osm.NODE).with_filter(osmium.filter.KeyFilter("place")):
        tags = dict(node.tags)
        if tags["place"] not in policy["place_types"] or not node.location.valid():
            continue
        name = tags.get("name:ru", tags.get("name", ""))
        if not name:
            continue
        point = Point(node.location.lon, node.location.lat)
        if prepared["77"].covers(point):
            continue
        matches = [code for code in regions if prepared[code].covers(point)]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError(f"Пункт на неоднозначной границе: {node.id}")
        code = matches[0]
        municipal = [name for name, polygon in municipalities[code] if polygon.covers(point)]
        rows.append({"place_id": f"osm_n{node.id}", "gar_id": "", "name_original": name,
                     "name_normalized": normalize(name), "region_code": code,
                     "municipality": "; ".join(municipal), "settlement_type": tags["place"],
                     "lat": node.location.lat, "lon": node.location.lon,
                     "coordinate_source_id": "osm_central_20261103", "osm_population_unverified": tags.get("population", ""),
                     "osm_population_date": tags.get("population:date", ""),
                     "osm_wikidata": tags.get("wikidata", "")})
    frame = pd.DataFrame(rows).sort_values(["region_code", "name_normalized", "place_id"]).reset_index(drop=True)
    frame.to_parquet(out / "osm_all_places.parquet", index=False)
    return frame


def parse_population(workbook, regions):
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    # Региональные заголовки берём из таблицы 4 того же официального тома.
    headers = openpyxl.load_workbook(workbook.with_name("Tom1_tab-4_VPN-2020.xlsx"), read_only=True, data_only=True)
    region_names = {str(row[0]).strip() for row in headers.active.iter_rows(values_only=True) if row[0]}
    headers.close()
    by_name = {name: code for code, name in regions.items()}
    region, municipality = None, ""
    rows = []
    pattern = re.compile(r"^(г\.|пгт|деревня|село|поселок|посёлок|хутор|станица|станция|местечко)\s+(.+)$", re.I)
    try:
        for row_no, values in enumerate(book.active.iter_rows(values_only=True), 1):
            if not isinstance(values[0], str):
                continue
            raw = values[0].strip()
            if raw in region_names:
                region, municipality = by_name.get(raw), ""
            if region is None or raw in by_name:
                continue
            if re.search(r"городской округ|муниципальный район|муниципальный округ", raw, re.I):
                municipality = raw.split(" - ")[0]
            tail = raw.split(" - ")[-1].strip()
            match = pattern.match(tail)
            if not match or not isinstance(values[1], (int, float)):
                continue
            kind, name = match.groups()
            name = re.sub(r"\s+(рп|дп|кп)$", "", name.strip(), flags=re.I)
            rows.append({"name_original": name, "name_normalized": normalize(name), "region_code": region,
                         "municipality": municipality, "rosstat_type": kind.lower(), "population": int(values[1]),
                         "population_year": 2021, "population_source_id": "rosstat_vpn2020_t1_5",
                         "source_row": row_no, "source_text": raw})
    finally:
        book.close()
    return pd.DataFrame(rows)


def municipality_key(name):
    name = normalize(name)
    for token in ("МУНИЦИПАЛЬНЫИ", "ГОРОДСКОИ", "ОКРУГ", "РАИОН", "ГОРОД", "Г."):
        name = name.replace(token, " ")
    return " ".join(name.split())


def match_population(places, population):
    groups = defaultdict(list)
    for row in population.to_dict("records"):
        groups[row["region_code"], row["name_normalized"]].append(row)
    allnames = places.groupby(["region_code", "name_normalized"]).size().to_dict()
    rows = []
    matches = []
    for row in places.to_dict("records"):
        key = row["region_code"], row["name_normalized"]
        candidates = groups.get(key, [])
        # Город/пгт сопоставляется только с городским place, село/деревня — с сельским.
        candidates = [p for p in candidates if (p["rosstat_type"] in ("г.", "пгт")) == (row["settlement_type"] in ("city", "town"))]
        same_name = places[(places.region_code == row["region_code"]) & (places.name_normalized == row["name_normalized"])] if candidates and allnames[key] > 1 else None
        unique_type = same_name is None or sum((same_name.settlement_type.isin(["city", "town"])) == (row["settlement_type"] in ("city", "town"))) == 1
        if len(candidates) != 1 or not unique_type:
            municipal = municipality_key(row["municipality"])
            candidates = [p for p in candidates if municipal and municipality_key(p["municipality"]) == municipal]
            if same_name is not None:
                unique_type = sum(same_name.municipality.map(municipality_key) == municipal) == 1
        matched = candidates[0] if len(candidates) == 1 and unique_type else None
        row.update(population=matched["population"] if matched else None,
                   population_year=2021 if matched else None,
                   population_source_id="rosstat_vpn2020_t1_5" if matched else "",
                   population_status="observed" if matched else "missing",
                   population_source_row=matched["source_row"] if matched else None,
                   quality_flag="matched" if matched else "population_unfilled")
        rows.append(row)
        matches.append({"place_id": row["place_id"], "status": row["population_status"],
                        "population_source_row": row["population_source_row"], "rule": "region_name_type_unique_or_municipality"})
    return pd.DataFrame(rows), pd.DataFrame(matches)


def select_places(towns, regions, count=30):
    pools = {code: deque(group.to_dict("records")) for code in regions
             for group in [towns[(towns.region_code == code) & towns.population.notna()].sort_values(
                 ["population", "name_normalized", "place_id"], ascending=[False, True, True])]} 
    chosen = []
    while len(chosen) < count and any(pools.values()):
        for code in sorted(regions):
            if pools[code] and len(chosen) < count:
                chosen.append(pools[code].popleft())
    return pd.DataFrame(chosen)


def components_for_places(frame, limit):
    # Проверяем достижимость без сохранения миллионов рёбер полного реестра.
    unseen = set(range(len(frame)))
    components = []
    lon, lat = frame.lon.to_numpy(), frame.lat.to_numpy()
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        component, queue = [start], deque([start])
        while queue and unseen:
            index = queue.popleft()
            rest = np.array(sorted(unseen))
            distances = GEOD.inv(np.full(len(rest), lon[index]), np.full(len(rest), lat[index]), lon[rest], lat[rest])[2] / 1000
            reachable = rest[distances <= limit + 1e-9].tolist()
            unseen.difference_update(reachable)
            queue.extend(reachable)
            component.extend(reachable)
        components.append([frame.iloc[i].place_id for i in component])
    return components


def edges_for_places(frame):
    rows = []
    for i, a in frame.iterrows():
        for j, b in frame.iterrows():
            if i >= j:
                continue
            distance = GEOD.inv(a.lon, a.lat, b.lon, b.lat)[2] / 1000
            rows.append({"origin_id": a.place_id, "destination_id": b.place_id, "distance_km": distance,
                         "allowed_200": distance <= 200, "allowed_160": distance <= 160})
    return pd.DataFrame(rows)


def run():
    started = time.perf_counter()
    inputs = yaml.safe_load((ROOT / "config/local_inputs.yaml").read_text())
    variant = yaml.safe_load((ROOT / "config/variant_i.yaml").read_text())
    policy = yaml.safe_load((ROOT / "config/data_policy.yaml").read_text())
    out = ROOT / "data/processed"
    out.mkdir(exist_ok=True, parents=True)
    pbf = ROOT / inputs["osm_pbf"]
    snapshot = ROOT / "reports/input_audit.json"
    verified = {r["path"]: r["sha256"] for r in json.loads(snapshot.read_text())["files"]}
    assert checksum(pbf) == verified[inputs["osm_pbf"]], "PBF изменился; повторите аудит"
    osm = extract_osm(pbf, variant["regions"], policy, out)
    population = parse_population(ROOT / inputs["population_workbook"], variant["regions"])
    population.to_csv(out / "rosstat_settlements.csv", index=False)
    eligible = osm[osm.name_normalized.str[0].isin(variant["allowed_initials"])].copy()
    towns, crosswalk = match_population(eligible, population)
    towns.to_csv(out / "towns_all.csv", index=False)
    towns.to_parquet(out / "towns_all.parquet", index=False)
    crosswalk.to_csv(out / "population_crosswalk.csv", index=False)
    main = select_places(towns, variant["regions"], variant["target_main_nodes"])
    small = main.head(variant["target_small_nodes"])
    main.to_csv(out / "towns_main.csv", index=False)
    small.to_csv(out / "towns_small.csv", index=False)
    edges = edges_for_places(main)
    edges.to_csv(out / "edges.csv", index=False)
    log = osm[["place_id", "region_code", "name_original"]].copy()
    log["eligible"] = log.place_id.isin(towns.place_id)
    log["selected_main"] = log.place_id.isin(main.place_id)
    log["selected_small"] = log.place_id.isin(small.place_id)
    log["reason"] = np.select([~log.eligible, log.selected_main, log.place_id.isin(towns[towns.population.isna()].place_id)],
                              ["letter_out_of_variant", "stratified_population_rank", "population_missing_preserved_in_registry"],
                              default="outside_fixed_sample_size")
    log["rule_version"] = policy["selection_rule_version"]
    log.to_csv(out / "selection_log.csv", index=False)
    graph_checks = {}
    for name, frame in (("all", towns), ("main", main), ("small", small)):
        graph_checks[name] = {str(limit): components_for_places(frame, limit) for limit in (200, 160)}
    save_json(out / "graph_components.json", graph_checks)
    report = {"scope": policy["registry_scope"], "osm_places_in_regions": len(osm), "eligible_places": len(towns),
              "matched_population": int(towns.population.notna().sum()), "main_nodes": len(main), "small_nodes": len(small),
              "by_region": towns.groupby("region_code").size().to_dict(),
              "main_by_region": main.groupby("region_code").size().to_dict(),
              "components": {name: {limit: len(c) for limit, c in checks.items()} for name, checks in graph_checks.items()},
              "full_geographic_registry_verified": False,
              "limitations": ["Полнота относительно государственного реестра не подтверждена; источник — place-узлы OSM",
                              "Пропуски населения оставлены пустыми по указанию пользователя; в основной выборке только однозначные сопоставления",
                              "Полигональные поселения без place-узла не представлены в этом извлечении"],
              "wall_seconds": round(time.perf_counter() - started, 3),
              "input_hashes": {name: verified[name] for name in (inputs["osm_pbf"], inputs["population_workbook"])}}
    save_json(ROOT / "reports/data_preparation.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in ("input_hashes", "limitations")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    run()
