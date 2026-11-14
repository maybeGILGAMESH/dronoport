"""Validate every saved plan, publish the report, seal and package one v2 run."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse
import json
import shutil
import zipfile
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_validation import validate
from droneport.pipeline_v2 import save,network_signature


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    folder=(Path(args.run_dir) if args.run_dir else Path((ROOT/'results_v2/current_run.txt').read_text().strip())).resolve()
    manifest=json.loads((folder/'run_manifest.json').read_text());towns=pd.read_csv(folder/'towns_main.csv');checks=[]
    for path in sorted(folder.rglob('result.json')):
        if 'source_snapshot' in path.parts:continue
        result=json.loads(path.read_text());cfg=json.loads((path.parent/'config.json').read_text())
        selected=pd.read_csv(path.parent/'towns.csv') if (path.parent/'towns.csv').exists() else towns.head(len(result['plan']['open_years']));check=validate(selected,result,cfg)
        checks.append(dict(artifact=str(path.relative_to(folder)),**check))
    assert checks and all(r['valid'] for r in checks),[r for r in checks if not r['valid']]
    save(folder/'delivery_validation.json',checks)
    game=json.loads((folder/'minimax_results.json').read_text())
    assert len({network_signature(a['plan']) for a in game['actions']})==game['network_actions']
    game_value=max(min(max(responses) for responses in network) for network in game['tree'])
    assert game_value==game['full']['value']==game['alpha_beta']['value']
    assert all(r['valid'] for r in game['leaf_validation'])
    for leaf in game['leaf_validation']:
        n=leaf['network'];j=game['actions'][n]['failed_nodes'].index(leaf['failed_node']);k=0 if leaf['response']=='retain' else 1
        assert leaf['completed_trips']==game['tree'][n][j][k]
    save(folder/'game_delivery_check.json',dict(value=game_value,distinct_networks=game['network_actions'],validated_leaves=len(game['leaf_validation']),same_tree_value=True))
    rows=[]
    def requirement(code,reference,text,status,evidence,check):rows.append(dict(id=code,pdf_reference=reference,requirement=text,status=status,evidence=evidence,verification=check))
    requirement('VAR','3–4','Регионы, буквы, 30/8 пунктов','done','towns_main.csv; data/processed/towns_small.csv','Фиксированные ID; территория не менялась после оптимизации')
    requirement('REGISTRY','3,7','Полный перечень и происхождение','partial','data/processed_v2/registry_gar.csv; gar_audit.json; gar_sources.json','Официальный список сохранён; неоднозначное сопоставление координат открыто')
    requirement('OSM_POLYGONS','7','Узлы и полигоны поселений','done','data/processed_v2/polygon_audit.csv','Пространственная проверка дубликатов, журнал неоднозначностей')
    requirement('MISSING','7','Пропуски и очистка','done','data/processed_v2/registry_gar.csv','Пропуски не заполняются по указанию пользователя')
    requirement('DEMAND','7','Направленный спрос и годовой масштаб','done','config.json; report/figures/04_od_matrix.png','Независимый пересчёт формулы и потолка спроса')
    for code,text in [('RANGE','Вместимость и дальность'),('FLEET','Непрерывность и замыкание суток'),('CHARGE','Зарядные места и движения'),('TRANSFER','Пересадки без повторного подсчёта'),('BUDGET','Накопленные бюджеты и остатки'),('RELOCATION','Межгодовые перегоны')]:
        requirement(code,'6,8',text,'done','delivery_validation.json; tests/test_event_model.py','Независимая проверка каждого опубликованного плана')
    requirement('HEURISTICS','9','Greedy и отжиг','done','method_comparison.csv; seed_results.csv; search_history.csv','Общая модель; сроки и ресурсы сравниваются явно')
    mips=json.loads((folder/'mip_reports.json').read_text())
    requirement('MIP','9','MIP и доказанная граница','done' if any(r.get('upper_bound') is not None for r in mips if r['nodes']==8) else 'partial','mip_reports.json; aggregate_bounds.json','Граница имеет явно указанную область действия')
    guarded=[r['nodes'] for r in mips if not (folder/f'scale/{r["nodes"]}/mip/result.json').exists() or r['status'] in ('RESOURCE_GUARD','MEMORY_LIMIT','Memory limit reached')]
    requirement('MIP_SCALE','план доработки','Временной MIP на всех размерах','partial' if guarded else 'done','mip_reports.json',f'Ограничение размера матрицы для: {guarded}; вместо расписания релаксация не выдаётся')
    requirement('SEQUENTIAL','9; план доработки','Совместные и последовательные решения','done' if all((folder/f'sequential_mip/{n}/result.json').exists() for n in (8,30)) else 'partial','annual_comparison.csv; sequential_mip/*/solver_reports.json','На 8 пунктах MIP; на 30 сравнение эвристик и явный статус временного MIP. Прошлые активы и рейсы фиксируются')
    requirement('PATHS','9','BFS, A*, Дейкстра и временная достижимость','done','bfs_astar.csv','Потенциальный граф и построенные сети всех лет')
    requirement('SCALE','10','Эксперимент по масштабу','done','method_comparison.csv','8/12/20/30, качество и время; статусы отсутствующих MIP сохранены')
    requirement('FINANCE','10','Бюджет и пороговые изменения','done','experiments.csv','250–1000 млн, сетки 50 и 10 млн; эвристическая зависимость')
    requirement('QUALITY','10','Две стратегии качества данных','done','experiments/quality_cap_0.95; config.json','Исходная модель и ограничение влияния экстремального населения, без удаления пунктов')
    requirement('RANDOM','10','Не менее 10 seed','done','seed_results.csv','По 10 seed на каждом размере; исходные времена сохранены')
    requirement('SENSITIVITY','6,10','Чувствительность учебных предположений','done','experiments.csv','CAPEX/OPEX/скорость/зарядка/спрос/сетка')
    requirement('ROBUST','10','Стресс-тесты и робастный план','done','scenario_results.csv; delivery_validation.json','Введённые активы фиксированы; восстановление эвристическое')
    requirement('GAME','10','Перебор и альфа-бета','done','minimax_results.json','Одинаковые листья, совпадение значения игры')
    requirement('OFFLINE','11','Автономные карты','done','report/browser_checks/browser_checks.json','Chromium и Firefox offline, ноль HTTP-запросов')
    requirement('DELIVERY','11','Отчёт, записка, код и воспроизводимость','done','report/report.pdf; report/executive_summary.txt; source_snapshot','Числа связаны с запуском, графики имеют ссылки на CSV/JSON')
    if (folder/'cp_ga/search_manifest.json').exists():
        requirement('CP_FIXED','дополнительный эксперимент','CP-SAT при фиксированных инвестициях и отказах','done','cp_ga/fixed_results.csv; cp_ga/portfolio_30/solver_report.json','Независимая проверка; границы только для фиксированной сети')
        requirement('GA_MATCHED','дополнительный эксперимент','GA и отжиг с общим CP-декодером','done','cp_ga/search_results.csv; cp_ga/validation.json','10 парных seed, общий старт, ремонт, декодер и лимит')
    pd.DataFrame(rows).to_csv(folder/'requirements_matrix.csv',index=False)
    if (folder/'regional/manifest.json').exists():
        requirement('REGIONAL_SERVICE','дополнительное условие пользователя','Порт и фактические рейсы в каждой из трёх областей к году 3','done','regional/region_service.csv; regional/validation.json','Независимый подсчёт введённых портов и выполненных рейсов; нормальный режим')
        pd.DataFrame(rows).to_csv(folder/'requirements_matrix.csv',index=False)
    print(f'Validated {len(checks)} plans; guarded MIP sizes: {guarded}',flush=True)
    if args.validate_only:return
    assert manifest['status']=='calculated','Numerical run is not complete'
    assert not manifest.get('additional_mip_pending'),'Supplemental numerical attempts are not integrated'
    consistency=json.loads((folder/'comparison_consistency.json').read_text());assert consistency['valid']
    tests=json.loads((folder/'test_validation.json').read_text())
    assert tests['junit_sha256']==checksum(ROOT/'reports/tests_v2.xml')
    assert all(checksum(ROOT/name)==digest for name,digest in tests['source_sha256'].items()),'Tested source has changed'
    browser=json.loads((folder/'report/browser_checks/browser_checks.json').read_text())
    assert {r['browser'] for r in browser}=={'chromium','firefox'} and all(not r['remote_requests'] and not r['js_errors'] and r['ready'] for r in browser)
    for record in browser:
        assert record['html_sha256']==checksum(folder/'report/maps/network.html')
        assert all(checksum(folder/'report/maps/assets'/name)==digest for name,digest in record['asset_sha256'].items())
    if (folder/'cp_ga/search_manifest.json').exists():
        extra=json.loads((folder/'cp_ga/validation.json').read_text());assert extra['valid']
        assert all(checksum(ROOT/name)==digest for name,digest in extra['source_sha256'].items())
        second=json.loads((folder/'report/browser_checks_cp_ga/browser_checks.json').read_text())
        assert {r['browser'] for r in second}=={'chromium','firefox'}
        assert all(r['ready'] and not r['js_errors'] and not r['remote_requests'] and r['html_sha256']==checksum(folder/'report/maps/network_cp_ga.html') for r in second)
        for r in second:assert all(checksum(folder/'report/maps/assets'/name)==digest for name,digest in r['asset_sha256'].items())
    # Export explicit investments in addition to the machine-readable plan.
    if (folder/'regional/manifest.json').exists():
        regional=json.loads((folder/'regional/validation.json').read_text());assert regional['valid']
        assert regional['result_sha256']==checksum(folder/'regional/final_best/result.json')
        assert all(checksum(ROOT/name)==digest for name,digest in regional['source_sha256'].items())
        checks_map=json.loads((folder/'report/browser_checks_regional/browser_checks.json').read_text())
        assert {r['browser'] for r in checks_map}=={'chromium','firefox'}
        for r in checks_map:
            assert r['ready'] and not r['js_errors'] and not r['remote_requests']
            assert r['html_sha256']==checksum(folder/'report/maps/network_regional.html')
            assert all(checksum(folder/'report/maps/assets'/name)==digest for name,digest in r['asset_sha256'].items())
    base=json.loads((folder/'base/result.json').read_text());investments=[]
    for i,y in enumerate(base['plan']['open_years']):
        if y:investments.append(dict(kind='port',year=y,place_id=towns.iloc[i].place_id,name=towns.iloc[i].name_original,aircraft_id=''))
    for a in base['plan']['aircraft']:
        investments.append(dict(kind='aircraft',year=a['year'],place_id=towns.iloc[a['home']].place_id,name=towns.iloc[a['home']].name_original,aircraft_id=a['id']))
    pd.DataFrame(investments).to_csv(folder/'investment_fleet_plan.csv',index=False)
    for name in ('report.pdf','report.html','report.md','executive_summary.txt','executive_summary.md','figure_manifest.json'):
        shutil.copy2(folder/'report'/name,ROOT/'reports'/name)
    for name in ('cp_ga_supplement.pdf','cp_ga_supplement.md','optimized_investments.csv','regional_supplement.pdf','regional_supplement.md','regional_investments.csv'):
        if (folder/'report'/name).exists():shutil.copy2(folder/'report'/name,ROOT/'reports'/name)
    shutil.copytree(folder/'report/figures',ROOT/'reports/figures',dirs_exist_ok=True)
    shutil.copytree(folder/'report/maps',ROOT/'reports/maps',dirs_exist_ok=True)
    shutil.copy2(folder/'requirements_matrix.csv',ROOT/'reports/requirements_matrix.csv')
    # Retain original numerical-code snapshot; separately identify report derivation.
    manifest['report_generator_sha256']=checksum(ROOT/'src/droneport/report_v2.py')
    if (folder/'regional/manifest.json').exists():
        manifest['regional_configuration_sha256']=checksum(folder/'regional/config.json')
        manifest['regional_report_generator_sha256']=checksum(ROOT/'src/droneport/report_regional.py')
        manifest['regional_result_sha256']=checksum(folder/'regional/final_best/result.json')
    manifest['report_artifact_count']=len(list((folder/'report/figures').glob('*.png')))
    manifest['delivery_validated_plans']=len(checks)
    manifest['test_count']=tests['tests'];manifest['configuration_sha256']=checksum(folder/'config.json')
    manifest['data_version']=dict(frozen_sample_sha256=checksum(folder/'towns_main.csv'),gar_release=json.loads((ROOT/'data/processed_v2/gar_audit.json').read_text())['version'],missing_population='preserved_null')
    manifest['environment_sha256']=checksum(ROOT/'environment.json');manifest['dependency_lock_sha256']=checksum(ROOT/'requirements.txt')
    manifest['source_files']={str(p.relative_to(ROOT)):checksum(p) for p in (ROOT/'data/processed_v2').glob('*') if p.is_file()}
    manifest['artifact_hashes']={str(p.relative_to(folder)):checksum(p) for p in folder.rglob('*') if p.is_file() and p.name!='run_manifest.json' and '__pycache__' not in p.parts}
    save(folder/'run_manifest.json',manifest)
    output=ROOT/'artifacts'/f'droneport_{folder.name}.zip'
    if output.exists():raise FileExistsError(output)
    paths=[]
    for directory in ('src','scripts','config','tests','assets','data/processed','data/processed_v2','reports',str(folder.relative_to(ROOT))):
        paths += [p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.partial')]
    for pattern in ('*.md','requirements.*','*.xlsx','*.pdf','pytest.ini','environment.json','input_inventory.csv'):paths+=list(ROOT.glob(pattern))
    paths=sorted(set(paths))
    delivery={str(p.relative_to(ROOT)):checksum(p) for p in paths}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in paths:archive.write(p,str(p.relative_to(ROOT)))
        archive.writestr('results_v2/current_run.txt',str(folder.relative_to(ROOT)))
        archive.writestr('delivery_manifest.json',json.dumps(dict(run_id=folder.name,files=delivery,omitted=['.venv','OSM PBF','GAR raw XML (parsed registry and source hashes included)','previous runs']),ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:assert archive.testzip() is None
    save(output.with_suffix('.sha256.json'),dict(sha256=checksum(output),bytes=output.stat().st_size))
    (ROOT/'results_v2/current_run.txt').write_text(str(folder.resolve()))
    print(output,checksum(output),flush=True)

if __name__=='__main__':main()
