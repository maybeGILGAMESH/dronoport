"""Audit every saved run; reconstruct search evidence without rerunning optimizers."""
from pathlib import Path
import sys,json,hashlib,collections,math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from droneport.ingest import ROOT,checksum
from droneport.article_theme import apply_theme,COLORS
from droneport.event_model import EventInstance
from droneport.event_validation import validate
R=ROOT/'runs/20261106_154352_regional'; O=ROOT/'reports/research_audit';O.mkdir(exist_ok=True)
(O/'figures').mkdir(exist_ok=True)
def js(p):return json.loads(p.read_text())
def sig(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def table(name,rows):
 d=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows);d.to_csv(O/(name+'.csv'),index=False);return d
def number(x):return f'{x:,.0f}'.replace(',',' ')
# Entire on-disk collection, including intermediate runs not previously exposed in the article.
files=[];allresults=[];runs=[]
for run in sorted((ROOT/'runs').iterdir()):
 if not run.is_dir():continue
 local=[]
 for p in sorted(run.rglob('*')):
  if not p.is_file() or '__pycache__' in p.parts:continue
  row=dict(run=run.name,path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=checksum(p));files.append(row);local.append(row)
  if p.name=='result.json':
   d=js(p);allresults.append(dict(**row,completed_trips=d.get('completed_trips'),nodes=len(d.get('plan',{}).get('open_years',[]))))
 runs.append(dict(run=run.name,files=len(local),bytes=sum(x['bytes'] for x in local),result_files=sum(Path(x['path']).name=='result.json' for x in local),unique_file_contents=len({x['sha256'] for x in local})))
 print('Inventoried',run.name,len(local),flush=True)
filedf=table('file_inventory',files);allres=table('all_run_results',allresults);rundf=table('run_inventory',runs)
canonicalhash=set(allres[allres.run==R.name].sha256);older=allres[(allres.run!=R.name)&~allres.sha256.isin(canonicalhash)]
table('historical_results_not_in_latest',older)
# Validate current deliverable records independently; retain paths even when records are copies.
towns=pd.read_csv(R/'towns_main.csv');cfg=js(R/'config.json');inst=EventInstance(towns,cfg);catalog=[]
for p in sorted(R.rglob('result.json')):
 d=js(p);plan=d['plan'];n=len(plan['open_years']);c=js(p.with_name('config.json'))
 selected=pd.read_csv(p.with_name('towns.csv')) if p.with_name('towns.csv').exists() else towns.head(n)
 check=validate(selected,d,c)
 assets=sorted([(a['year'],a['home'],tuple(int(a.get('homes',{}).get(str(y),a['home'])) for y in range(a['year'],4))) for a in plan['aircraft']])
 design=dict(towns=selected.place_id.tolist(),open_years=plan['open_years'],aircraft=assets)
 rel=p.relative_to(R).as_posix();saved=js(p.with_name('validation.json')) if p.with_name('validation.json').exists() else {}
 catalog.append(dict(path=rel,series=rel.split('/')[0],nodes=n,result_sha256=checksum(p),investment_sha256=sig(design),config_sha256=sig(c),scenario_sha256=sig(d.get('scenario',{})),valid=check['valid'],saved_valid=saved.get('valid'),errors=json.dumps(check['errors'],ensure_ascii=False),completed_trips=d['completed_trips'],cost_rub=sum(x['spend_rub'] for x in d['budget']),ports=sum(y>0 for y in plan['open_years']),fleet=len(plan['aircraft']),flights=len(d['flights']),itineraries=len(d['itineraries'])))
cat=table('result_catalog',catalog)
series=table('series_inventory',cat.groupby('series').agg(records=('path','size'),unique_results=('result_sha256','nunique'),investment_designs=('investment_sha256','nunique'),valid=('valid','sum')).reset_index())
assert cat.valid.all(),cat[~cat.valid]
print('Validated',len(cat),'records;',cat.result_sha256.nunique(),'distinct JSON;',cat.investment_sha256.nunique(),'asset designs',flush=True)
# Do not load 495 MB aggregate history or count its copies again: use authoritative per-seed files.
hist=[];trajectories=[]
for stage,pattern in [('A preliminary','preliminary_iteration_study/scale/*/seed_*/history.csv'),('A timed','time_budget_study/scale/*/seed_*/history.csv'),('B SA','cp_ga/search/sa/seed_*/history.csv'),('B GA','cp_ga/search/ga/seed_*/history.csv')]:
 for p in sorted(R.glob(pattern)):
  h=pd.read_csv(p);n=30 if stage.startswith('B') else int(p.parents[1].name);seed=int(p.parent.name.split('_')[-1]);initial=498300 if stage.startswith('B') else float(pd.read_csv(R/'method_comparison.csv').query('instance==@n and method=="greedy"').iloc[0].completed_trips)
  feasible=h.feasible.astype(bool) if 'feasible' in h else h.candidate.notna();best=h.best.to_numpy();improve=int(np.count_nonzero(np.diff(np.r_[initial,best])>0))
  hist.append(dict(stage=stage,nodes=n,seed=seed,path=p.relative_to(R).as_posix(),sha256=checksum(p),proposals=len(h),feasible=int(feasible.sum()),accepted=int(h.accepted.astype(bool).sum()),improvements=improve,best=int(best[-1]),elapsed=float(h.elapsed.iloc[-1]),unique_objective_values=h.candidate.nunique(),zero_candidates=int((h.candidate==0).sum()),accepted_zero=int(((h.candidate==0)&h.accepted).sum()),last_candidate=h.candidate.iloc[-1],decoder_calls=int(h.decoder_calls.iloc[-1]) if 'decoder_calls' in h else None,cache_hits=int(h.cache_hits.iloc[-1]) if 'cache_hits' in h else None))
  for t in np.linspace(0,600,61):
   part=h[h.elapsed<=t];trajectories.append(dict(stage=stage,nodes=n,seed=seed,seconds=t,best=initial if part.empty else part.best.iloc[-1]))
prepath=R/'preliminary_iteration_study/search_history.csv';preh=pd.read_csv(prepath)
for (n,seed),hpre in preh.groupby(['instance','seed']):
 initial=float(pd.read_csv(R/'method_comparison.csv').query('instance==@n and method=="greedy"').iloc[0].completed_trips)
 hist.append(dict(stage='A preliminary',nodes=int(n),seed=int(seed),path=prepath.relative_to(R).as_posix(),sha256=checksum(prepath),proposals=len(hpre),feasible=int(hpre.feasible.sum()),accepted=int(hpre.accepted.sum()),improvements=int(np.count_nonzero(np.diff(np.r_[initial,hpre.best.to_numpy()])>0)),best=int(hpre.best.iloc[-1]),elapsed=float(hpre.elapsed.iloc[-1]),unique_objective_values=hpre.candidate.nunique(),decoder_calls=None,cache_hits=None))
history=table('history_inventory',hist);trajectory=table('search_trajectories',trajectories)
# Solver outcomes are attempts, not independent successful networks.
attempt=[]
for p in sorted((R/'extended_mip_attempts').glob('*/solver_report.json')):
 d=js(p);m=js(p.with_name('attempt_manifest.json')) if p.with_name('attempt_manifest.json').exists() else {}
 attempt.append(dict(attempt=p.parent.name,nodes=d.get('nodes'),status=d.get('status'),returncode=m.get('returncode'),seconds=m.get('wall_seconds',d.get('wall_seconds')),memory_limit_gib=m.get('memory_limit_gib',d.get('memory_limit_gib')),incumbent=d.get('incumbent'),upper_bound=d.get('upper_bound'),gap=d.get('gap'),saved_plan=p.with_name('result.json').exists(),scope=d.get('scope',d.get('bound_source','not recorded'))))
attempts=table('mip_attempts',attempt)
# Data engineering: separate OD trips, passenger-legs, flights and active asset-years.
variants={'A':'base','B':'cp_ga/final_best','C':'regional/final_best'};distance=[];resources=[];facts=[];od=[]
for tag,sub in variants.items():
 d=js(R/sub/'result.json');f=pd.DataFrame(d['flights']);tr=pd.DataFrame(d['itineraries']);p=d['plan'];load=int(f.passengers.sum());trip=len(tr);weight=cfg['operating_days'];dur=(f.arrival_min-f.departure_min).sum();charge=(f.charge_end_min-f.arrival_min).sum();airyears=sum(4-a['year'] for a in p['aircraft']);portyears=sum(4-y for y in p['open_years'] if y)
 facts.append(dict(variant=tag,trips=d['completed_trips'],passenger_legs=load*weight,transfer_extra_legs=(load-trip)*weight,flights=len(f),full_flights=int((f.passengers==10).sum()),empty_flights=int((f.passengers==0).sum()),load_factor=load/(len(f)*10),mean_flight_km=f.distance_km.mean(),mean_passenger_leg_km=np.average(f.distance_km,weights=f.passengers),median_flight_km=f.distance_km.median(),min_flight_km=f.distance_km.min(),short_flights_20km=int((f.distance_km<20).sum()),flight_share=dur/(airyears*720),charge_share=charge/(airyears*720),wait_share=1-(dur+charge)/(airyears*720),asset_years=airyears,port_years=portyears,served_od_pairs=len(tr[['origin_id','destination_id']].drop_duplicates()),cost_rub=sum(b['spend_rub'] for b in d['budget']),carry_year3=d['budget'][-1]['carry_rub']))
 for _,row in f.iterrows():distance.append(dict(variant=tag,year=int(row.year),distance_km=row.distance_km,passengers=int(row.passengers)))
 for y in [1,2,3]:
  fy=f[f.year==y]
  for i,oy in enumerate(p['open_years']):
   if not 0<oy<=y:continue
   pid=towns.iloc[i].place_id;arr=fy[fy.destination_id==pid];dep=fy[fy.origin_id==pid];counts=collections.Counter(((pd.concat([arr.arrival_min,dep.departure_min])-480)//90).astype(int))
   events=sorted([(int(v.arrival_min),1) for _,v in arr.iterrows()]+[(int(v.charge_end_min),-1) for _,v in arr.iterrows()]);occ=peak=0
   for _,delta in events:occ+=delta;peak=max(peak,occ)
   resources.append(dict(variant=tag,year=y,port=towns.iloc[i].name_original,movements=len(arr)+len(dep),movement_capacity=16,saturated_windows=sum(v==2 for v in counts.values()),peak_chargers=peak,charging_minutes=int((arr.charge_end_min-arr.arrival_min).sum()),charging_capacity=1440))
 served=tr.groupby(['origin_id','destination_id']).annual_weight.sum().to_dict()
 for i in range(inst.n):
  for j in range(inst.n):
   if i==j:continue
   od.append(dict(variant=tag,origin=inst.ids[i],destination=inst.ids[j],distance_km=inst.distance[i,j],demand=int(inst.demand[:,i,j].sum()*weight),served=int(served.get((inst.ids[i],inst.ids[j]),0))))
facts=table('operational_facts',facts);dist=table('flight_distances',distance);resource=table('port_resources',resources);ods=table('od_coverage',od)
assert all(ods.groupby('variant').served.sum().sort_index().to_numpy()==facts.set_index('variant').sort_index().trips.to_numpy())
assert all(facts.passenger_legs-facts.transfer_extra_legs==facts.trips)
bfs=pd.read_csv(R/'bfs_astar.csv');reach=[]
for (g,y),part in bfs.groupby(['graph','year']):
 reach.append(dict(graph=g,year=y,pairs=len(part),spatial=int(part.reachable.sum()),scheduled=int(part.schedule_reachable.fillna(False).astype(bool).sum()),shorter_astar=int((part.bfs_minutes-part.astar_minutes>1e-6).sum())))
reach=table('reachability_summary',reach)
# Saved comparative series, with every row represented in machine-readable evidence.
methods=pd.read_csv(R/'method_comparison.csv');seeds=pd.read_csv(R/'seed_results.csv');candidates=pd.read_csv(R/'regional/candidate_results.csv');fixed=pd.read_csv(R/'cp_ga/fixed_results.csv');search=pd.read_csv(R/'cp_ga/search_results.csv');experiments=pd.read_csv(R/'experiments.csv')
for name,d in [('method_comparison',methods),('timed_seed_results',seeds),('regional_candidates',candidates),('fixed_cp_results',fixed),('ga_sa_results',search),('parameter_experiments',experiments)]:table(name,d)
reconciled=[]
def reconcile(row,path,source):
 result=js(R/path/'result.json');plan=result['plan'];actual=dict(completed_trips=result['completed_trips'],cost_rub=sum(x['spend_rub'] for x in result['budget']),ports=sum(y>0 for y in plan['open_years']),fleet=len(plan['aircraft']))
 for key,value in actual.items():assert abs(row[key]-value)<1e-8,(source,path,key,row[key],value)
 reconciled.append(dict(source=source,path=path,valid=True))
for _,row in methods.iterrows():
 n=int(row.instance);paths={'greedy':f'scale/{n}/greedy','annealing_best':f'scale/{n}/timed_best','annealing_preliminary':f'preliminary_iteration_study/scale/{n}/best','deployment_polish':f'deployment_polish/{n}/best','mip':f'scale/{n}/mip','sequential_greedy':f'sequential/{n}','sequential_mip':f'sequential_mip/{n}'}
 reconcile(row,paths[row.method],'methods')
for _,row in seeds.iterrows():reconcile(row,f'scale/{int(row.instance)}/seed_{int(row.seed)}','seeds')
for _,row in experiments.iterrows():reconcile(row,row.result_path if isinstance(row.result_path,str) else f'grid/{int(row.value)}','experiments')
for name,df in [('fixed_cp',fixed),('ga_sa',search)]:
 for _,row in df.iterrows():reconcile(row,row.result_path,name)
table('comparison_reconciliation',reconciled)
assert len(history)==100 and len(preh)==8000 and len(seeds)==40 and len(candidates)==75
# Article blocks and white Atlas graphics. Explicit source and axis description per figure.
apply_theme();blocks=[];figures=[]
def h(t):blocks.append(dict(kind='h',text=t))
def p(t):blocks.append(dict(kind='p',text=t))
def tab(title,headers,rows,widths=None):blocks.append(dict(kind='table',title=title,headers=headers,rows=rows,widths=widths))
def fig(stem,title,source,axes,draw,height=3.8):
 f,ax=plt.subplots(figsize=(7.2,height),layout='constrained');draw(f,ax)
 for ext in ['png','pdf','svg']:f.savefig(O/'figures'/f'{stem}.{ext}',dpi=280,facecolor='white',bbox_inches='tight')
 plt.close(f);n=19+len(figures);figures.append(dict(number=n,title=title,source=source,axes=axes,**{ext:f'../research_audit/figures/{stem}.{ext}' for ext in ['png','pdf','svg']}));blocks.append(dict(kind='audit_figure',number=n))
h('11. Аудит расчётного архива: что скрыто за тремя итогами')
p(f'Три варианта A, B и C обозначают выбранные решения, а не число проведённых расчётов. Проверены все семь каталогов runs: в них {number(len(filedf))} файлов и {number(len(allres))} записей result.json. По SHA-256 это {number(allres.sha256.nunique())} различных файлов результата. Итоговый каталог C содержит {len(cat)} записей, {cat.result_sha256.nunique()} различных файлов результата и {cat.investment_sha256.nunique()} структур инвестиций. Для последнего числа из подписи исключены имена аппаратов и seed расписания, но сохранены состав и порядок пунктов, годы открытия и годовые базы. Это число не является числом независимых экспериментов: среди записей есть разные размеры, условия спроса и сценарии отказа.')
p(f'Все {len(cat)} текущих результатов повторно проверены независимым валидатором с сохранённой конфигурацией и соответствующей выборкой пунктов. Исторические файлы ранних запусков проверены на наличие и целостность, но не объявлены допустимыми для последней редакции модели. {len(older)} исторических записей, представляющих {older.sha256.nunique()} различных файлов, не имеют побайтовой копии среди текущих result.json. Они сохранены в исходных каталогах; это не потеря данных. Новый комплект включает все семь каталогов, включая предварительные запуски, а не только три финальных архива.')
tab('Таблица R1. Полный перечень каталогов запуска',['Запуск','Файлов','result.json','Объём, МиБ'],[[x.run,str(x.files),str(x.result_files),f'{x.bytes/2**20:.1f}'] for x in rundf.itertuples()],[2.4,1,1.2,1.3])
tab('Таблица R2. Состав итогового каталога; строки между сериями могут дублироваться',['Серия','Записей','Различных JSON','Инвест. структур'],[[x.series,str(x.records),str(x.unique_results),str(x.investment_designs)] for x in series.itertuples()],[2.5,1,1.4,1.4])
p('Файлы file_inventory.csv и all_run_results.csv дают адрес, размер и SHA-256 каждой записи. result_catalog.csv связывает текущий план с конфигурацией, сценарием, результатом независимой проверки и подписью инвестиций. history_inventory.csv считает только выбранные первичные журналы seed; агрегированный search_history.csv и скопированные журналы scale повторно не суммируются. Число разных значений целевой функции не используется как число разных сетей: разные расписания могут перевозить одинаковое число пассажиров.')
h('12. Внутренние альтернативы A, B и C')
p('В семейство A входят greedy, предварительный поиск с ограничением итераций, отдельная серия отжига по 600 секунд на seed и последующая доработка активов. Обе серии отжига стартовали от greedy; предварительный результат не передавался как старт временной серии. Финальный A получен из временной серии удалением лишних активов и добавлением аппаратов с перепланированием. Параллельно сохранены MIP, последовательные годовые решения и отдельная робастная сеть. Последняя максимизирует худший сценарий, поэтому не должна подменять базовое решение в рейтинге обычных перевозок. Рост качества между стадиями описывает эту последовательность вычислений; сравнивать его как ускорение одного метода на одинаковом времени нельзя.')
def draw_a(f,ax):
 selected=['greedy','annealing_best','deployment_polish'];labels=['Greedy','Отжиг: лучший из 10','Доработка инвестиций'];x=np.arange(4)
 for k,(method,label) in enumerate(zip(selected,labels)):
  v=methods[methods.method==method].set_index('instance').loc[[8,12,20,30]];ax.bar(x+(k-1)*.25,v.completed_trips/1000,width=.24,label=label)
 ax.set_xticks(x,['8','12','20','30']);ax.set(xlabel='Число пунктов в фиксированной выборке',ylabel='Завершённые поездки за 3 года, тыс.');ax.legend(loc='upper left');ax.grid(axis='y',alpha=.5)
fig('a_stages','Стадии формирования A на четырёх размерах','method_comparison.csv; deployment_polish/manifest.json','Абсцисса задаёт размер выборки, ордината число завершённых поездок за три года в тысячах. Столбцы показывают greedy, лучший результат десяти запусков отжига и последующую доработку активов. Это последовательные стадии с разным суммарным временем, а не три равных по бюджету метода.',draw_a)
polish=js(R/'deployment_polish/manifest.json');pt=polish['trace'];tested=sum(x['tested'] for x in pt);feas=sum(x['feasible'] for x in pt)
p(f'В доработке инвестиций зафиксировано {tested} проверок добавления аппарата с возможным открытием базы; {feas} проверок дали допустимый вариант. Эти числа относятся к проверкам, а не уникальным сетям. На 30 пунктах результат вырос с 448 800 до 491 700 поездок, на 42 900, или {42900/448800*100:.2f}%. На восьми пунктах объём остался 358 380, но число портов уменьшилось с восьми до шести, а расходы на 216 млн рублей. Улучшение здесь означает экономию при том же сервисе, а не рост целевой функции.')
tab('Таблица R3. Дополнительные решения на 30 пунктах внутри A',['Решение','Поездки','Млрд руб.','Порты / флот'],[[str(x.method),number(x.completed_trips),f'{x.cost_rub/1e9:.3f}',f'{x.ports} / {x.fleet}'] for x in methods[methods.instance==30].itertuples()],[2.8,1,1,1.2])
def draw_networks(f,ax):
 ax.remove();axes=f.subplots(2,2);points=towns.set_index('place_id');panels=[('Greedy','scale/30/greedy'),('Лучший seed','scale/30/timed_best'),('A после доработки','base'),('Робастная сеть','robust')];all_ids=set();draws=[]
 for label,path in panels:
  d=js(R/path/'result.json');edges={(x['origin_id'],x['destination_id']) for x in d['flights'] if x['year']==3};active=[i for i,y in enumerate(d['plan']['open_years']) if y];all_ids.update(towns.iloc[active].place_id);draws.append((label,d,edges,active))
 pts=points.loc[sorted(all_ids)];bounds=(pts.lon.min()-.12,pts.lon.max()+.12,pts.lat.min()-.08,pts.lat.max()+.08)
 for ax,(label,d,edges,active) in zip(axes.flat,draws):
  for a,b in edges:
   pa,pb=points.loc[a],points.loc[b];ax.plot([pa.lon,pb.lon],[pa.lat,pb.lat],color=COLORS['A'],lw=.9,alpha=.6)
  ax.scatter(towns.iloc[active].lon,towns.iloc[active].lat,s=16,color=COLORS['C'],zorder=3)
  ax.set(title=f'{label}: {number(d["completed_trips"])} поездок',xlabel='Долгота, °',ylabel='Широта, °',xlim=bounds[:2],ylim=bounds[2:]);ax.grid(alpha=.3)
fig('a_alternative_networks','Четыре фактически рассчитанные сети внутри семейства A','scale/30/greedy; scale/30/timed_best; base; robust','В каждой панели абсцисса задаёт долготу, ордината широту в градусах; границы координат одинаковы. Точки обозначают введённые порты третьего года, линии фактические рейсы в обоих направлениях без показа частоты. Число поездок в заголовке относится ко всем трём годам. Робастная сеть решает другую целевую задачу и не ранжируется по базовой производительности наравне с остальными.',draw_networks,height=5.2)
a_hist=history[history.stage=='A timed'];pre=history[history.stage=='A preliminary']
p(f'Первичные журналы содержат {len(pre)} предварительных запусков и {len(a_hist)} запусков A с лимитом времени. В серии по времени сохранено {number(a_hist.proposals.sum())} предложений изменений, из них {number(a_hist.feasible.sum())} помечены построителем как допустимые и {number(a_hist.accepted.sum())} приняты поиском. Принятие не означает улучшение: отжиг допускает равные и худшие состояния. Зафиксировано {number(a_hist.improvements.sum())} строгих увеличений лучшего значения относительно общего старта. Каждый seed остаётся самостоятельным наблюдением, а миллионы предложений внутри него не превращаются в миллионы независимых опытов.')
def draw_seed(f,ax):
 for n in [8,12,20,30]:
  a=trajectory[(trajectory.stage=='A timed')&(trajectory.nodes==n)].groupby('seconds').best;v=a.agg(['min','median','max']);ax.plot(v.index,v['median']/1000,label=f'{n} пунктов');ax.fill_between(v.index,v['min']/1000,v['max']/1000,alpha=.12)
 ax.set(xlabel='Прошедшее время одного запуска, с',ylabel='Лучший результат, тыс. поездок');ax.legend(ncols=2);ax.grid(alpha=.4)
fig('a_search_trajectories','Как накапливались улучшения в серии A','history_inventory.csv; search_trajectories.csv','Абсцисса показывает прошедшие секунды одного запуска, от 0 до 600. Ордината показывает лучший уже найденный объём поездок. Линия является медианой десяти seed данного размера, полоса охватывает минимум и максимум, а не доверительный интервал. Значения на общей сетке времени переносятся ступенчато из последнего завершённого шага.',draw_seed)
seedstats=seeds.groupby('instance').completed_trips.agg(['min','median','max','nunique']).reset_index();tab('Таблица R4. Разброс десяти seed A при лимите 600 секунд',['Пунктов','Минимум','Медиана','Максимум','Разных итогов'],[[str(int(x.instance)),number(x.min),number(x.median),number(x.max),str(int(x.nunique))] for x in seedstats.itertuples()])
large=a_hist[a_hist.nodes==30].sort_values('seed');heavy=large[large.proposals>1000000]
p(f'На 30 пунктах seed 2, 3 и 5 породили {number(heavy.proposals.sum())} предложений, но {number(heavy.zero_candidates.sum())} из них имели нулевую целевую функцию. На них приходится {heavy.proposals.sum()/a_hist.proposals.sum()*100:.2f}% всех предложений временной серии A. Последние кандидаты в этих трёх журналах тоже имеют нулевой объём, тогда как сохранённые лучшие значения составляют 448 800, 409 200 и 409 200. Таким образом, большая часть счётчика не свидетельствует о продуктивном исследовании хороших сетей. Код хранит лучшее решение отдельно от текущего и использует кэш, но журналы A не содержат подписей всех промежуточных генотипов: точное число уникальных сетей и долю попаданий в кэш восстановить нельзя. Это диагностический недостаток прежнего протокола, а не основание задним числом заменить результаты.')
tab('Таблица R4a. Почему число итераций A нельзя считать числом полезных сетей',['Seed, 30 пунктов','Предложений','Нулевых кандидатов','Лучшее'],[[str(x.seed),number(x.proposals),number(x.zero_candidates),number(x.best)] for x in large.itertuples()],[1.2,1.4,1.7,1.3])
p('На 30 пунктах предварительная серия по 200 итераций дала 455 400 поездок, тогда как лучшая попытка по 600 секунд дала 448 800: на 6 600, или 1,45%, меньше. Это не нарушение сохранения лучшего состояния внутри одного запуска: сравниваются отдельные серии с общим greedy-стартом, но разным управлением охлаждением. Предварительный протокол охлаждал поиск по доле выполненных итераций, временной по доле истекшего времени. Поэтому дополнительное время здесь не является гарантией более высокого итога. Наблюдение мотивирует отдельную проверку охлаждения и рестартов; такая новая серия в настоящем аудите не выполнялась.')
p('Сохранены также девять расширенных попыток MIP. В таблице R5 отдельно показаны завершение процесса и наличие сохранённого плана. Возврат процесса с кодом 0 не доказывает оптимальность; статус MODEL_TOO_LARGE или MEMORY_LIMIT относится к ресурсам модели. Границы из агрегированной релаксации нельзя выдавать за найденное расписание. Повторные старты и смена лимита памяти входят в вычислительную историю, но не являются новыми независимыми экземплярами.')
tab('Таблица R5. Расширенные попытки MIP',['Попытка','Статус','Секунд','Лимит, ГиБ','План'],[[x.attempt,str(x.status),'-' if pd.isna(x.seconds) else f'{x.seconds:.1f}','-' if pd.isna(x.memory_limit_gib) else f'{x.memory_limit_gib:g}','да' if x.saved_plan else 'нет'] for x in attempts.itertuples()],[2.2,2,1,1,0.6])
zero=int((fixed.gain==0).sum());pos=int((fixed.gain>0).sum())
p(f'В B предварительная серия CP-SAT на фиксированных активах содержит {len(fixed)} задачи: {zero} без роста целевой функции и {pos} с улучшением. Это отдельный протокол, предшествующий финальной доводке. Смена построителя расписания и последующая пассажирская аллокация дали итоговые 501 600 поездок. Все 20 запусков GA и SA стартовали с 498 300 и закончили с тем же значением. Следовательно, прирост итогового B нельзя приписать генетическому алгоритму.')
def draw_b(f,ax):
 z=search.groupby('method')[['iterations','decoder_calls','cache_hits']].sum();x=np.arange(len(z));names={'ga':'GA','sa':'SA'}
 ax.bar(x-.17,z.decoder_calls,width=.34,label='Вызовы декодера');ax.bar(x+.17,z.cache_hits,width=.34,label='Попадания в кэш');ax.set_xticks(x,[names[k] for k in z.index]);ax.set(ylabel='Сумма по десяти seed',xlabel='Метод при общем построителе расписания');ax.legend();ax.grid(axis='y',alpha=.4)
fig('b_decoder','Работа декодера при одинаковом конечном результате GA и SA','cp_ga/search_results.csv','Абсцисса разделяет GA и SA. Ордината показывает суммарное число вызовов общего декодера и попаданий в его кэш за десять seed. Это счётчики выполненной работы, а не скорость процессора и не число уникальных сетей. Нулевой выигрыш по поездкам не означает, что поиск не выполнялся.',draw_b)
cok=candidates[candidates.feasible.astype(bool)];cfail=len(candidates)-len(cok)
p(f'Для C сохранены все {len(candidates)} конструктивных кандидатов, из них {len(cok)} допустимы и {cfail} отвергнуты. Менялись пара региональных портов, аппарат и сдвиг времени; выборка ограничена этим семейством замкнутых маршрутов. Среди допустимых конструктивных вариантов объём составляет от {number(cok.completed_trips.min())} до {number(cok.completed_trips.max())} поездок. После отбора выполнялся CP-SAT и перераспределение пассажиров. Называть этот перебор глобальной оптимизацией всех инвестиций нельзя.')
def draw_c(f,ax):
 x=np.arange(1,len(candidates)+1);ok=candidates.feasible.astype(bool)
 ax.scatter(x[ok],candidates.loc[ok,'completed_trips']/1000,c=COLORS['C'],s=25,label='Допустимый кандидат');ax.scatter(x[~ok],np.full((~ok).sum(),.025),transform=ax.get_xaxis_transform(),marker='x',s=14,color='#88929e',label='Отклонён (нет результата)');ax.axhline(485.1,color=COLORS['B'],ls='--',label='C после CP-SAT и аллокации');ax.set(xlabel='Порядковый номер конструктивного кандидата',ylabel='Завершённые поездки, тыс.',xlim=(0,76));ax.legend(fontsize=7);ax.grid(alpha=.4)
fig('c_candidates','Полный сохранённый конструктивный перебор регионального варианта','regional/candidate_results.csv','Абсцисса показывает порядковый номер от 1 до 75, а не время и не расстояние; идентификаторы доступны в CSV. Ордината показывает поездки допустимого расписания. Серые крестики вдоль нижней рамки отмечают отвергнутые варианты и не имеют численного значения Y. Пунктир обозначает финальный результат C после других стадий, поэтому не является верхней границей перебора.',draw_c)
h('13. Дополнительные закономерности данных и ограничений')
p('Для анализа разведены четыре единицы учёта: OD-поездка от начального до конечного пункта, пассажирский участок рейса, сам рейс и год эксплуатации актива. Одна пересадка увеличивает число пассажирских участков, но не число завершённых OD-поездок. Строки расписания описывают типичные сутки каждого года, а годовой объём получается повторением этих суток 330 раз. Поэтому суммы строк разных лет не означают единственное реальное трёхдневное расписание.')
tab('Таблица R6. Перевозки и загрузка без двойного учёта пересадок',['Вариант','OD-поездки','Пасс.-участки','Загрузка мест','Разных OD'],[[x.variant,number(x.trips),number(x.passenger_legs),f'{x.load_factor*100:.2f}%',str(x.served_od_pairs)] for x in facts.itertuples()])
a=facts.set_index('variant').loc['A'];b=facts.set_index('variant').loc['B'];c=facts.set_index('variant').loc['C'];ao=ods[ods.variant=='A'];short=ao.distance_km<20
p(f'В A все {int(a.flights)} рейсов типичных суток трёх лет полностью загружены. При этом {int(a.short_flights_20km)} рейсов короче 20 км; минимальный участок составляет {a.min_flight_km:.2f} км. На OD-пары короче 20 км приходится {ao.loc[short,"demand"].sum()/ao.demand.sum()*100:.2f}% заданного спроса и {ao.loc[short,"served"].sum()/ao.served.sum()*100:.2f}% обслуженных поездок A. Модель считает завершённые поездки, не пассажиро-километры и не выигрыш времени относительно автомобиля. Поэтому она может предпочитать очень короткие связи. Их практическую целесообразность нельзя подтвердить без наземного времени в пути, стоимости доступа к порту и цены билета.')
def draw_dist(f,ax):
 def ecdf(v,w,label,style='-'):
  idx=np.argsort(v);v=np.asarray(v)[idx];w=np.asarray(w)[idx];ax.step(v,np.cumsum(w)/sum(w)*100,where='post',label=label,ls=style)
 ecdf(ao.distance_km,ao.demand,'Весь OD-спрос','--')
 for tag in variants:
  z=ods[ods.variant==tag];ecdf(z.distance_km,z.served,'Обслужено '+tag)
 ax.set(xlabel='Прямое расстояние между началом и концом OD, км',ylabel='Накопленная доля поездок, %',xlim=(0,650),ylim=(0,102));ax.legend();ax.grid(alpha=.4)
fig('od_distance_ecdf','Какие расстояния обслуживаются относительно структуры спроса','od_coverage.csv','Абсцисса показывает геодезическое расстояние между началом и концом поездки в километрах, включая OD с пересадкой. Ордината показывает долю соответствующего объёма на расстояниях не больше X. Пунктир взвешен всем заданным спросом, отдельные линии A, B и C взвешены завершёнными поездками каждой версии. Это накопленные доли с разными знаменателями, а не доли удовлетворения спроса.',draw_dist)
p(f'В C число OD-поездок равно {number(c.trips)}, а пассажирских участков {number(c.passenger_legs)}. Разница {number(c.transfer_extra_legs)} соответствует шести дополнительным участкам в типичных сутках, повторённым 330 раз. Считать её новыми поездками было бы ошибкой. В B загрузка мест составляет {b.load_factor*100:.2f}%, в C {c.load_factor*100:.2f}%; число обслуженных направленных OD-пар равно соответственно {int(b.served_od_pairs)} и {int(c.served_od_pairs)} из 870 возможных пар фиксированной выборки.')
def draw_resource(f,ax):
 y=np.arange(3);ax.barh(y,facts.flight_share*100,label='Перелёт');ax.barh(y,facts.charge_share*100,left=facts.flight_share*100,label='Зарядка');ax.barh(y,facts.wait_share*100,left=(facts.flight_share+facts.charge_share)*100,label='Ожидание / резерв');ax.set_yticks(y,facts.variant);ax.set(xlabel='Доля времени приобретённого флота в рабочем окне, %',ylabel='Вариант',xlim=(0,100));ax.legend(loc='upper center',bbox_to_anchor=(.5,1.16),ncols=3)
fig('fleet_time','Время флота: полёт, полная зарядка и ожидание','operational_facts.csv; flights_and_schedule.csv','Абсцисса показывает процент суммарного фонда времени аппаратов в типичных сутках всех лет их эксплуатации; один аппарат-год даёт 720 минут. Ордината разделяет варианты. Перелёт включает округлённую длительность и посадку, зарядка учитывается после каждого рейса, остаток включает ожидание и неиспользованный резерв. Межгодовые перемещения вне рабочего дня в эти полосы не входят.',draw_resource)
y3=resource[(resource.variant=='A')&(resource.year==3)];sat=int(y3.saturated_windows.sum());windows=len(y3)*8
p(f'В A полёт занимает {a.flight_share*100:.1f}% фонда рабочего времени приобретённого флота, зарядка {a.charge_share*100:.1f}%, ожидание и резерв {a.wait_share*100:.1f}%. Это не оценка возможности немедленно добавить рейсы: в третьем году уже насыщены {sat} из {windows} фиксированных 90-минутных портовых окон. Максимум одновременно занятых зарядных мест по действующим портам равен {int(y3.peak_chargers.max())} из двух. Наблюдение показывает, что свободные часы аппарата и зарядные места сами по себе не снимают ограничение движений; причинный эффект изменения лимита потребовал бы отдельного расчёта.')
def draw_ports(f,ax):
 z=resource[(resource.variant=='A')&(resource.year==3)].sort_values('saturated_windows');y=np.arange(len(z));ax.barh(y,z.saturated_windows,label='Окна с двумя движениями');ax.set_yticks(y,z.port,fontsize=8);ax.set(xlabel='Насыщенных 90-минутных окон из восьми',ylabel='Действующий порт A, третий год',xlim=(0,8));ax.grid(axis='x',alpha=.4)
fig('port_windows','Где ограничение движений уже насыщено','port_resources.csv','Абсцисса показывает число фиксированных 90-минутных интервалов с двумя взлётами и посадками суммарно; максимум восемь. Ордината перечисляет введённые порты A в третьем году. Насыщенное окно не обязательно означает положительную двойственную цену ограничения; график описывает загрузку найденного расписания.',draw_ports,height=4.1)
rr=reach[reach.graph!='potential'];tab('Таблица R7. Пространственная и расписанная достижимость A',['Граф','Год','Проверено OD','В графе','По расписанию'],[[x.graph,str(x.year),str(x.pairs),str(x.spatial),str(x.scheduled)] for x in reach.itertuples()])
p('Для потенциального графа столбец достижимости по расписанию не рассчитывался; ноль в машинной сводке означает отсутствие такой проверки, а не доказанную недостижимость. Для построенных сетей достижимость означает наличие хронологически допустимого пути, но не свободное место на нём. Поэтому число достижимых пар нельзя приравнивать к числу реально обслуженных OD или к удовлетворённому спросу.')
# Archive retention and remaining requirements are not silently promoted by a longer article.
h('14. Полнота отчёта и границы нового анализа')
p('В основной текст добавлены ранее сжатые стадии поиска и диагностические факты. В электронных таблицах дополнительно сохранены все 75 строк параметрических экспериментов, все seed, задачи фиксированного CP-SAT, региональные кандидаты, ошибки и границы попыток MIP. Полный каталог файлов охватывает также старые коридорные расчёты, промежуточные конфигурации, журналы и исходные снимки кода. Наличие истории в архиве не означает, что все её записи сравнимы напрямую: размер задачи, модель, цель и сценарий должны совпадать.')
p('Дополнительный анализ не меняет выбранные инвестиции и не заменяет отсутствующие вычислительные доказательства. Три пункта матрицы остаются частичными: полнота географического сопоставления реестра, полноценный MIP на 30 пунктах и совместное против последовательного MIP-планирования на этом размере. Улучшенная редакция делает выполненную работу прослеживаемой, но не объявляет эти ограничения устранёнными.')
summary=dict(valid=True,run_count=len(rundf),files=len(filedf),result_records_all_runs=len(allres),unique_result_files_all_runs=int(allres.sha256.nunique()),current_records=len(cat),current_unique_results=int(cat.result_sha256.nunique()),current_investment_designs=int(cat.investment_sha256.nunique()),current_independently_validated=int(cat.valid.sum()),historical_records_not_copied_to_current=len(older),historical_unique_not_copied=int(older.sha256.nunique()),history_groups=len(history),history_files=int(history.path.nunique()),timed_a_proposals=int(a_hist.proposals.sum()),mip_attempts=len(attempts),new_figures=len(figures),optimizers_rerun=False,inventory_scope='All seven saved run directories; hashes computed before publication; original runs unchanged')
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));(O/'article_addendum.json').write_text(json.dumps(dict(blocks=blocks,figures=figures),ensure_ascii=False,indent=2))
# Attest derived data and sources, allowing an offline checker to detect drift.
outputs={p.relative_to(ROOT).as_posix():checksum(p) for p in sorted(O.glob('*.csv'))};outputs[str((O/'article_addendum.json').relative_to(ROOT))]=checksum(O/'article_addendum.json')
outputs.update({p.relative_to(ROOT).as_posix():checksum(p) for p in sorted((O/'figures').glob('*'))})
(O/'validation.json').write_text(json.dumps(dict(valid=True,checks=['All canonical plans independently validated','OD trip sums reconcile','Passenger legs minus transfers reconcile','All saved runs inventoried; file hashes recorded','History copies excluded from proposal totals'],sources={str((ROOT/'scripts/audit_research.py').relative_to(ROOT)):checksum(ROOT/'scripts/audit_research.py')},outputs=outputs),ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
