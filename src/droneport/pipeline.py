"""Сквозной расчёт, эксперименты, независимая проверка и журнал запуска."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import resource
import shutil
import time
from zoneinfo import ZoneInfo

import networkx as nx
import numpy as np
import pandas as pd
import yaml

from .ingest import ROOT, checksum, save_json
from .model import Instance, anneal, greedy, solve_strategic_mip
from .scheduling import build_schedule, cp_sat_schedule_check
from .validation import validate


def timed_call(function, *args, **kwargs):
    if args and isinstance(args[0], Instance):
        args[0].cache.clear()  # Каждый замер алгоритма начинается без готовых распределений.
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return result, round(time.perf_counter() - started, 4)


def search_tree(instance, plans):
    """Конечная игра: план → отказ → один из двух допустимых ответов перевозок."""
    tree, labels = [], []
    unique = {plan.tobytes(): plan for plan in plans}
    for plan in unique.values():
        baseline = instance.evaluate(plan)
        nodes = sorted({node for e in np.flatnonzero(plan.sum(axis=0)) for node in instance.edges[e][:2]})
        failures = []
        for failed in nodes:
            # Ответ 1: отменить исходные пассажирские маршруты через отказавший узел.
            retained = 0
            for allocation in baseline["allocations"]:
                retained += sum(people for route_id, people in allocation["flows"] if failed not in instance.routes[route_id].nodes)
            retained *= instance.cfg["operating_days"]
            # Ответ 2: заново распределить потоки при той же инфраструктуре и флоте.
            rerouted = instance.evaluate(plan, failed=failed)["completed"]
            failures.append([retained, rerouted])
        if failures:
            tree.append(failures)
            labels.append({"plan_index": len(labels), "failed_nodes": nodes})
    def traverse(node, depth, alpha, beta, prune, visits):
        visits[0] += 1
        if not isinstance(node, list):
            return node
        maximizing = depth % 2 == 0
        result = -float("inf") if maximizing else float("inf")
        for child in node:
            value = traverse(child, depth + 1, alpha, beta, prune, visits)
            result = max(result, value) if maximizing else min(result, value)
            if maximizing:
                alpha = max(alpha, result)
            else:
                beta = min(beta, result)
            if prune and alpha >= beta:
                break
        return result
    reports = []
    for prune in (False, True):
        visits = [0]; started = time.perf_counter()
        value = traverse(tree, 0, -float("inf"), float("inf"), prune, visits)
        reports.append({"method": "alpha_beta" if prune else "full_enumeration", "value": value,
                        "visited_nodes": visits[0], "wall_seconds": time.perf_counter() - started})
    assert reports[0]["value"] == reports[1]["value"]
    return {"network_actions": len(tree), "recourse_actions": ["cancel_affected_itineraries", "reoptimize_flows"],
            "results": reports, "leaf_values": tree, "labels": labels,
            "scope": "finite listed network plans; all built-node failures; two fixed response actions"}


def path_comparison(instance):
    records = []
    speed = instance.cfg["flight_speed_kmh"]
    for a, b, data in instance.graph.edges(data=True):
        data["time"] = data["weight"] / speed * 60 + instance.cfg["landing_minutes"] + instance.cfg["charging_minutes"]
    for a, b in instance.od:
        row = {"origin_id": instance.towns.iloc[a].place_id, "destination_id": instance.towns.iloc[b].place_id,
               "reachable": nx.has_path(instance.graph, a, b)}
        if row["reachable"]:
            started = time.perf_counter(); bfs = nx.shortest_path(instance.graph, a, b)
            row["bfs_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            astar = nx.astar_path(instance.graph, a, b,
                                  heuristic=lambda u, v: instance.distances[u, v] / speed * 60, weight="time")
            row["astar_seconds"] = time.perf_counter() - started
            row.update(bfs_hops=len(bfs) - 1, astar_hops=len(astar) - 1,
                       bfs_minutes=nx.path_weight(instance.graph, bfs, "time"),
                       astar_minutes=nx.path_weight(instance.graph, astar, "time"))
            assert row["astar_minutes"] <= row["bfs_minutes"] + 1e-7
        records.append(row)
    return pd.DataFrame(records)


def export_plan(instance, plan, folder, label):
    folder.mkdir(parents=True, exist_ok=True)
    evaluation = instance.evaluate(plan)
    flights, itineraries, served = build_schedule(instance, plan, evaluation)
    check = validate(instance.towns, flights, itineraries, served, evaluation["budget"], instance.cfg)
    check["cp_sat"] = cp_sat_schedule_check(flights, instance.cfg)
    check["valid"] = check["valid"] and check["cp_sat"]["valid"]
    if not check["valid"]:
        save_json(folder / "validation_report.json", check)
        raise ValueError(f"Невалидный план {label}: {check['errors'][:5]}")
    flights.to_csv(folder / "flights_and_schedule.csv", index=False)
    itineraries.to_csv(folder / "passenger_itineraries.csv", index=False)
    served.to_csv(folder / "served_od.csv", index=False)
    pd.DataFrame(evaluation["budget"]).to_csv(folder / "budget_by_year.csv", index=False)
    estimate = []
    port_components = [("Земля и подготовка", 9000000), ("Площадка и покрытие", 32000000),
                       ("Сети и зарядка", 18000000), ("Модуль обслуживания", 14000000),
                       ("Связь и безопасность", 8000000), ("Ввод и местные работы", 9000000)]
    for row in evaluation["budget"]:
        items = [(name, row["new_ports"], price) for name, price in port_components]
        items += [("Аппараты в комплекте", row["new_aircraft"], instance.cfg["aircraft_capex_rub"]),
                  ("OPEX портов", row["active_ports"], instance.cfg["port_opex_rub_per_year"]),
                  ("OPEX аппаратов без энергии", row["active_aircraft"], instance.cfg["aircraft_opex_rub_per_year"]),
                  ("Энергия всех рейсов", 1, row["aircraft_opex_including_energy_rub"] - row["active_aircraft"] * instance.cfg["aircraft_opex_rub_per_year"])]
        for item, quantity, unit_price in items:
            estimate.append({"year": row["year"], "item": item, "quantity": quantity, "unit_price_rub": unit_price,
                             "amount_rub": quantity * unit_price, "price_base_year": 2026, "evidence_status": "assumption"})
        assert sum(i[1] * i[2] for i in items) == row["spend_rub"]
    pd.DataFrame(estimate).to_csv(folder / "cost_estimate.csv", index=False)
    save_json(folder / "validation_report.json", check)
    save_json(folder / "plan.json", {"label": label, "purchase_matrix": plan.tolist(), "completed": evaluation["completed"]})
    purchases = []
    for year in range(3):
        for edge in np.flatnonzero(plan[year]):
            a, b, distance = instance.edges[edge]
            purchases.append({"year": year + 1, "origin_id": instance.towns.iloc[a].place_id,
                              "destination_id": instance.towns.iloc[b].place_id,
                              "origin": instance.towns.iloc[a].name_original, "destination": instance.towns.iloc[b].name_original,
                              "new_aircraft": int(plan[year, edge]), "distance_km": distance})
    pd.DataFrame(purchases).to_csv(folder / "investment_fleet_plan.csv", index=False)
    features = []
    for year in range(1, 4):
        annual = flights[flights.year == year]
        port_ids = sorted(set(annual.origin_id) | set(annual.destination_id))
        for pid in port_ids:
            row = instance.towns[instance.towns.place_id == pid].iloc[0]
            features.append({"type": "Feature", "properties": {"kind": "port", "year": year, "place_id": pid, "name": row.name_original},
                             "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]}})
        for edge in np.flatnonzero(plan[:year].sum(axis=0)):
            a, b, distance = instance.edges[edge]
            coords = [[instance.towns.iloc[i].lon, instance.towns.iloc[i].lat] for i in (a, b)]
            features.append({"type": "Feature", "properties": {"kind": "corridor", "year": year, "distance_km": distance,
                                                               "aircraft": int(plan[:year, edge].sum())},
                             "geometry": {"type": "LineString", "coordinates": coords}})
    save_json(folder / "network_by_year.geojson", {"type": "FeatureCollection", "features": features})
    return evaluation, check


def verify_scenarios(instance, plan, label):
    baseline = instance.evaluate(plan)
    base_flights, _, _ = build_schedule(instance, plan, baseline)
    nodes = sorted({n for e in np.flatnonzero(plan.sum(axis=0)) for n in instance.edges[e][:2]})
    specs = [("base", {}), ("demand_070", {"factor": .7}), ("demand_130", {"factor": 1.3}), ("range_160", {"max_range": 160.})]
    specs += [(f"failed_{instance.towns.iloc[n].place_id}", {"failed": n}) for n in nodes]
    results = []
    for scenario, kwargs in specs:
        evaluation = instance.evaluate(plan, **kwargs)
        flights, itineraries, served = build_schedule(instance, plan, evaluation, **kwargs)
        config = {**instance.cfg, "demand_factor": kwargs.get("factor", 1.), "range_km": kwargs.get("max_range", 200.)}
        failed = instance.towns.iloc[kwargs["failed"]].place_id if "failed" in kwargs else None
        report = validate(instance.towns, flights, itineraries, served, baseline["budget"], config,
                          committed_flights=base_flights, failed_port=failed)
        report["cp_sat"] = cp_sat_schedule_check(flights, config)
        assert report["valid"] and report["cp_sat"]["valid"], (scenario, report["errors"])
        results.append({"plan": label, "scenario": scenario, "completed_trips": evaluation["completed"], "validation": report})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.report_only:
        from .reporting import generate
        generate(ROOT / "results")
        return
    cfg = yaml.safe_load((ROOT / "config/model.yaml").read_text())
    towns = pd.read_csv(ROOT / "data/processed/towns_main.csv", dtype={"region_code": str})
    run_id = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y%m%d_%H%M%S")
    folder = ROOT / "runs" / run_id
    folder.mkdir(parents=True)
    started = time.perf_counter()
    print(f"RUN {run_id}: малая задача", flush=True)
    small = Instance(towns.head(8), cfg)
    (small_greedy, _), sg_time = timed_call(greedy, small)
    (small_mip, mip_info), _ = timed_call(solve_strategic_mip, small)
    save_json(folder / "small_mip_report.json", mip_info)
    small_sa = []
    small_seed_rows = []
    for seed in cfg["annealing_seeds"]:
        (plan, info), elapsed = timed_call(anneal, small, small_greedy, seed)
        small_sa.append(plan)
        small_seed_rows.append({**info, "completed_trips": small.evaluate(plan)["completed"], "wall_seconds": elapsed, "nodes": 8})
    pd.DataFrame(small_seed_rows).to_csv(folder / "small_seed_results.csv", index=False)
    small_plans = [small_greedy] + small_sa + ([small_mip] if small_mip is not None else [])
    for i, plan in enumerate(small_plans):
        export_plan(small, plan, folder / "small" / str(i), "small_candidate")
    sequential = small.empty_plan()
    sequential_reports = []
    for year in range(3):
        sequential, info = solve_strategic_mip(small, horizon=year + 1, fixed=sequential[:year], objective_years=[year])
        if sequential is None:
            break
        sequential_reports.append(info)
    save_json(folder / "sequential_solver_reports.json", sequential_reports)
    comparison = [{"instance": "small", "method": "greedy", "completed_trips": small.evaluate(small_greedy)["completed"], "wall_seconds": sg_time},
                  {"instance": "small", "method": "annealing_best", "completed_trips": max(r["completed_trips"] for r in small_seed_rows),
                   "wall_seconds": sum(r["wall_seconds"] for r in small_seed_rows)}]
    if small_mip is not None:
        comparison.append({"instance": "small", "method": "joint_mip", "completed_trips": small.evaluate(small_mip)["completed"], "wall_seconds": mip_info["wall_seconds"]})
    if sequential is not None:
        export_plan(small, sequential, folder / "small_sequential", "sequential_mip")
        comparison.append({"instance": "small", "method": "sequential_mip", "completed_trips": small.evaluate(sequential)["completed"],
                           "wall_seconds": sum(r["wall_seconds"] for r in sequential_reports)})
    save_json(folder / "minimax_results.json", search_tree(small, small_plans))
    print(f"RUN {run_id}: основной экземпляр, greedy", flush=True)
    main_instance = Instance(towns, cfg)
    (baseline, _), baseline_time = timed_call(greedy, main_instance)
    baseline_value = main_instance.evaluate(baseline)["completed"]
    print(f"Greedy 30: {baseline_value:,} поездок; {baseline_time:.2f} с", flush=True)
    export_plan(main_instance, baseline, folder / "baseline", "greedy")
    best, best_value = baseline, baseline_value
    seed_rows = []
    seed_plans = []
    for seed in cfg["annealing_seeds"]:
        (plan, info), elapsed = timed_call(anneal, main_instance, baseline, seed)
        value = main_instance.evaluate(plan)["completed"]
        seed_rows.append({**info, "completed_trips": value, "wall_seconds": elapsed, "nodes": 30})
        seed_plans.append(plan)
        if value > best_value:
            best, best_value = plan, value
        export_plan(main_instance, plan, folder / "seeds" / str(seed), f"annealing_seed_{seed}")
        print(f"SA seed={seed}: {value:,} поездок, изменённых предложений={info['changed_proposals']}", flush=True)
    pd.DataFrame(seed_rows).to_csv(folder / "seed_results.csv", index=False)
    evaluation, check = export_plan(main_instance, best, folder, "best_base")
    comparison += [{"instance": "main", "method": "greedy", "completed_trips": baseline_value, "wall_seconds": baseline_time},
                   {"instance": "main", "method": "annealing_best", "completed_trips": best_value,
                    "wall_seconds": sum(r["wall_seconds"] for r in seed_rows)}]
    pd.DataFrame(comparison).to_csv(folder / "method_comparison.csv", index=False)
    print("Стресс-тесты и поиск робастного плана", flush=True)
    # Выбор исходной точки по реальному худшему сценарию из уже найденных планов.
    candidates = {p.tobytes(): p for p in [baseline, best] + seed_plans}
    robust = max(candidates.values(), key=lambda p: min(r["completed_trips"] for r in main_instance.stress(p)))
    (robust, robust_info), robust_time = timed_call(anneal, main_instance, robust, 1042, iterations=150, robust=True)
    robust_evaluation, _ = export_plan(main_instance, robust, folder / "robust", "robust_heuristic")
    scenarios = [{"plan": label, **row} for label, plan in (("base", best), ("robust", robust)) for row in main_instance.stress(plan)]
    pd.DataFrame(scenarios).to_csv(folder / "scenario_results.csv", index=False)
    save_json(folder / "scenario_validation_report.json", verify_scenarios(main_instance, best, "base") + verify_scenarios(main_instance, robust, "robust"))
    save_json(folder / "robust_search.json", {**robust_info, "wall_seconds": robust_time,
                                              "base_completed": robust_evaluation["completed"]})
    print("Эксперименты по масштабу и бюджету", flush=True)
    experiments = []
    for size in (8, 12, 20, 30):
        instance = small if size == 8 else main_instance if size == 30 else Instance(towns.head(size), cfg)
        (plan, _), elapsed = timed_call(greedy, instance)
        ev, validation = export_plan(instance, plan, folder / "scale" / str(size), "scale_greedy")
        experiments.append({"experiment": "scale", "nodes": size, "tranche_rub": cfg["yearly_tranche_rub"],
                            "completed_trips": ev["completed"], "wall_seconds": elapsed, "valid": validation["valid"],
                            "peak_process_ram_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024})
    for amount in (500000000, 750000000, 1000000000):
        (plan, _), elapsed = timed_call(greedy, main_instance, tranche=amount)
        ev = main_instance.evaluate(plan, tranche=amount)
        flight, itinerary, od = build_schedule(main_instance, plan, ev)
        validation = validate(main_instance.towns, flight, itinerary, od, ev["budget"], {**cfg, "yearly_tranche_rub": amount})
        assert validation["valid"], validation["errors"]
        save_json(folder / f"finance_{amount}.json", {"plan": plan.tolist(), "budget": ev["budget"], "validation": validation})
        experiments.append({"experiment": "finance", "nodes": 30, "tranche_rub": amount, "completed_trips": ev["completed"],
                            "wall_seconds": elapsed, "valid": validation["valid"],
                            "peak_process_ram_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024})
    pd.DataFrame(experiments).to_csv(folder / "benchmarks.csv", index=False)
    path_comparison(main_instance).to_csv(folder / "bfs_astar.csv", index=False)
    demand_rows = [{"year": y + 1, "origin_id": towns.iloc[a].place_id, "destination_id": towns.iloc[b].place_id,
                    "demand_daily": int(main_instance.demand[y, k]), "annual_weight": cfg["operating_days"], "method": "synthetic_gravity"}
                   for y in range(3) for k, (a, b) in enumerate(main_instance.od)]
    pd.DataFrame(demand_rows).to_csv(folder / "od_demand.csv", index=False)
    population = float(towns.population.sum())
    demand_summary = {"population_selected": population, "daily_demand_by_year": main_instance.demand.sum(axis=1).tolist(),
                      "daily_trips_per_resident_year1": float(main_instance.demand[0].sum() / population),
                      "demand_model": cfg["demand"], "observed_forecast": False}
    save_json(folder / "demand_sanity.json", demand_summary)
    for name in ("towns_main.csv", "towns_small.csv", "selection_log.csv", "towns_all.csv", "edges.csv", "graph_components.json", "region_boundaries.geojson"):
        shutil.copy2(ROOT / "data/processed" / name, folder / name)
    shutil.copy2(ROOT / "reports/data_preparation.json", folder / "data_preparation.json")
    shutil.copy2(ROOT / "config/model.yaml", folder / "model.yaml")
    manifest = {"run_id": run_id, "model_version": cfg["model_version"], "completed_trips": evaluation["completed"],
                "annual_completed": evaluation["annual"], "validation": check["valid"],
                "wall_seconds": round(time.perf_counter() - started, 3),
                "peak_process_ram_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "allocation_solves": main_instance.evaluations,
                "timing_cache_policy": "allocation cache cleared before each timed algorithm run",
                "source_hashes": json.loads((ROOT / "reports/data_preparation.json").read_text())["input_hashes"],
                "test_report_sha256": checksum(ROOT / "reports/tests.xml") if (ROOT / "reports/tests.xml").exists() else None,
                "code_and_config_hashes": {str(p.relative_to(ROOT)): checksum(p) for base in ("src", "config", "scripts")
                                            for p in (ROOT / base).rglob("*") if p.is_file() and p.suffix in (".py", ".yaml", ".sh")},
                "artifact_hashes": {str(p.relative_to(folder)): checksum(p) for p in folder.rglob("*") if p.is_file()},
                "limitations": ["Ограниченные фиксированные коридоры и три пути на OD; оптимум исходной неограниченной задачи не заявляется",
                                "Полнота официального реестра не подтверждена; извлечены OSM place-узлы",
                                "Эксперимент с двумя стратегиями пропусков отложен по указанию пользователя",
                                "Цены и спрос — учебные допущения; реальная стоимость и спрос не подтверждены"]}
    save_json(folder / "run_manifest.json", manifest)
    source_records = []
    audited = json.loads((ROOT / "reports/input_audit.json").read_text())
    source_info = {"central-fed-district-261103.osm.pbf": ("osm_central_20261103", "Geofabrik / OpenStreetMap", "https://download.geofabrik.de/russia/central-fed-district.html", "2026-11-03"),
                   "Tom1_tab-5_VPN-2020.xlsx": ("rosstat_vpn2020_t1_5", "Росстат", "https://www.rosstat.gov.ru/vpn/2020/Tom1_Chislennost_i_razmeshchenie_naseleniya", "2021-10-01"),
                   "Задание_Сеть_дронопортов_России.pdf": ("assignment_pdf", "Преподаватель / пользователь", "", "")}
    for entry in audited["files"]:
        if entry["path"] in source_info:
            source_id, publisher, url, observation_date = source_info[entry["path"]]
            source_records.append({"source_id": source_id, "publisher": publisher, "url": url, "local_file": entry["path"],
                                   "sha256": entry["sha256"], "observation_date": observation_date,
                                   "retrieved_at": "provided_by_user; checked " + audited["checked_at"],
                                   "verification_status": entry["status"], "license_or_terms": "См. условия первоисточника; файлы предоставлены пользователем"})
    pd.DataFrame(source_records).to_csv(folder / "sources.csv", index=False)
    pd.DataFrame([{ "parameter": key, "value": cfg[key], "evidence_status": "assumption", "source": "config/model.yaml", "price_base_year": 2026}
                  for key in ("port_capex_rub", "aircraft_capex_rub", "port_opex_rub_per_year", "aircraft_opex_rub_per_year", "electricity_rub_per_kwh", "energy_kwh_per_km")]).to_csv(folder / "price_evidence.csv", index=False)
    manifest["artifact_hashes"] = {str(p.relative_to(folder)): checksum(p) for p in folder.rglob("*")
                                    if p.is_file() and p.name != "run_manifest.json"}
    save_json(folder / "run_manifest.json", manifest)
    current = ROOT / "results"
    current.mkdir(exist_ok=True)
    # Текущие артефакты публикуются локально лишь после всех проверок.
    for path in folder.iterdir():
        if path.is_file():
            shutil.copy2(path, current / path.name)
    shutil.copytree(folder / "robust", current / "robust", dirs_exist_ok=True)
    from .reporting import generate
    generate(current)
    print(f"ГОТОВО {run_id}: {evaluation['completed']:,} поездок; валидатор={check['valid']}; {manifest['wall_seconds']} с", flush=True)


if __name__ == "__main__":
    main()
