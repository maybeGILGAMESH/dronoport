"""Материализация расписания и индивидуальных маршрутов пассажиров."""
from collections import defaultdict
import json
import math

import numpy as np
import pandas as pd


def build_schedule(instance, plan, evaluation, factor=1., max_range=200., failed=-1):
    cfg = instance.cfg
    flights, itineraries, served = [], [], []
    flight_lookup = defaultdict(list)
    active = np.cumsum(plan, axis=0)
    for year in range(3):
        for edge, (a, b, distance) in enumerate(instance.edges):
            if distance > max_range or failed in (a, b):
                continue
            for aircraft in range(int(active[year, edge])):
                for slot in range(cfg["slots_per_day"]):
                    origin, destination = (a, b) if slot % 2 == 0 else (b, a)
                    departure = cfg["day_start_minutes"] + slot * cfg["slot_minutes"]
                    arrival = departure + math.ceil(distance / cfg["flight_speed_kmh"] * 60) + cfg["landing_minutes"]
                    flight = {"year": year + 1, "flight_id": f"y{year+1}_e{edge}_a{aircraft}_s{slot}",
                              "aircraft_id": f"e{edge}_a{aircraft}", "origin_id": instance.towns.iloc[origin].place_id,
                              "destination_id": instance.towns.iloc[destination].place_id,
                              "departure_min": departure, "arrival_min": arrival,
                              "charge_end_min": arrival + cfg["charging_minutes"],
                              "distance_km": distance, "passengers": 0, "slot": slot,
                              "energy_cost_rub": math.ceil(distance * cfg["energy_kwh_per_km"] * cfg["electricity_rub_per_kwh"])}
                    flights.append(flight)
                    flight_lookup[year, edge, slot].append(flight)
        counts = defaultdict(int)
        for route_id, people in evaluation["allocations"][year]["flows"]:
            route = instance.routes[route_id]
            counts[route.origin, route.destination] += people
            for passenger in range(people):
                route_flights = []
                for edge, slot in route.legs:
                    flight = next(f for f in flight_lookup[year, edge, slot] if f["passengers"] < cfg["capacity_per_flight"])
                    flight["passengers"] += 1
                    route_flights.append(flight)
                itineraries.append({"year": year + 1, "trip_id": f"y{year+1}_p{route_id}_{passenger}",
                                    "origin_id": instance.towns.iloc[route.origin].place_id,
                                    "destination_id": instance.towns.iloc[route.destination].place_id,
                                    "flight_ids": json.dumps([f["flight_id"] for f in route_flights]),
                                    "arrival_min": route_flights[-1]["arrival_min"],
                                    "transfers": len(route_flights) - 1,
                                    "annual_weight": cfg["operating_days"]})
        for od_index, (a, b) in enumerate(instance.od):
            demand = math.floor(instance.demand[year, od_index] * factor)
            completed = counts[a, b]
            served.append({"year": year + 1, "origin_id": instance.towns.iloc[a].place_id,
                           "destination_id": instance.towns.iloc[b].place_id, "demand_daily": demand,
                           "served_daily": completed, "unmet_daily": demand - completed,
                           "completed_annual": completed * cfg["operating_days"]})
    for flight in flights:
        flight["empty"] = flight["passengers"] == 0
    flight_columns = ["year", "flight_id", "aircraft_id", "origin_id", "destination_id", "departure_min", "arrival_min",
                      "charge_end_min", "distance_km", "passengers", "slot", "energy_cost_rub", "empty"]
    itinerary_columns = ["year", "trip_id", "origin_id", "destination_id", "flight_ids", "arrival_min", "transfers", "annual_weight"]
    return pd.DataFrame(flights, columns=flight_columns), pd.DataFrame(itineraries, columns=itinerary_columns), pd.DataFrame(served)


def cp_sat_schedule_check(flights, cfg):
    # OR-Tools and highspy ship incompatible libhighs.so builds with the same
    # SONAME. A fresh process keeps native solver libraries from interposing.
    import subprocess
    import sys
    import os
    from pathlib import Path
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+env.get('PYTHONPATH','')
    payload=json.dumps({'flights':flights.to_dict('records'),'config':cfg})
    run=subprocess.run([sys.executable,'-m','droneport.cp_sat_worker'],input=payload,text=True,capture_output=True,env=env,timeout=45)
    if run.returncode:
        raise RuntimeError('Isolated CP-SAT check failed: '+run.stderr[-2000:])
    return json.loads(run.stdout)


def _cp_sat_schedule_check_local(flights, cfg):
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    aircraft, chargers = defaultdict(list), defaultdict(list)
    for row in flights.to_dict("records"):
        aircraft[row["year"], row["aircraft_id"]].append(model.new_fixed_size_interval_var(
            row["departure_min"], row["charge_end_min"] - row["departure_min"], row["flight_id"]))
        chargers[row["year"], row["destination_id"]].append(model.new_fixed_size_interval_var(
            row["arrival_min"], row["charge_end_min"] - row["arrival_min"], "charge_" + row["flight_id"]))
    for intervals in aircraft.values():
        model.add_no_overlap(intervals)
    for intervals in chargers.values():
        model.add_cumulative(intervals, [1] * len(intervals), cfg["chargers_per_port"])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 2
    status = solver.solve(model)
    return {"status": solver.status_name(status), "valid": status in (cp_model.OPTIMAL, cp_model.FEASIBLE),
            "wall_seconds": solver.wall_time, "scope": "fixed schedule resource feasibility; not schedule optimization"}
