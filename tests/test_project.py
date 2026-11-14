"""Контрпримеры существенных ограничений и независимые маленькие эталоны."""
from copy import deepcopy
import json

import networkx as nx
import numpy as np
import pandas as pd
import pytest
import yaml

from droneport.ingest import ROOT, components_for_places, normalize, parse_population
from droneport.model import Instance, greedy, solve_strategic_mip
from droneport.scheduling import build_schedule, cp_sat_schedule_check
from droneport.validation import validate


@pytest.fixture
def cfg():
    return yaml.safe_load((ROOT / "config/model.yaml").read_text())


@pytest.fixture
def pair(cfg):
    towns = pd.DataFrame([{"place_id": "a", "name_original": "Клин", "region_code": "50", "lat": 56., "lon": 36., "population": 100000},
                          {"place_id": "b", "name_original": "Лесной", "region_code": "50", "lat": 56., "lon": 36.1, "population": 100000}])
    instance = Instance(towns, cfg)
    plan = instance.empty_plan(); plan[0, 0] = 1
    result = instance.evaluate(plan)
    flights, trips, served = build_schedule(instance, plan, result)
    return instance, plan, flights, trips, served, result["budget"]


def test_valid_physical_and_financial_case(pair, cfg):
    instance, _, f, t, s, b = pair
    result = validate(instance.towns, f, t, s, b, cfg)
    assert result["valid"], result["errors"]
    assert result["completed_trips_3yr"] == 3 * 8 * 10 * 330
    assert cp_sat_schedule_check(f, cfg)["valid"]


@pytest.mark.parametrize("mutation,expected", [("capacity", "capacity"), ("overlap", "aircraft_overlap"),
                                              ("duplicate_trip", "duplicate_trip"), ("double_count_od", "od_double_count_or_missing"),
                                              ("future_budget", "future_budget_spending"), ("charging", "charging_duration"),
                                              ("teleport", "aircraft_teleportation"), ("bad_initial", "initial"),
                                              ("range", "range"), ("demand", "demand_formula")])
def test_rejects_counterexamples(pair, cfg, mutation, expected):
    instance, _, f, t, s, budget = pair
    f, t, s, budget = f.copy(), t.copy(), s.copy(), deepcopy(budget)
    towns = instance.towns.copy()
    if mutation == "capacity":
        f.loc[0, "passengers"] = 11
    elif mutation == "overlap":
        f.loc[1, "departure_min"] = f.loc[0, "departure_min"]
    elif mutation == "duplicate_trip":
        t = pd.concat([t, t.iloc[[0]]], ignore_index=True)
    elif mutation == "double_count_od":
        s.loc[0, "served_daily"] += 1
    elif mutation == "future_budget":
        budget[0]["spend_rub"] = 1100000000
        budget[1]["spend_rub"] = 100000000
        budget[2]["spend_rub"] = 100000000
    elif mutation == "charging":
        f.loc[0, "charge_end_min"] = f.loc[0, "arrival_min"]
    elif mutation == "teleport":
        f.loc[1, "origin_id"] = f.loc[0, "origin_id"]
    elif mutation == "bad_initial":
        towns.loc[0, "name_original"] = "Москва"
    elif mutation == "range":
        towns.loc[1, "lon"] = 46.
    elif mutation == "demand":
        s.loc[0, "demand_daily"] += 100
    result = validate(towns, f, t, s, budget, cfg)
    assert not result["valid"]
    assert expected in {row["code"] for row in result["errors"]}


def test_real_transfer_counts_one_trip(cfg):
    towns = pd.DataFrame([{"place_id": str(i), "name_original": name, "region_code": "50", "lat": 56., "lon": lon, "population": 1000000}
                          for i, (name, lon) in enumerate(zip(["Клин", "Лесной", "Истра"], [34., 36., 38.]))])
    instance = Instance(towns, cfg)
    assert not instance.graph.has_edge(0, 2)
    plan = instance.empty_plan(); plan[0, :] = 1
    route_id = next(i for i, r in enumerate(instance.routes) if r.nodes == (0, 1, 2))
    ev = {"allocations": [{"flows": [(route_id, 1)]} for _ in range(3)], "budget": instance.costs(plan)}
    assert ev["budget"] is not None
    f, t, s = build_schedule(instance, plan, ev)
    result = validate(towns, f, t, s, ev["budget"], cfg)
    assert result["valid"], result["errors"]
    assert result["completed_trips_3yr"] == 990  # Три поездки в трёх типичных сутках, не шесть участков.
    assert f.passengers.sum() == 6
    assert t.transfers.tolist() == [1, 1, 1]
    ids = json.loads(t.iloc[0].flight_ids)
    first = f[f.flight_id == ids[0]].iloc[0]
    f.loc[f.flight_id == ids[1], "departure_min"] = first.arrival_min
    broken = validate(towns, f, t, s, ev["budget"], cfg)
    assert "transfer_time" in {row["code"] for row in broken["errors"]}


def test_mip_known_pair_optimum(pair):
    instance, *_ = pair
    plan, report = solve_strategic_mip(instance, seconds=10)
    # Два аппарата на единственном коридоре — предел двух зарядных мест.
    # Их покупка в первом году допустима, все 16 рейсов/сутки заполнены.
    assert instance.evaluate(plan)["completed"] == 2 * 3 * 8 * 10 * 330
    assert report["relative_gap"] == 0
    assert abs(report["upper_bound_completed"] - 158400) < .001


def test_population_not_municipality(cfg):
    regions = yaml.safe_load((ROOT / "config/variant_i.yaml").read_text())["regions"]
    frame = parse_population(ROOT / "Tom1_tab-5_VPN-2020.xlsx", regions)
    klin = frame[(frame.name_original == "Клин") & (frame.region_code == "50")]
    assert len(klin) == 1
    assert klin.population.iloc[0] == 88511
    assert klin.population.iloc[0] != 148083  # Официальный итог городского округа из строки 3138.
    assert set(frame.region_code) == {"50", "67", "69"}


def test_geographic_sample_and_isolates_preserved():
    full = pd.read_csv(ROOT / "data/processed/towns_all.csv", dtype={"region_code": str})
    selected = pd.read_csv(ROOT / "data/processed/towns_main.csv", dtype={"region_code": str})
    small = selected.head(8)
    assert set(selected.place_id) <= set(full.place_id)
    assert selected.population_source_row.is_unique
    assert len(selected) == 30 and len(small) == 8
    assert set(full.region_code) == {"50", "67", "69"}
    assert full.name_normalized.str[0].isin(list("ЖЗИКЛ")).all()
    components = components_for_places(small, 200)
    assert len(components) == 2
    assert sum(map(len, components)) == 8
    assert full.population.isna().any()  # Пользовательские пропуски сохранены, а не заменены нулями.
    assert normalize("Йошкар-Ола")[0] == "И"
