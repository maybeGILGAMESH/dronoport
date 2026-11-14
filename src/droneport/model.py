"""Трёхлетнее проектирование сети с явными рейсами и пересадками."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import itertools
import math
import os
import time

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

import networkx as nx
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .ingest import GEOD, ROOT


@dataclass(frozen=True)
class Route:
    origin: int
    destination: int
    nodes: tuple
    legs: tuple  # (edge_index, departure_slot)


class Instance:
    def __init__(self, towns, config):
        self.towns = towns.reset_index(drop=True)
        self.cfg = config
        self.n = len(towns)
        self.edges = []
        self.edge_index = {}
        self.distances = np.zeros((self.n, self.n))
        self.graph = nx.Graph()
        self.graph.add_nodes_from(range(self.n))
        for a in range(self.n):
            for b in range(a + 1, self.n):
                x, y = self.towns.iloc[a], self.towns.iloc[b]
                distance = GEOD.inv(x.lon, x.lat, y.lon, y.lat)[2] / 1000
                self.distances[a, b] = self.distances[b, a] = distance
                if distance <= config["range_km"]:
                    edge = len(self.edges)
                    self.edges.append((a, b, distance))
                    self.edge_index[a, b] = edge
                    self.graph.add_edge(a, b, weight=distance)
        self.m = len(self.edges)
        self.od = [(a, b) for a in range(self.n) for b in range(self.n) if a != b]
        self.od_index = {pair: i for i, pair in enumerate(self.od)}
        params = config["demand"]
        self.demand = np.array([[math.floor(params["K"] * float(self.towns.iloc[a].population) ** params["alpha"] *
                                           float(self.towns.iloc[b].population) ** params["beta"] /
                                           (1 + self.distances[a, b] / params["distance_scale_km"]) ** params["gamma"] *
                                           params["yearly_growth"] ** year)
                                 for a, b in self.od] for year in range(3)], dtype=int)
        self.air_opex = np.array([config["aircraft_opex_rub_per_year"] + math.ceil(distance *
                                 config["energy_kwh_per_km"] * config["electricity_rub_per_kwh"]) *
                                 config["slots_per_day"] * config["operating_days"]
                                 for _, _, distance in self.edges], dtype=np.int64)
        self.routes = []
        for origin, destination in self.od:
            if not nx.has_path(self.graph, origin, destination):
                continue
            paths = itertools.islice(nx.shortest_simple_paths(self.graph, origin, destination, weight="weight"),
                                     config["candidate_spatial_paths_per_od"])
            seen = set()
            for path in paths:
                for first_slot in range(config["slots_per_day"]):
                    slot, legs = first_slot, []
                    for a, b in zip(path, path[1:]):
                        parity = int(a > b)
                        if slot % 2 != parity:
                            slot += 1
                        if slot >= config["slots_per_day"]:
                            break
                        legs.append((self.edge_index[min(a, b), max(a, b)], slot))
                        slot += 1
                    if len(legs) == len(path) - 1 and tuple(legs) not in seen:
                        self.routes.append(Route(origin, destination, tuple(path), tuple(legs)))
                        seen.add(tuple(legs))
        self.route_od = np.array([self.od_index[r.origin, r.destination] for r in self.routes])
        self.cache = {}
        self.evaluations = 0

    def empty_plan(self):
        return np.zeros((3, self.m), dtype=int)

    def costs(self, plan, tranche=None):
        """Целые рубли; объекты открываются при первой покупке коридорного аппарата."""
        tranche = self.cfg["yearly_tranche_rub"] if tranche is None else tranche
        active = np.cumsum(plan, axis=0)
        if plan.shape != (3, self.m) or np.any(plan < 0) or np.any(plan != np.floor(plan)):
            return None
        degree = np.zeros((3, self.n), dtype=int)
        for edge, (a, b, _) in enumerate(self.edges):
            degree[:, a] += active[:, edge]
            degree[:, b] += active[:, edge]
        if np.any(degree > self.cfg["chargers_per_port"]):
            return None
        opened = degree > 0
        rows = []
        carry = 0
        for year in range(3):
            new_ports = int(np.sum(opened[year] & ~(opened[year - 1] if year else np.zeros(self.n, bool))))
            port_capex = new_ports * self.cfg["port_capex_rub"]
            fleet_capex = int(plan[year].sum()) * self.cfg["aircraft_capex_rub"]
            port_opex = int(opened[year].sum()) * self.cfg["port_opex_rub_per_year"]
            fleet_opex = int(active[year] @ self.air_opex)
            spent = port_capex + fleet_capex + port_opex + fleet_opex
            available = carry + tranche
            carry = available - spent
            if carry < 0:
                return None
            rows.append({"year": year + 1, "new_ports": new_ports, "active_ports": int(opened[year].sum()),
                         "new_aircraft": int(plan[year].sum()), "active_aircraft": int(active[year].sum()),
                         "port_capex_rub": port_capex, "aircraft_capex_rub": fleet_capex,
                         "port_opex_rub": port_opex, "aircraft_opex_including_energy_rub": fleet_opex,
                         "spend_rub": spent, "available_rub": available, "carry_rub": carry})
        return rows

    def allocate(self, counts, year, factor=1., max_range=200., failed=-1):
        key = (tuple(counts), year, factor, max_range, failed)
        if key in self.cache:
            return self.cache[key]
        self.evaluations += 1
        demand = np.floor(self.demand[year] * factor).astype(int)
        usable = np.array([int(counts[e]) if distance <= max_range and failed not in (a, b) else 0
                           for e, (a, b, distance) in enumerate(self.edges)])
        candidates = [i for i, route in enumerate(self.routes)
                      if demand[self.route_od[i]] > 0 and all(usable[e] > 0 for e, _ in route.legs)]
        if not candidates:
            answer = {"daily_completed": 0, "flows": [], "status": "EMPTY", "gap": 0.}
            self.cache[key] = answer
            return answer
        rr, cc, vv, upper, row_map = [], [], [], [], {}
        def row_index(tag, bound):
            if tag not in row_map:
                row_map[tag] = len(upper)
                upper.append(bound)
            return row_map[tag]
        for col, rid in enumerate(candidates):
            route = self.routes[rid]
            entries = [(('od', int(self.route_od[rid])), int(demand[self.route_od[rid]]))]
            entries += [(('flight', edge, slot), self.cfg["capacity_per_flight"] * int(usable[edge])) for edge, slot in route.legs]
            for tag, bound in entries:
                rr.append(row_index(tag, bound)); cc.append(col); vv.append(1.)
        matrix = coo_matrix((vv, (rr, cc)), shape=(len(upper), len(candidates))).tocsc()
        solved = milp(-np.ones(len(candidates)), integrality=np.ones(len(candidates)),
                      bounds=Bounds(0, demand[self.route_od[candidates]]),
                      constraints=LinearConstraint(matrix, -np.inf, upper),
                      options={"time_limit": self.cfg["allocation_time_limit_seconds"], "mip_rel_gap": 0.})
        if solved.x is None:
            raise RuntimeError(f"Нет допустимого распределения пассажиров: {solved.message}")
        values = np.rint(solved.x).astype(int)
        if np.max(matrix @ values - upper) > 1e-7:
            raise RuntimeError("Округлённое распределение нарушает ограничения")
        answer = {"daily_completed": int(values.sum()), "flows": [(rid, int(value)) for rid, value in zip(candidates, values) if value],
                  "status": "OPTIMAL" if solved.status == 0 else "TIME_LIMIT", "gap": float(solved.mip_gap)}
        self.cache[key] = answer
        return answer

    def evaluate(self, plan, tranche=None, factor=1., max_range=200., failed=-1):
        budget = self.costs(plan, tranche)
        if budget is None:
            return None
        active = np.cumsum(plan, axis=0)
        allocations = [self.allocate(active[y], y, factor, max_range, failed) for y in range(3)]
        return {"completed": sum(a["daily_completed"] for a in allocations) * self.cfg["operating_days"],
                "annual": [a["daily_completed"] * self.cfg["operating_days"] for a in allocations],
                "budget": budget, "allocations": allocations}

    def stress(self, plan, tranche=None):
        active_nodes = sorted({node for e in np.flatnonzero(plan.sum(axis=0)) for node in self.edges[e][:2]})
        scenarios = [("base", {}), ("demand_070", {"factor": .7}), ("demand_130", {"factor": 1.3}),
                     ("range_160", {"max_range": 160.})]
        scenarios += [(f"failed_{self.towns.iloc[node].place_id}", {"failed": node}) for node in active_nodes]
        return [{"scenario": label, "completed_trips": self.evaluate(plan, tranche, **kwargs)["completed"]}
                for label, kwargs in scenarios]


def greedy(instance, tranche=None):
    plan = instance.empty_plan()
    cfg = instance.cfg
    current = instance.evaluate(plan, tranche)
    history = []
    for _ in range(12):
        moves = []
        for year in range(3):
            for edge, (a, b, distance) in enumerate(instance.edges):
                candidate = plan.copy(); candidate[year, edge] += 1
                budget = instance.costs(candidate, tranche)
                if budget is None:
                    continue
                increment = sum(r["spend_rub"] for r in budget) - sum(r["spend_rub"] for r in current["budget"])
                direct = sum(min(40, instance.demand[t, instance.od_index[a, b]]) +
                             min(40, instance.demand[t, instance.od_index[b, a]]) for t in range(year, 3))
                moves.append((direct / increment, year, edge, increment))
        moves.sort(reverse=True)
        best = None
        for _, year, edge, increment in moves[:cfg["greedy_shortlist"]]:
            candidate = plan.copy(); candidate[year, edge] += 1
            result = instance.evaluate(candidate, tranche)
            gain = result["completed"] - current["completed"]
            rank = (gain / increment, gain, -year, -edge)
            if gain > 0 and (best is None or rank > best[0]):
                best = (rank, candidate, result)
        if best is None:
            break
        _, plan, current = best
        history.append(current["completed"])
    return plan, {"method": "greedy_shortlisted_marginal_trips_per_ruble", "history": history}


def anneal(instance, initial, seed, iterations=None, robust=False, tranche=None):
    rng = np.random.default_rng(seed)
    iterations = iterations or instance.cfg["annealing_iterations"]
    score_cache = {}
    def score(plan):
        key = plan.tobytes()
        if key not in score_cache:
            result = instance.evaluate(plan, tranche)
            if result is None:
                score_cache[key] = None
            elif robust:
                score_cache[key] = min(r["completed_trips"] for r in instance.stress(plan, tranche))
            else:
                score_cache[key] = result["completed"]
        return score_cache[key]
    current = initial.copy(); current_score = score(current)
    best, best_score = current.copy(), current_score
    accepted = feasible = changed = 0
    for step in range(iterations):
        candidate = current.copy()
        occupied = np.argwhere(candidate > 0)
        move = int(rng.integers(4))
        if move != 0 and len(occupied):
            year, edge = occupied[int(rng.integers(len(occupied)))]
            candidate[year, edge] -= 1
            if move == 1:
                candidate[int(rng.integers(3)), edge] += 1
            elif move == 2:
                candidate[year, int(rng.integers(instance.m))] += 1
        else:
            candidate[int(rng.integers(3)), int(rng.integers(instance.m))] += 1
        # Восстановление допустимости: убираем покупки начиная с последнего года,
        # пока все годовые бюджеты и ограничения степени портов не соблюдаются.
        repairs = 0
        while instance.costs(candidate, tranche) is None and candidate.sum() and repairs < 12:
            locations = np.argwhere(candidate > 0)
            year, edge = locations[int(rng.integers(len(locations)))]
            candidate[year, edge] -= 1
            repairs += 1
        value = score(candidate)
        if value is None:
            continue
        feasible += 1
        if not np.array_equal(candidate, current):
            changed += 1
        temperature = max(100., max(1, current_score) * .08 * (1 - step / iterations) ** 2)
        if value >= current_score or rng.random() < math.exp((value - current_score) / temperature):
            current, current_score = candidate, value
            accepted += 1
        if value > best_score:
            best, best_score = candidate.copy(), value
    return best, {"seed": seed, "iterations": iterations, "feasible_proposals": feasible,
                  "changed_proposals": changed, "accepted": accepted, "score": best_score, "robust": robust}


def solve_strategic_mip(instance, horizon=3, fixed=None, objective_years=None, seconds=None):
    started = time.perf_counter()
    cfg = instance.cfg
    objective_years = list(range(horizon)) if objective_years is None else objective_years
    c, lb, ub, integer = [], [], [], []
    def var(cost=0., upper=np.inf):
        index = len(c); c.append(cost); lb.append(0.); ub.append(upper); integer.append(1)
        return index
    opened = {(y, n): var(upper=1) for y in range(horizon) for n in range(instance.n)}
    buys = {(y, e): var(upper=cfg["chargers_per_port"]) for y in range(horizon) for e in range(instance.m)}
    if fixed is not None:
        for y in range(len(fixed)):
            for e in range(instance.m):
                lb[buys[y, e]] = ub[buys[y, e]] = int(fixed[y, e])
    flows = {(y, r): var(-cfg["operating_days"] if y in objective_years else 0., int(instance.demand[y, instance.route_od[r]]))
             for y in range(horizon) for r in range(len(instance.routes)) if instance.demand[y, instance.route_od[r]] > 0}
    rr, cc, vv, lower, upper = [], [], [], [], []
    def constraint(terms, high, low=-np.inf):
        row = len(upper)
        for col, coefficient in terms:
            rr.append(row); cc.append(col); vv.append(float(coefficient))
        lower.append(low); upper.append(high)
    incident = defaultdict(list)
    for e, (a, b, _) in enumerate(instance.edges):
        incident[a].append(e); incident[b].append(e)
    for y in range(horizon):
        for n in range(instance.n):
            if y:
                constraint([(opened[y - 1, n], 1), (opened[y, n], -1)], 0)
            terms = [(buys[k, e], 1) for k in range(y + 1) for e in incident[n]]
            terms.append((opened[y, n], -cfg["chargers_per_port"]))
            constraint(terms, 0)
        money = []
        for n in range(instance.n):
            money.append((opened[y, n], cfg["port_capex_rub"] / 1e6))
            money += [(opened[k, n], cfg["port_opex_rub_per_year"] / 1e6) for k in range(y + 1)]
        for k in range(y + 1):
            money += [(buys[k, e], (cfg["aircraft_capex_rub"] + (y - k + 1) * instance.air_opex[e]) / 1e6)
                      for e in range(instance.m)]
        constraint(money, (y + 1) * cfg["yearly_tranche_rub"] / 1e6)
        od_terms, flight_terms = defaultdict(list), defaultdict(list)
        for r, route in enumerate(instance.routes):
            if (y, r) not in flows:
                continue
            col = flows[y, r]
            od_terms[instance.route_od[r]].append((col, 1))
            for leg in route.legs:
                flight_terms[leg].append((col, 1))
        for od, terms in od_terms.items():
            constraint(terms, int(instance.demand[y, od]))
        for (edge, slot), terms in flight_terms.items():
            constraint(terms + [(buys[k, edge], -cfg["capacity_per_flight"]) for k in range(y + 1)], 0)
    matrix = coo_matrix((vv, (rr, cc)), shape=(len(upper), len(c))).tocsc()
    solved = milp(c, integrality=integer, bounds=Bounds(lb, ub), constraints=LinearConstraint(matrix, lower, upper),
                  options={"time_limit": seconds or cfg["small_mip_time_limit_seconds"], "mip_rel_gap": 0.001})
    report = {"status": {0: "OPTIMAL_WITHIN_TOLERANCE", 1: "TIME_LIMIT", 2: "INFEASIBLE"}.get(solved.status, str(solved.status)),
              "message": solved.message, "variables": len(c), "constraints": len(upper),
              "wall_seconds": round(time.perf_counter() - started, 3),
              "time_limit_seconds": seconds or cfg["small_mip_time_limit_seconds"],
              "bound_scope": "timed_shuttles_v1_with_fixed_candidate_paths", "horizon": horizon}
    if solved.x is None:
        report.update(incumbent_completed=None, upper_bound_completed=None, relative_gap=None)
        return None, report
    plan = instance.empty_plan()
    for (y, e), index in buys.items():
        plan[y, e] = int(round(solved.x[index]))
    report.update(incumbent_completed=float(-solved.fun), upper_bound_completed=float(-solved.mip_dual_bound),
                  relative_gap=float(solved.mip_gap))
    # Будущие OPEX могут сделать промежуточный годовой план непригодным для 3 лет;
    # такой план не возвращается как допустимый окончательный результат без проверки.
    return plan, report
