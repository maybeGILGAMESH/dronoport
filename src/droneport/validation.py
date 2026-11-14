"""Независимая проверка артефактов: не обращается к решателю и его матрицам."""
from collections import Counter, defaultdict
import json
import math

from pyproj import Geod


def validate(towns, flights, itineraries, served, budget, cfg, committed_flights=None, failed_port=None):
    errors = []
    def require(condition, code, detail=""):
        if not condition:
            errors.append({"code": code, "detail": str(detail)})
    points = {row["place_id"]: row for row in towns.to_dict("records")}
    for point in points.values():
        require(str(point["region_code"]) in ("50", "67", "69"), "region", point["place_id"])
        first = point["name_original"].strip().upper().replace("Ё", "Е").replace("Й", "И")[0]
        require(first in "ЖЗИКЛ", "initial", point["place_id"])
    require(not flights.flight_id.duplicated().any(), "duplicate_flight")
    require(not itineraries.trip_id.duplicated().any(), "duplicate_trip")
    fdict = {f["flight_id"]: f for f in flights.to_dict("records")}
    geod = Geod(ellps="WGS84")
    charge_events = defaultdict(list)
    movements = Counter()
    years_ports, years_aircraft = defaultdict(set), defaultdict(set)
    for flight in fdict.values():
        origin, destination = flight["origin_id"], flight["destination_id"]
        require(failed_port is None or failed_port not in (origin, destination), "failed_port_used", flight["flight_id"])
        require(origin in points and destination in points, "unknown_port", flight["flight_id"])
        if origin not in points or destination not in points:
            continue
        a, b = points[origin], points[destination]
        distance = geod.inv(a["lon"], a["lat"], b["lon"], b["lat"])[2] / 1000
        require(distance <= cfg["range_km"] + 1e-7, "range", flight["flight_id"])
        require(abs(distance - flight["distance_km"]) < 1e-5, "distance", flight["flight_id"])
        require(0 <= flight["passengers"] <= cfg["capacity_per_flight"], "capacity", flight["flight_id"])
        require(flight["arrival_min"] - flight["departure_min"] >= distance / cfg["flight_speed_kmh"] * 60 + cfg["landing_minutes"] - 1e-7,
                "flight_duration", flight["flight_id"])
        require(flight["charge_end_min"] - flight["arrival_min"] >= cfg["charging_minutes"], "charging_duration", flight["flight_id"])
        require(flight["departure_min"] >= cfg["day_start_minutes"] and flight["charge_end_min"] <= cfg["day_start_minutes"] + cfg["slot_minutes"] * cfg["slots_per_day"],
                "working_day", flight["flight_id"])
        expected_energy = math.ceil(distance * cfg["energy_kwh_per_km"] * cfg["electricity_rub_per_kwh"])
        require(expected_energy == flight["energy_cost_rub"], "energy_cost", flight["flight_id"])
        y = flight["year"]
        years_ports[y].update([origin, destination]); years_aircraft[y].add(flight["aircraft_id"])
        charge_events[y, destination] += [(flight["arrival_min"], 1), (flight["charge_end_min"], -1)]
        movements[y, origin, (flight["departure_min"] - cfg["day_start_minutes"]) // cfg["slot_minutes"]] += 1
        movements[y, destination, (flight["arrival_min"] - cfg["day_start_minutes"]) // cfg["slot_minutes"]] += 1
    for tag, events in charge_events.items():
        occupied = 0
        for _, delta in sorted(events):
            occupied += delta
            require(occupied <= cfg["chargers_per_port"], "chargers", tag)
    require(all(v <= cfg["max_movements_per_port_per_slot"] for v in movements.values()), "movements")
    for (year, aircraft), frame in flights.groupby(["year", "aircraft_id"]):
        records = frame.sort_values("departure_min").to_dict("records")
        require(len(records) == cfg["slots_per_day"], "aircraft_flight_count", (year, aircraft))
        require(records[0]["origin_id"] == records[-1]["destination_id"], "daily_fleet_cycle", aircraft)
        for previous, following in zip(records, records[1:]):
            require(following["origin_id"] == previous["destination_id"], "aircraft_teleportation", aircraft)
            require(following["departure_min"] >= previous["charge_end_min"], "aircraft_overlap", aircraft)
    passenger_load = Counter()
    completed = Counter()
    annual_completed = 0
    for trip in itineraries.to_dict("records"):
        ids = json.loads(trip["flight_ids"])
        require(bool(ids) and all(fid in fdict for fid in ids), "unknown_itinerary_flight", trip["trip_id"])
        if not ids or any(fid not in fdict for fid in ids):
            continue
        legs = [fdict[fid] for fid in ids]
        require(all(leg["year"] == trip["year"] for leg in legs), "trip_year", trip["trip_id"])
        require(legs[0]["origin_id"] == trip["origin_id"] and legs[-1]["destination_id"] == trip["destination_id"], "od_completion", trip["trip_id"])
        require(trip["arrival_min"] == legs[-1]["arrival_min"], "trip_arrival", trip["trip_id"])
        require(trip["transfers"] == len(legs) - 1, "transfer_count", trip["trip_id"])
        for before, after in zip(legs, legs[1:]):
            require(before["destination_id"] == after["origin_id"], "transfer_location", trip["trip_id"])
            require(after["departure_min"] >= before["arrival_min"] + cfg["minimum_transfer_minutes"], "transfer_time", trip["trip_id"])
        passenger_load.update(ids)
        completed[trip["year"], trip["origin_id"], trip["destination_id"]] += 1
        require(trip["annual_weight"] == cfg["operating_days"], "annual_weight", trip["trip_id"])
        annual_completed += trip["annual_weight"]
    for fid, flight in fdict.items():
        require(passenger_load[fid] == flight["passengers"], "flight_passenger_balance", fid)
    require(not served.duplicated(["year", "origin_id", "destination_id"]).any(), "duplicate_od")
    for row in served.to_dict("records"):
        key = row["year"], row["origin_id"], row["destination_id"]
        require(row["year"] in (1, 2, 3) and row["origin_id"] != row["destination_id"], "od_key", key)
        if row["origin_id"] in points and row["destination_id"] in points:
            a, b = points[row["origin_id"]], points[row["destination_id"]]
            d = geod.inv(a["lon"], a["lat"], b["lon"], b["lat"])[2] / 1000
            p = cfg["demand"]
            expected = math.floor(p["K"] * a["population"] ** p["alpha"] * b["population"] ** p["beta"] /
                                  (1 + d / p["distance_scale_km"]) ** p["gamma"] * p["yearly_growth"] ** (row["year"] - 1))
            expected = math.floor(expected * cfg.get("demand_factor", 1.))
            require(row["demand_daily"] == expected, "demand_formula", key)
        require(0 <= row["served_daily"] <= row["demand_daily"], "demand_capacity", key)
        require(completed[key] == row["served_daily"], "od_double_count_or_missing", key)
        require(row["unmet_daily"] == row["demand_daily"] - row["served_daily"], "unmet_demand", key)
        require(row["completed_annual"] == row["served_daily"] * cfg["operating_days"], "od_annual_weight", key)
    require(annual_completed == int(served.completed_annual.sum()), "annual_total")
    cost_flights = flights if committed_flights is None else committed_flights
    if committed_flights is not None:
        original = {r["flight_id"]: r for r in committed_flights.to_dict("records")}
        for fid, flight in fdict.items():
            require(fid in original, "scenario_new_flight", fid)
            if fid in original:
                require(all(flight[k] == original[fid][k] for k in ("aircraft_id", "origin_id", "destination_id", "departure_min", "arrival_min")),
                        "scenario_changed_fleet_or_timing", fid)
        years_ports, years_aircraft = defaultdict(set), defaultdict(set)
        for f in cost_flights.to_dict("records"):
            years_ports[f["year"]].update([f["origin_id"], f["destination_id"]])
            years_aircraft[f["year"]].add(f["aircraft_id"])
    previous_ports, previous_aircraft, carry = set(), set(), 0
    for row in budget:
        year = row["year"]
        ports, aircraft = years_ports[year], years_aircraft[year]
        require(previous_ports <= ports, "ports_disappear", year)
        require(previous_aircraft <= aircraft, "aircraft_disappear", year)
        new_ports, new_aircraft = len(ports - previous_ports), len(aircraft - previous_aircraft)
        energy = int(cost_flights.loc[cost_flights.year == year, "energy_cost_rub"].sum()) * cfg["operating_days"]
        expected = new_ports * cfg["port_capex_rub"] + new_aircraft * cfg["aircraft_capex_rub"] + \
            len(ports) * cfg["port_opex_rub_per_year"] + len(aircraft) * cfg["aircraft_opex_rub_per_year"] + energy
        require(row["spend_rub"] == expected, "budget_cost_reconciliation", year)
        require(row["active_ports"] == len(ports) and row["active_aircraft"] == len(aircraft), "asset_count", year)
        require(row["new_ports"] == new_ports and row["new_aircraft"] == new_aircraft, "asset_purchase_count", year)
        available = carry + cfg["yearly_tranche_rub"]
        carry = available - row["spend_rub"]
        require(carry >= 0, "future_budget_spending", year)
        require(row["available_rub"] == available and row["carry_rub"] == carry, "budget_balance", year)
        previous_ports, previous_aircraft = ports, aircraft
    return {"valid": not errors, "errors": errors, "completed_trips_3yr": annual_completed,
            "typical_day_trips_all_years": len(itineraries), "flights_all_typical_days": len(flights),
            "transfer_trips_all_typical_days": int((itineraries.transfers > 0).sum()),
            "empty_flights_all_typical_days": int(flights["empty"].sum()),
            "scope": "timed_shuttles_v1; all three yearly typical-day schedules"}
