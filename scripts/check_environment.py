"""Короткая проверка окружения на искусственных примерах, не решение задания."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
os.environ["MPLCONFIGDIR"] = str(ROOT / ".cache/matplotlib")
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"


def mip_check(folder: Path) -> dict:
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    # Три неделимых предмета: вместимость 7, веса 6/4/3, полезности 10/7/4.
    # Перебор 8 вариантов независимо подтверждает оптимум 11 (предметы 2 и 3).
    result = milp(c=-np.array([10., 7., 4.]), integrality=np.ones(3),
                  bounds=Bounds(0, 1), constraints=LinearConstraint([[6., 4., 3.]], -np.inf, 7),
                  options={"time_limit": 10, "mip_rel_gap": 0})
    assert result.success and result.status == 0, result.message
    assert abs(result.fun + 11) < 1e-8 and np.allclose(result.x, [0, 1, 1])
    impossible = milp(c=[1.], integrality=[1], bounds=Bounds(0, 1),
                      constraints=LinearConstraint([[1.]], 2, np.inf), options={"time_limit": 10})
    assert impossible.status == 2, impossible.message
    return {"solver": "HiGHS через scipy.optimize.milp", "objective": -result.fun,
            "gap": result.mip_gap, "infeasible_case_detected": True}


def schedule_check(folder: Path) -> dict:
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    starts = [model.new_int_var(0, 7 - duration, f"start_{i}") for i, duration in enumerate((3, 4))]
    ends = [model.new_int_var(0, 7, f"end_{i}") for i in range(2)]
    intervals = [model.new_interval_var(starts[i], duration, ends[i], f"job_{i}")
                 for i, duration in enumerate((3, 4))]
    model.add_no_overlap(intervals)
    makespan = model.new_int_var(0, 7, "makespan")
    model.add_max_equality(makespan, ends)
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 42
    status = solver.solve(model)
    assert status == cp_model.OPTIMAL, solver.status_name(status)
    jobs = [(solver.value(starts[i]), solver.value(ends[i])) for i in range(2)]
    assert jobs[0][1] <= jobs[1][0] or jobs[1][1] <= jobs[0][0]
    assert [end - start for start, end in jobs] == [3, 4]
    assert solver.value(makespan) == 7
    return {"solver": "OR-Tools CP-SAT", "status": solver.status_name(status), "jobs": jobs}


def graph_geodesy_check(folder: Path) -> dict:
    import networkx as nx
    from pyproj import Geod
    graph = nx.Graph()
    graph.add_weighted_edges_from([("A", "C", 9), ("A", "B", 2), ("B", "C", 2)])
    assert nx.shortest_path(graph, "A", "C") == ["A", "C"]
    assert nx.astar_path(graph, "A", "C", heuristic=lambda *_: 0, weight="weight") == ["A", "B", "C"]
    distance = Geod(ellps="WGS84").inv(0, 0, 1, 0)[2] / 1000
    assert abs(distance - 111.319490793) < 1e-6
    return {"equatorial_degree_km": distance, "bfs_and_astar": "ok"}


def table_check(folder: Path) -> dict:
    import pandas as pd
    import yaml
    data = pd.DataFrame({"name": ["Клин", "Лобня"], "population": pd.array([1, None], dtype="Int64")})
    data.to_parquet(folder / "test.parquet", index=False)
    pd.testing.assert_frame_equal(data, pd.read_parquet(folder / "test.parquet"))
    data.to_excel(folder / "test.xlsx", index=False)
    restored = pd.read_excel(folder / "test.xlsx")
    assert restored["name"].tolist() == ["Клин", "Лобня"] and pd.isna(restored.population.iloc[1])
    config = yaml.safe_load((ROOT / "config/variant_i.yaml").read_text())
    assert config["variant_letter"] == "И" and set(config["regions"]) == {"50", "67", "69"}
    assert config["allowed_initials"] == list("ЖЗИКЛ")
    return {"parquet": "ok", "xlsx": "ok", "variant_config": "ok", "data": "synthetic_fixture"}


def osm_check(folder: Path) -> dict:
    import osmium
    path = folder / "fixture.osm.pbf"
    with osmium.SimpleWriter(str(path)) as writer:
        writer.add_node(osmium.osm.mutable.Node(id=1, location=(1., 2.), tags={"name": "Тест", "place": "village"}))
    class Reader(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.rows = []
        def node(self, node):
            self.rows.append((node.id, node.tags["name"], node.location.lon, node.location.lat))
    reader = Reader()
    reader.apply_file(str(path))
    assert reader.rows == [(1, "Тест", 1., 2.)]
    return {"pbf_read_write": "ok", "data": "synthetic_fixture"}


def reporting_check(folder: Path) -> dict:
    import folium
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pypdf import PdfReader
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.plot([1, 2, 3], [1, 4, 9])
    ax.set_title("Проверка окружения — искусственные данные")
    fig.tight_layout()
    fig.savefig(folder / "test.png")
    fig.savefig(folder / "test.pdf")
    plt.close(fig)
    assert len(PdfReader(folder / "test.pdf").pages) == 1
    assert (folder / "test.png").stat().st_size > 1000
    map_ = folium.Map(location=[0, 0], tiles=None)
    folium.Marker([0, 0], tooltip="Искусственная тестовая точка").add_to(map_)
    map_.save(str(folder / "test.html"))
    assert "leaflet" in (folder / "test.html").read_text().lower()
    return {"png": "ok", "pdf": "ok", "html_map_generation": "ok"}


def main() -> int:
    import psutil
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "runs").mkdir(exist_ok=True)
    timestamp = datetime.now(ZoneInfo("Europe/Moscow")).isoformat()
    memory, disk = psutil.virtual_memory(), psutil.disk_usage(str(ROOT))
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=10)
        gpu_info = {"returncode": gpu.returncode, "details": gpu.stdout.strip(), "error": gpu.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        gpu_info = {"unavailable": str(exc)}
    packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    cpu_model = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                          if line.startswith("model name")), cpu_model)
    env = dict(captured_at=timestamp, os=platform.platform(), python=sys.version,
               executable=sys.executable, virtualenv=sys.prefix, project=str(ROOT),
               cpu_model=cpu_model, physical_cores=psutil.cpu_count(logical=False),
               logical_cores=psutil.cpu_count(), ram_total_gib=round(memory.total / 2**30, 2),
               ram_available_gib=round(memory.available / 2**30, 2),
               swap_used_gib=round(psutil.swap_memory().used / 2**30, 2),
               disk_free_gib=round(disk.free / 2**30, 2), gpu=gpu_info,
               compute_device="cpu", packages=packages)
    (ROOT / "environment.json").write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n")
    checks = []
    with tempfile.TemporaryDirectory(prefix="environment-check-", dir=ROOT / "runs") as temporary:
        for check in (mip_check, schedule_check, graph_geodesy_check, table_check, osm_check, reporting_check):
            start = time.perf_counter()
            try:
                details = check(Path(temporary))
                record = dict(check=check.__name__, status="passed", details=details)
            except Exception as exc:
                record = dict(check=check.__name__, status="failed", error=f"{type(exc).__name__}: {exc}")
            record["wall_seconds"] = round(time.perf_counter() - start, 3)
            checks.append(record)
            print(f"{record['status'].upper()}: {check.__name__}", flush=True)
            if record["status"] == "failed":
                print(record["error"], flush=True)
    dependency_check = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, timeout=30)
    checks.append(dict(check="pip_check", status="passed" if dependency_check.returncode == 0 else "failed",
                       details=(dependency_check.stdout + dependency_check.stderr).strip()))
    passed = all(check["status"] == "passed" for check in checks)
    report = dict(captured_at=timestamp, scope="environment_only_synthetic_examples", passed=passed, checks=checks)
    (ROOT / "reports/environment_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Итог: {sum(c['status'] == 'passed' for c in checks)}/{len(checks)} проверок; reports/environment_check.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
