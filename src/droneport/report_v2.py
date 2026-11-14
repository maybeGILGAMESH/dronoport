"""Evidence-based figures, flowing PDF and a genuinely offline Leaflet map."""
from pathlib import Path
import html
import json
import math
import shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from shapely.geometry import shape, mapping
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, NextPageTemplate, PageBreak, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .ingest import ROOT,checksum
from .event_model import EventInstance
from .pipeline_v2 import save


def offline_map(folder,destination,result=None):
    variant='Исходный план' if result is None else 'Дополнительный поиск'
    assets=destination.parent/'assets'; assets.mkdir(parents=True,exist_ok=True)
    import requests
    dependencies={
        'leaflet.js':'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js',
        'leaflet.css':'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css',
        'LICENSE':'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/LICENSE'}
    for filename,url in dependencies.items():
        target=assets/filename
        if not target.exists():
            response=requests.get(url,timeout=60); response.raise_for_status(); target.write_bytes(response.content)
    save(assets/'sources.json',{name:dict(url=url,sha256=checksum(assets/name)) for name,url in dependencies.items()})
    boundaries=json.loads((ROOT/'data/processed/region_boundaries.geojson').read_text())
    for f in boundaries['features']: f['geometry']=mapping(shape(f['geometry']).simplify(.005,preserve_topology=True))
    allpoints=pd.read_csv(ROOT/'data/processed_v2/towns_all.csv')
    towns=pd.read_csv(folder/'towns_main.csv'); result=result if result is not None else json.loads((folder/'base/result.json').read_text())
    payload=dict(boundaries=boundaries,points=allpoints[['name_original','lat','lon']].values.tolist(),towns=towns[['place_id','name_original','lat','lon']].values.tolist(),
        flights=result['flights'],plan=result['plan'])
    template='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сеть дронопортов · автономная карта</title><link rel="stylesheet" href="assets/leaflet.css">
<style>html,body,#map{height:100%;margin:0;font:14px system-ui}#panel{position:absolute;right:12px;top:12px;z-index:1000;background:white;padding:16px;box-shadow:0 2px 12px #0003;border-radius:8px;max-width:290px}label{display:block;margin:8px 0}h1{font-size:18px;margin:0 0 8px}.note{font-size:12px;color:#536576}#map{background:#eef3f6}</style>
<div id="map"></div><div id="panel"><h1>Сеть дронопортов · И</h1><div class="note">RUNINFO</div><div class="note">Автономная схема: границы, населённые пункты и рейсы. Интернет и VPN не нужны. Дорожной подложки нет.</div>
<label><input id="all" type="checkbox"> Допустимые пункты с координатами OSM</label><label><input id="sample" type="checkbox" checked> Расчётные 30 пунктов</label>
<label><input id="y1" type="checkbox"> Год 1</label><label><input id="y2" type="checkbox"> Год 2</label><label><input id="y3" type="checkbox" checked> Год 3</label>
<div class="note">Границы и координаты: © OpenStreetMap contributors. Население: Росстат. Спрос и цены — учебные допущения.</div></div>
<script src="assets/leaflet.js"></script><script>
const data=PAYLOAD;
const map=L.map('map',{preferCanvas:true}).setView([56,35.4],7);window.projectMap=map;
L.geoJSON(data.boundaries,{style:f=>({color:f.properties.region_code==='77'?'#8c4d3e':'#698697',weight:1.5,fillOpacity:.04})}).addTo(map);
const safe=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const layers={all:L.layerGroup(),sample:L.layerGroup(),y1:L.layerGroup(),y2:L.layerGroup(),y3:L.layerGroup()};
data.points.forEach(p=>L.circleMarker([p[1],p[2]],{radius:2,color:'#899aa8',weight:0,fillOpacity:.5}).bindTooltip(safe(p[0])).addTo(layers.all));
const towns={};data.towns.forEach(p=>{towns[p[0]]=p;L.circleMarker([p[2],p[3]],{radius:4,color:'#263e50',fillOpacity:.6}).bindTooltip(safe(p[1])).addTo(layers.sample)});
for(let y=1;y<=3;y++){const color=['','#187f8c','#d28c23','#b33e58'][y],counts={};
data.flights.filter(f=>f.year===y).forEach(f=>{const key=[f.origin_id,f.destination_id].sort().join('|');counts[key]=(counts[key]||0)+1});
Object.entries(counts).forEach(([key,count])=>{const [a,b]=key.split('|').map(id=>towns[id]);L.polyline([[a[2],a[3]],[b[2],b[3]]],{color,weight:3}).bindTooltip(safe(a[1]+' — '+b[1])+': '+count+' рейсов/сутки').addTo(layers['y'+y])});
data.plan.open_years.forEach((opened,i)=>{if(opened>0&&opened<=y){const p=data.towns[i];L.circleMarker([p[2],p[3]],{radius:7,color,fillOpacity:.8}).bindTooltip(safe(p[1])).addTo(layers['y'+y])}})}
Object.entries(layers).forEach(([id,layer])=>{const el=document.getElementById(id);if(el.checked)layer.addTo(map);el.onchange=()=>el.checked?layer.addTo(map):map.removeLayer(layer)});
window.mapReady=true;
</script></html>'''
    destination.write_text(template.replace('RUNINFO',html.escape(f'{variant}: {result["completed_trips"]:,} поездок за три года. Запуск {folder.name}.')).replace('PAYLOAD',json.dumps(payload,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')


def generate(folder):
    folder=Path(folder); out=folder/'report'; figures=out/'figures'; figures.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((folder/'config.json').read_text()); towns=pd.read_csv(folder/'towns_main.csv'); inst=EventInstance(towns,cfg)
    base=json.loads((folder/'base/result.json').read_text()); robust=json.loads((folder/'robust/result.json').read_text())
    budget=pd.DataFrame(base['budget']); flights=pd.DataFrame(base['flights']); seeds=pd.read_csv(folder/'seed_results.csv')
    methods=pd.read_csv(folder/'method_comparison.csv'); exp=pd.read_csv(folder/'experiments.csv'); scenarios=pd.read_csv(folder/'scenario_results.csv')
    annual=pd.read_csv(folder/'annual_comparison.csv'); manifest=json.loads((folder/'run_manifest.json').read_text())
    registry=json.loads((ROOT/'data/processed_v2/audit.json').read_text()); allpoints=pd.read_csv(ROOT/'data/processed_v2/towns_all.csv')
    old=json.loads((folder/'comparisons/legacy_in_v2_30/result.json').read_text())
    boundaries=json.loads((ROOT/'data/processed/region_boundaries.geojson').read_text())
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.18,'figure.facecolor':'white'})
    import networkx as nx
    graph=nx.Graph();graph.add_nodes_from(range(inst.n))
    graph.add_edges_from((i,j) for i in range(inst.n) for j in range(i+1,inst.n) if inst.distance[i,j]<=cfg['range_km'])
    components=list(nx.connected_components(graph));membership={i:k for k,comp in enumerate(components) for i in comp}
    disconnected=np.array([[membership[i]!=membership[j] for j in range(inst.n)] for i in range(inst.n)])
    descriptive=dict(component_sizes=sorted(map(len,components),reverse=True),unreachable_annual_demand=[int(q[disconnected].sum()*cfg['operating_days']) for q in inst.demand],
        population_skew=float(towns.population.skew()),directional_asymmetry=float(np.abs(inst.demand[0]-inst.demand[0].T).sum()/inst.demand[0].sum()),
        population_p95=float(towns.population.quantile(.95)))
    save(out/'data_descriptive.json',descriptive)
    charts=[]
    def finish(fig,name,caption,evidence):
        fig.tight_layout(); fig.savefig(figures/(name+'.png'),dpi=160); fig.savefig(figures/(name+'.pdf')); plt.close(fig)
        charts.append(dict(name=name,caption=caption,evidence=evidence))
    def geo(ax):
        for f in boundaries['features']:
            geom=shape(f['geometry']); polygons=list(geom.geoms) if geom.geom_type=='MultiPolygon' else [geom]
            for poly in polygons:
                x,y=poly.exterior.xy; ax.plot(x,y,color='#8ca2af',lw=.7)
        ax.set(xlabel='Долгота, °',ylabel='Широта, °'); ax.set_aspect(1/math.cos(math.radians(56)))
    def network(ax,result,year):
        geo(ax); ax.scatter(towns.lon,towns.lat,s=10,color='#a4b1ba')
        pairs=set()
        for f in result['flights']:
            if f['year']!=year: continue
            pair=tuple(sorted((f['origin_id'],f['destination_id'])))
            if pair in pairs: continue
            pairs.add(pair); a,b=[towns[towns.place_id==p].iloc[0] for p in pair]; ax.plot([a.lon,b.lon],[a.lat,b.lat],color='#197f8b',lw=2)
        opened=[i for i,v in enumerate(result['plan']['open_years']) if 0<v<=year]
        if opened: ax.scatter(towns.iloc[opened].lon,towns.iloc[opened].lat,s=28,color='#b63e58',zorder=4)
    fig,ax=plt.subplots(figsize=(9,6)); geo(ax); ax.scatter(allpoints.lon,allpoints.lat,s=2,alpha=.35,color='#adb9c0',label=f'OSM с координатами: {len(allpoints)}')
    for k,comp in enumerate(components):
        selected=towns.iloc[sorted(comp)];ax.scatter(selected.lon,selected.lat,s=22,label=f'Компонента {k+1}: {len(comp)} пунктов')
    ax.legend(fontsize=8); ax.set_title('Территория, фиксированная выборка и связность при 200 км')
    finish(fig,'01_registry','Карта показывает извлечённые OSM-объекты с координатами. Полный официальный перечень и неоднозначные сопоставления ГАР сохранены отдельно; координаты не выдумываются.','data/processed_v2/towns_all.csv; registry_gar.csv; towns_main.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); axs[0].hist(np.log10(towns.population),bins=10,color='#197f8b'); axs[0].set(xlabel='log₁₀ населения',ylabel='Пунктов',title='Население фиксированной выборки')
    for code,name,color in [(50,'Московская','#197f8b'),(67,'Смоленская','#d28c23'),(69,'Тверская','#b63e58')]:
        vals=towns[towns.region_code==code].population; axs[1].scatter([name]*len(vals),vals,color=color)
    axs[1].set(yscale='log',ylabel='Человек, логарифмическая шкала',title='Региональные различия')
    finish(fig,'02_population','Показаны наблюдаемые значения Росстата 2021 года; пропуски не восстановлены.','towns_main.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); axs[0].hist(inst.distance[np.triu_indices(inst.n,1)],bins=20,color='#197f8b'); axs[0].axvline(200,color='#b63e58'); axs[0].set(xlabel='Расстояние, км',ylabel='Пар',title='Геодезические расстояния')
    axs[1].hist(inst.demand[0][~np.eye(inst.n,dtype=bool)],bins=25,color='#d28c23'); axs[1].set(xlabel='Поездок/типичные сутки',ylabel='Направленных OD',title='Синтетический спрос, год 1')
    finish(fig,'03_distances_demand','Красная линия — базовая дальность. Спрос задан до оптимизации.','config.json; towns_main.csv')
    fig,ax=plt.subplots(figsize=(9,7)); im=ax.imshow(np.log1p(inst.demand[0]),cmap='YlGnBu'); fig.colorbar(im,ax=ax,label='ln(1 + поездок/сутки)'); ax.set(xticks=range(30),yticks=range(30),xlabel='Назначение',ylabel='Отправление',title='Направленная матрица спроса первого года'); ax.set_xticklabels(towns.name_original,rotation=90,fontsize=9); ax.set_yticklabels(towns.name_original,fontsize=9)
    finish(fig,'04_od_matrix','Асимметрия задана разными степенями населения отправления и назначения.','config.json; towns_main.csv')
    fig,axs=plt.subplots(1,3,figsize=(13,6))
    for y,ax in enumerate(axs,1): network(ax,base,y); ax.set_title(f'Год {y}: {base["annual_completed"][y-1]:,} поездок')
    finish(fig,'05_network_years','Красные точки — открытые порты; линии — фактически выполняемые рейсы.','base/result.json')
    fig,axs=plt.subplots(1,2,figsize=(11,6)); network(axs[0],old,3)
    network(axs[1],base,3); axs[0].set_title(f'Прежняя модель: {old["completed_trips"]:,}'); axs[1].set_title(f'Свободные ротации: {base["completed_trips"]:,}')
    finish(fig,'06_model_comparison','Одинаковые 30 пунктов и спрос. Старое расписание перенесено на новую сетку и независимо проверено без изменения пассажиров. Рост найденного результата относится к расширению модели и процедур поиска.','base/result.json; comparisons/legacy_lift.json')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); bottom=np.zeros(3)
    for key,label in [('port_capex_rub','Порты CAPEX'),('aircraft_capex_rub','Флот CAPEX'),('port_opex_rub','Порты OPEX'),('aircraft_opex_rub','Флот OPEX'),('energy_rub','Энергия'),('relocation_energy_rub','Перегоны')]:
        if key not in budget: continue
        vals=budget[key].to_numpy()/1e6; axs[0].bar(budget.year,vals,bottom=bottom,label=label); bottom+=vals
    axs[0].plot(budget.year,budget.available_rub/1e6,'ko--',label='Доступно'); axs[0].set(xticks=[1,2,3],ylabel='Млн руб.',title='Ежегодное финансирование'); axs[0].legend(fontsize=7)
    axs[1].bar(budget.year,budget.carry_rub/1e6,color='#197f8b'); axs[1].set(xticks=[1,2,3],ylabel='Млн руб.',title='Переносимый остаток')
    finish(fig,'07_budget','Транши поступают в начале года; будущие транши не используются.','base/budget_by_year.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); demand=inst.demand.sum(axis=(1,2))*cfg['operating_days']; done=np.array(base['annual_completed'])
    axs[0].bar([1,2,3],done/1000,label='Завершено'); axs[0].set(xticks=[1,2,3],ylabel='Тысяч поездок',title='Перевозки по годам')
    axs[1].bar([1,2,3],100*done/demand,color='#197f8b',label='Обслужен');axs[1].bar([1,2,3],100*(1-done/demand),bottom=100*done/demand,color='#dce5e9',label='Не обслужен'); axs[1].set(xticks=[1,2,3],ylabel='% спроса',title='Обслуженный и неудовлетворённый спрос');axs[1].legend(fontsize=8)
    finish(fig,'08_service','Знаменатель включает весь синтетический OD-спрос фиксированной выборки, включая недостижимые пары.','base/result.json; config.json')
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for method,group in methods.groupby('method'):
        axs[0].plot(group.instance,group.completed_trips/1000,'o-',label=method); axs[1].plot(group.instance,group.wall_seconds,'o-',label=method)
    axs[0].set(xlabel='Пунктов',ylabel='Тысяч поездок',title='Качество методов'); axs[1].set(xlabel='Пунктов',ylabel='Секунды, log',yscale='log',title='Время; annealing_best — сумма серии'); axs[0].legend(fontsize=7)
    finish(fig,'09_methods','Отсутствующая точка MIP означает отсутствие опубликованного допустимого результата; статусы приведены в таблице решателя.','method_comparison.csv; mip_reports.json')
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for n,group in seeds.groupby('instance'): axs[0].scatter([n]*len(group),group.completed_trips/1000,alpha=.6)
    trace=pd.read_csv(folder/'search_history.csv')
    for seed,g in trace[trace.instance==30].groupby('seed'): axs[1].plot(g.elapsed,g.best/1000,alpha=.7,label=str(seed))
    axs[0].set(xlabel='Пунктов',ylabel='Тысяч поездок',title='Все seed без сокрытия совпадений'); axs[1].set(xlabel='Время запуска, с',ylabel='Лучшее, тыс. поездок',title='Траектории отжига, 30 пунктов')
    finish(fig,'10_randomness','Общие входы и начальное greedy-решение; случайны изменения и принятие ухудшений.','seed_results.csv; search_history.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); g=methods[methods.method=='greedy']; axs[0].plot(g.instance,g.wall_seconds,'o-'); axs[1].plot(g.instance,g.served_share*100,'o-'); axs[0].set(xlabel='Пунктов',ylabel='Секунды',title='Масштаб: время greedy'); axs[1].set(xlabel='Пунктов',ylabel='% спроса',title='Масштаб: доля обслуживания')
    finish(fig,'11_scale','Рост абсолютных перевозок сам по себе не означает рост доли обслуженного спроса.','method_comparison.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,4)); g=exp[exp.experiment=='budget'].sort_values('value'); axs[0].plot(g.value,g.completed_trips/1000,'o-',ms=3); axs[1].step(g.value,g.ports,where='mid',label='Порты'); axs[1].step(g.value,g.fleet,where='mid',label='Аппараты'); axs[1].legend(); axs[0].set(xlabel='Ежегодный транш, млн руб.',ylabel='Тысяч поездок',title='Лучшие допустимые бюджетные планы'); axs[1].set(xlabel='Млн руб./год',ylabel='Объектов',title='Изменения структуры инвестиций')
    finish(fig,'12_finance','Сетка 50/10 млн. План меньшего бюджета проверяется как кандидат при большем бюджете; значения не сглаживаются. Первичные greedy-результаты сохранены. Это не доказанная граница.','experiments.csv; experiments_raw.csv; experiments_portfolio/budget_*')
    reference=float(methods[(methods.instance==30)&(methods.method=='greedy')].completed_trips.iloc[0])
    translated={'port_capex_rub':'CAPEX порта ×','aircraft_capex_rub':'CAPEX аппарата ×','port_opex_rub_per_year':'OPEX порта ×','aircraft_opex_rub_per_year':'OPEX аппарата ×','flight_speed_kmh':'Скорость ×','charging_minutes':'Зарядка, мин:','demand.gamma':'Затухание спроса γ =','demand.yearly_growth':'Годовой множитель спроса:','quality_cap':'Квантиль ограничения населения:'}
    fig,ax=plt.subplots(figsize=(11,7)); g=exp[~exp.experiment.isin(['budget','grid_small'])].copy(); labels=[f'{translated.get(r.experiment,r.experiment)} {r.value:g}' for r in g.itertuples()]
    if 'raw_completed_trips' in g:ax.barh(labels,(g.raw_completed_trips/reference-1)*100,color='#ced9dd',label='Первичный greedy')
    ax.barh(labels,(g.completed_trips/reference-1)*100,color='#197f8b',height=.45,label='С допустимым исходным планом'); ax.axvline(0,color='black'); ax.set(xlabel='Изменение к greedy при исходных параметрах, %',title='Чувствительность найденных допустимых планов'); ax.tick_params(axis='y',labelsize=8);ax.legend(fontsize=8)
    finish(fig,'13_sensitivity','Исходный инвестиционный план дополнительно проверен при изменённых параметрах. Эффект скорости зависит от временной сетки и эвристики; он не является доказанной физической зависимостью.','experiments.csv; experiments_raw.csv; experiments_portfolio/*/config.json')
    fig,ax=plt.subplots(figsize=(12,5)); day=flights[flights.year==3]; aircraft=sorted(day.aircraft_id.unique()); positions={a:i for i,a in enumerate(aircraft)}
    for f in day.itertuples():
        y=positions[f.aircraft_id]; ax.broken_barh([(f.departure_min/60,(f.arrival_min-f.departure_min)/60)],(y-.3,.6),facecolors='#197f8b'); ax.broken_barh([(f.arrival_min/60,(f.charge_end_min-f.arrival_min)/60)],(y-.3,.6),facecolors='#d28c23')
    ax.set(yticks=range(len(aircraft)),yticklabels=aircraft,xlim=[8,20],xlabel='Часы суток',ylabel='Аппарат',title='Год 3: перелёты (синий), зарядки (жёлтый), ожидание (пробелы)')
    finish(fig,'14_schedule','Проверяются непрерывность маршрута, возврат на базу, места зарядки и ограничения движений.','base/flights_and_schedule.csv')
    fig,axs=plt.subplots(1,2,figsize=(12,6))
    failure_ids=sorted(set(scenarios[scenarios.scenario.str.startswith('failed_')].scenario))
    point_names=dict(zip(towns.place_id,towns.name_original))
    for label,g in scenarios.groupby('plan'):
        failed=g[g.scenario.str.startswith('failed_')].set_index('scenario'); vals=[failed.loc[key,'completed_trips']/1000 if key in failed.index else np.nan for key in failure_ids]
        axs[0].scatter(vals,range(len(failure_ids)),label=label)
        vals=[g[g.scenario=='base'].completed_trips.iloc[0],g.completed_trips.min()]; axs[1].bar(np.arange(2)+(-.18 if label=='base' else .18),np.array(vals)/1000,width=.36,label=label)
    axs[0].set(xlabel='Тысяч поездок',yticks=range(len(failure_ids)),yticklabels=[point_names.get(key[7:],key[7:]) for key in failure_ids],title='Отказы построенных портов'); axs[0].tick_params(axis='y',labelsize=8); axs[0].legend(); axs[1].set(xticks=[0,1],xticklabels=['Базовый сценарий','Худший сценарий'],ylabel='Тысяч поездок',title='Цена устойчивости'); axs[1].legend()
    finish(fig,'15_robustness','Наборы портов планов различаются. Значения отражают найденное допустимое перепланирование, а не доказанный оптимум восстановления.','scenario_results.csv; scenarios/*/*/validation.json')
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for mode,g in annual[annual.instance==30].groupby('mode'):
        axs[0].plot(g.year,g.completed_trips/1000,'o-',label=mode); axs[1].plot(g.year,g.spend_rub/1e6,'o-',label=mode)
    axs[0].set(xticks=[1,2,3],ylabel='Тысяч поездок',title='Последовательное и совместное планирование'); axs[1].set(xticks=[1,2,3],ylabel='Млн руб.',title='Годовые расходы'); axs[0].legend(); axs[1].legend()
    finish(fig,'16_years','Текущая реализация сравнивает последовательный greedy и поиск с трёхлетней оценкой; это не сравнение двух доказанных MIP-оптимумов.','annual_comparison.csv')
    paths=pd.read_csv(folder/'bfs_astar.csv'); reachable=paths[paths.reachable]
    fig,axs=plt.subplots(1,2,figsize=(11,4)); axs[0].scatter(reachable.bfs_minutes,reachable.astar_minutes,s=6,alpha=.25); top=max(reachable.bfs_minutes.max(),reachable.astar_minutes.max()); axs[0].plot([0,top],[0,top],'k--'); axs[0].set(xlabel='BFS, мин',ylabel='A*, мин',title='Достижимые пары: качество маршрута')
    built=paths[paths.graph=='built']; counts=built.groupby('year')[['reachable','schedule_reachable']].sum(); counts.plot.bar(ax=axs[1]); axs[1].set(ylabel='Направленных OD',title='Графовая и временная достижимость'); axs[1].legend(['По графу','По расписанию'],fontsize=8)
    finish(fig,'17_paths','Поиск по пространственному графу не гарантирует существование подходящей пересадки по времени. A* проверен Дейкстрой.','bfs_astar.csv')
    mip_year_rows=[]
    for n in (8,30):
        for mode,path in [('joint',folder/'scale'/str(n)/'mip/result.json'),('sequential',folder/'sequential_mip'/str(n)/'result.json')]:
            if path.exists():
                r=json.loads(path.read_text())
                mip_year_rows += [dict(instance=n,mode=mode,**b,completed_trips=r['annual_completed'][i]) for i,b in enumerate(r['budget'])]
    if mip_year_rows:
        mf=pd.DataFrame(mip_year_rows); mf.to_csv(out/'mip_annual_comparison.csv',index=False)
        fig,axs=plt.subplots(1,2,figsize=(11,4))
        for (n,mode),g in mf.groupby(['instance','mode']):
            axs[0].plot(g.year,g.completed_trips/1000,'o-',label=f'{n}, {mode}'); axs[1].plot(g.year,g.spend_rub/1e6,'o-',label=f'{n}, {mode}')
        axs[0].set(xticks=[1,2,3],ylabel='Тысяч поездок',title='MIP: фактически найденные планы'); axs[1].set(xticks=[1,2,3],ylabel='Млн руб.',title='MIP: инвестиции и эксплуатация'); axs[0].legend(fontsize=8);axs[1].legend(fontsize=8)
        finish(fig,'18_mip_years','При поэтапном решении прошлые инвестиции и рейсы фиксируются. Пропущенная серия означает отсутствие допустимого результата в лимитах.','scale/*/mip/result.json; sequential_mip/*/result.json')
    transfer=json.loads((folder/'examples/transfer.json').read_text());empty=json.loads((folder/'examples/empty_return/result.json').read_text())
    fig,axs=plt.subplots(1,2,figsize=(12,5));names=dict(zip(towns.place_id,towns.name_original))
    for k,f in enumerate(transfer['legs']):
        axs[0].broken_barh([(f['departure_min']/60,(f['arrival_min']-f['departure_min'])/60)],(k-.22,.44),facecolors='#197f8b')
        axs[0].text(f['departure_min']/60,k+.28,names[f['origin_id']]+' → '+names[f['destination_id']],fontsize=8)
    first,second=transfer['legs'][:2];axs[0].plot([first['arrival_min']/60,second['departure_min']/60],[0,1],'--',color='#d28c23')
    axs[0].set(yticks=range(len(transfer['legs'])),yticklabels=[f['aircraft_id'] for f in transfer['legs']],xlabel='Часы суток',ylabel='Аппарат',title='Одна поездка, смена аппарата')
    fs=[f for f in empty['flights'] if f['year']==1]
    for k,f in enumerate(fs):
        axs[1].broken_barh([(f['departure_min']/60,(f['arrival_min']-f['departure_min'])/60)],(k-.22,.44),facecolors='#b63e58' if f['empty'] else '#197f8b')
        axs[1].text(f['departure_min']/60,k+.27,f'Пасс.: {f["passengers"]}; энергия: {f["energy_cost_rub"]} руб.',fontsize=8)
    axs[1].set(yticks=range(len(fs)),yticklabels=[names[f['origin_id']]+' → '+names[f['destination_id']] for f in fs],xlabel='Часы суток',title='Проверочный пример: порожний возврат')
    finish(fig,'19_transfer_empty','Слева — реальная смена аппарата из вычислительного результата. Справа — отдельный синтетический спрос с известным ответом 990 поездок за три года; обратный рейс оплачивается без пассажиров.','examples/transfer.json; examples/empty_return/result.json; examples/empty_return/example_scope.json')
    quality_row=exp[exp.experiment=='quality_cap'].iloc[0]
    quality_path=folder/quality_row.get('result_path','experiments/quality_cap_0.95/result.json')
    if quality_path.is_dir():quality_path=quality_path/'result.json'
    quality=json.loads(quality_path.read_text());greedy_result=json.loads((folder/'scale/30/greedy/result.json').read_text())
    fig,axs=plt.subplots(1,2,figsize=(11,6));network(axs[0],greedy_result,3);network(axs[1],quality,3)
    axs[0].set_title(f'Исходное население: {greedy_result["completed_trips"]:,}');axs[1].set_title(f'Влияние ограничено P95: {quality["completed_trips"]:,}')
    finish(fig,'20_quality_network','Сравниваются правила построения синтетического спроса при сохранённых исходных наблюдениях. Крупное население не объявляется ошибкой; одинаковый результат допустим.','scale/30/greedy/result.json; experiments.csv; experiments_portfolio/quality_cap_0.95/result.json')
    save(out/'figure_manifest.json',charts)
    mips=json.loads((folder/'mip_reports.json').read_text()) if (folder/'mip_reports.json').exists() else []
    game=json.loads((folder/'minimax_results.json').read_text())
    worst=scenarios.groupby('plan').completed_trips.min().to_dict()
    def num(v): return f'{v:,.0f}'.replace(',',' ')
    blocks=[
      ('Постановка и результат',f'Вариант И: Московская, Смоленская и Тверская области; буквы ЖЗИКЛ. Основная выборка — 30 пунктов, малая — 8. Запуск {folder.name}. Базовый план даёт {num(base["completed_trips"])} завершённых поездок за три года, {base["completed_trips"]/demand.sum():.2%} синтетического спроса. Стоимость {num(budget.spend_rub.sum())} руб. Это допустимый найденный план, а не доказанный глобальный оптимум.'),
      ('Данные и происхождение',f'Извлечение дополнено полигонами поселений: {registry["added_polygons"]} дополнительных объектов трёх областей, всего {registry["eligible"]} допустимых пунктов. Вычислительные 30/8 пунктов сохранены для сравнимости. Население — Росстат, наблюдение 01.10.2021; координаты — OSM 03.11.2026. Таблица 5 Росстата охватывает городские и сельские поселения от 3000 жителей, поэтому не подтверждает полноту реестра малых поселений. Проверены {registry["official_rows_checked"]} подходящих строк официальной таблицы; требуется дополнительная сверка ГАР. Пропуски сохранены.'),
      ('Спрос и качество данных','q(i,j,t)=floor(0.003 P_i^0.55 P_j^0.45 /(1+d_ij/50)^1.5 × 1.05^(t−1)); 330 типичных суток в году. Годовой спрос — суточный × 330. Исходное население не меняется. Второй вариант качества данных ограничивает только вход населения в формулу спроса 95-м процентилем фиксированной выборки: это чувствительность к экстремальным значениям, а не утверждение об ошибке официальных данных. Удалённые пункты и недостижимые OD остаются в анализе.'),
      ('Техника, время и финансы','10 мест, дальность 200 км; полный заряд после каждого перелёта. Скорость 240 км/ч, посадка 5 минут, зарядка 30 минут. Сетка 10 минут с округлением длительностей вверх, рабочее окно 08:00–20:00. Два зарядных места; максимум два движения суммарно в каждом фиксированном 90-минутном интервале. Порты и флот приобретаются в начале года и сохраняются. Транш 1 млрд руб./год, остаток переносится. Энергия оплачивается по всем выполненным рейсам, включая порожние. Цены — учебные допущения из config.json, анализ чувствительности сохранён отдельно.'),
      ('Математическая постановка','x_it — открытый порт; b_it — приобретённые аппараты базы i; a^h_ijt — целочисленные движения аппаратов базы h по временным дугам; f^d_ijt — пассажирские потоки к назначению d; s_od — завершённые поездки. Максимизируется 330 Σ s_od по трём годам. На временных узлах сохраняются потоки аппаратов и пассажиров; Σ_d f ≤ 10 Σ_h a. Начальный и конечный запас каждого типа аппаратов совпадает в его базе. Рейс связан с открытием обоих портов, ограничениями дальности, зарядок и движений. Для каждой OD s≤q. Накопленные CAPEX+OPEX+энергия ≤ накопленных траншей. Разложение целочисленных потоков восстанавливает отдельные аппараты и пассажирские маршруты.'),
      ('Область применимости','В новой версии аппарат меняет направления, число и время рейсов выбираются; пассажиры используют все пути фактического расписания. Сохраняются полная зарядка после каждого перелёта и дискретное время. Конструктивный поиск рассматривает двух- и трёхзвенные обороты, а MIP допускает произвольные ротации временного графа. Базы доставки пока закреплены между годами: межгодовое перебазирование не реализовано. Поэтому расширение модели существенно, но утверждать выполнение всего первоначального плана нельзя.'),
      ('Методы и вычислительный протокол','Greedy ранжирует добавления по приросту допустимых перевозок на рубль; перебирает 12 наиболее перспективных пар по исходному спросу. Отжиг меняет год открытия, базу, закупки и seed расписания; восстанавливает сроки ввода и удаляет закупки при дефиците бюджета. Остановка: 200 итераций либо 600 секунд; все seed и траектории опубликованы. MIP имеет лимит 1800 секунд и защиту размера матрицы для доступной RAM. Отсутствие решения или срабатывание защиты не обозначается нулевым разрывом.'),
      ('Расписание и независимая проверка',f'Сохранены расписания всех трёх типичных суток: {len(base["flights"])} рейсов; поездок с пересадкой {sum(t["transfers"]>0 for t in base["itineraries"])}; порожних рейсов {sum(f["empty"] for f in base["flights"])}. Независимая проверка пересчитывает расстояния, часы работы, движения, зарядки, владение флотом, пересадки, спрос и бюджет. Для каждого опубликованного экспериментального плана есть validation.json. Состояние решателя OPTIMAL относится только к соответствующей задаче, а не ко всему проекту.'),
      ('Эксперименты и статистика','Размеры 8/12/20/30, по 10 seed. Бюджеты 250–1000 млн с шагом 50 млн и уточнением до 10 млн в интервалах изменения числа объектов. Выполнены изменения CAPEX/OPEX ±20%, скорости ±20%, зарядки 20/45 минут, параметра расстояния 1.2/1.8, годового роста 0/10%, сетки 5/15 минут на малой задаче. Сравнения описательные и парные на фиксированных входах; ANOVA не используется. Seed отражают вариативность поиска, а не независимые выборки реального пассажиропотока.'),
      ('Стресс-тесты и робастность',f'Проверены спрос ±30%, дальность 160 км и каждый отказ построенного порта. Флот и инвестиции сохраняются, расписание пересоставляется; базирующиеся в отказавшем порту аппараты блокируются. Постоянные расходы сохраняются, энергия пересчитывается. Худший найденный результат базы: {num(worst["base"])}; робастного плана: {num(worst["robust"])}. Робастный план в базе: {num(robust["completed_trips"])}. Это эвристический maximin по найденному восстановлению; глобальная робастная оптимальность не доказана.'),
      ('Поиск путей и игра',f'BFS минимизирует число перелётов, A* — сумму времени полёта, посадки и зарядки. Эвристика — геодезическое расстояние / скорость; результат каждой достижимой пары сверяется с Дейкстрой. Для построенных сетей отдельно проверяется временная достижимость. Игра содержит {game["network_actions"]} различных планов: выбор сети → отказ узла → отмена затронутых ротаций либо эвристическое перепланирование. Полный обход: {game["full"]["visited_nodes"]} узлов; альфа-бета: {game["alpha_beta"]["visited_nodes"]}; значение обоих {num(game["full"]["value"])}. Дерево и листья сохранены.'),
      ('Выводы и незакрытые пункты','Добавлены свободные ротации, пересадки, обязательные эксперименты и автономная карта. Остаются: полнота официального реестра; межгодовое перебазирование; сравнение совместного и последовательного MIP; решение крупных MIP при ограниченной памяти. Результаты не являются оценкой спроса реального авиасервиса: не учтены тарифы и конкуренция наземного транспорта. ИИ использован для разработки кода, аудита и подготовки текста; вычислительные результаты получены программами. На защите требуется самостоятельно объяснить модель и ограничения.')]
    gar_path=ROOT/'data/processed_v2/gar_audit.json'
    if gar_path.exists():
        gar=json.loads(gar_path.read_text())
        blocks[1]=('Данные и происхождение',f'OSM-извлечение дополнено полигонами: {registry["added_polygons"]} дополнительных объектов трёх областей, {registry["eligible"]} допустимых объектов с координатами. Вычислительные 30/8 пунктов сохранены. Население — Росстат, 01.10.2021; координаты — OSM 03.11.2026. Из официального архива ФНС ГАР 03.11.2026 выборочно получены адресные объекты регионов 50/67/69: {gar["active_official_settlements"]} действующих поселений заданных типов, {gar["eligible_official_settlements"]} на нужные буквы. Города могут иметь административный уровень 2, поэтому отбор учитывает и тип объекта. Муниципальные образования не принимаются за населённые пункты. Полный список в рамках опубликованных типов сохранён; {gar["matched_coordinates"]} записей однозначно сопоставлены с координатами OSM, {gar["unresolved_official_rows"]} остаются неразрешёнными. Пропуски населения и координат не заполняются. Источники, выбранные члены ZIP и SHA-256: gar_sources.json; официальный URL: {gar["source_url"]}.')
    blocks[4]=(blocks[4][0],blocks[4][1]+' Между годами запас аппаратов в каждой базе равен прежнему запасу плюс покупки плюс прибывшие перегоны минус выбывшие. Энергия перегонов входит в бюджет один раз, энергия типичных суток — с множителем 330. Суточный спрос доступен с начала рабочего окна; профиль спроса по часам не задан.')
    blocks[3]=(blocks[3][0],blocks[3][1]+' CAPEX порта 90 млн руб. включает оснащение и зарядные места; CAPEX аппарата 250 млн руб. OPEX порта 12 млн и аппарата 18 млн руб./год агрегирует персонал, содержание, обслуживание и ремонт. Энергия 4 кВт·ч/км по 10 руб./кВт·ч. Цены постоянны по годам, инфляция и выручка не входят в бюджет. Ввод — начало года; 330 одинаковых эксплуатационных суток, остальные 35 дней оставлены для обслуживания и межгодовых перегонов.')
    blocks[5]=('Область применимости','В новой версии аппарат меняет направления, число и время рейсов выбираются; пассажиры используют все пути фактического расписания. Сохраняются полная зарядка после каждого перелёта и дискретное время. Конструктивный поиск рассматривает двух- и трёхзвенные обороты, а MIP допускает произвольные ротации временного графа. Межгодовое перебазирование выполняется реальными порожними перегонами в неэксплуатационные дни; энергия оплачивается однократно. Объекты и флот в стресс-тестах фиксированы. Введённые ограничения являются учебными предположениями, а не характеристиками сертифицированного воздушного судна.')
    blocks[7]=(blocks[7][0],blocks[7][1]+f' Межгодовых перегонных участков в базовом плане: {len(base.get("relocations",[]))}; их расписание и энергия сохранены отдельно.')
    timed_path=folder/'time_budget_study/manifest.json'
    if cfg.get('annealing_iterations')==0 and timed_path.exists():
        timed=json.loads(timed_path.read_text())
        blocks[6]=('Методы и вычислительный протокол',f'Greedy ранжирует допустимые добавления по приросту перевозок на рубль; проверяет 12 перспективных пар по спросу. Отжиг меняет годы открытия, закупки, межгодовые базы и расписание. Основная серия: 10 seed на каждом размере, по {timed["seconds_per_seed"]:g} секунд; предварительная серия по 200 итераций сохранена отдельно. Одновременно работали до {timed["workers"]} процессов, поэтому время включает конкуренцию за ресурсы. Сумма времён 40 запусков {timed["summed_worker_seconds"]:.1f} с; последний возобновлённый этап {timed["wall_seconds"]:.1f} с, ранее завершено {timed.get("resumed_count",0)} запусков. Для сравнения быстродействия это не изолированный CPU-бенчмарк. Совместный MIP получает 1800 с на экземпляр; последовательный — по 600 с на год, суммарно столько же. Состояния до прерывания и незавершённые попытки хранятся отдельно. Увеличение времени отжига меняет темп охлаждения и не гарантирует улучшения; основной план выбирается среди всех проверенных известных решений, а серии сравниваются раздельно.')
    blocks[8]=(blocks[8][0],blocks[8][1]+' Для бюджетной зависимости дополнительно проверены найденные планы меньших бюджетов. В чувствительности исходный инвестиционный план включён как кандидат при новых параметрах. Первичные результаты сохранены в experiments_raw.csv. Отрицательный эффект увеличения скорости в найденном плане может возникать из-за сетки и эвристики; он не доказывает ухудшение оптимума физической системы.')
    if (folder/'deployment_polish/manifest.json').exists():
        blocks[8]=(blocks[8][0],blocks[8][1]+' Отдельный этап deployment_polish удаляет неиспользуемые активы при сохранении допустимого расписания, затем проверяет добавление аппарата и, при необходимости, его базы. Не более шести шагов, перебор годов и пунктов. Его время показывается отдельно и добавляется к затратам на получение исходного плана; результаты seed не переписываются. Для бюджетной кривой дополнительно проверена допустимость итогового расписания при каждом транше. Это портфель нижних оценок с разными вычислительными затратами, а не одинаковый бюджет поиска в каждой точке.')
    robust_cost=sum(b['spend_rub'] for b in robust['budget']);base_cost=int(budget.spend_rub.sum())
    blocks[9]=(blocks[9][0],blocks[9][1]+f' Цена устойчивости: потеря {num(base["completed_trips"]-robust["completed_trips"])} поездок в базе, изменение расходов {num(robust_cost-base_cost)} руб.; выигрыш худшего найденного исхода {num(worst["robust"]-worst["base"])} поездок. При отказе будущей базы исправный аппарат остаётся на прежней; реальное местоположение сохраняется по годам.')
    blocks[-1]=('Выводы и незакрытые пункты','Добавлены свободные ротации, пересадки, межгодовые перегоны, обязательные эксперименты и автономная карта. Официальный перечень ФНС извлечён, но географическое сопоставление всех записей остаётся неполным. Для крупных временных MIP возможна остановка по ограничению ресурсов; вместо фиктивного оптимума публикуется непрерывная агрегированная верхняя граница и допустимый эвристический план. Последовательные MIP используют ту же временную постановку и фиксируют прошлые решения; доступность результатов определяется статусами решателя. Не учтены тарифы и конкуренция наземного транспорта. ИИ использован для разработки кода, аудита и текста; результаты получены программами. На защите требуется самостоятельно объяснить модель и ограничения.')
    blocks.append(('Распределения и недостижимый спрос',f'Компоненты потенциального графа при дальности 200 км имеют размеры {descriptive["component_sizes"]}. Между разными компонентами нельзя перевезти {num(sum(descriptive["unreachable_annual_demand"]))} поездок за три года даже при достаточном бюджете. Асимметрия Σ|qᵢⱼ−qⱼᵢ|/Σqᵢⱼ первого года равна {descriptive["directional_asymmetry"]:.3f}. Выборочная асимметрия населения {descriptive["population_skew"]:.3f}; 95-й процентиль {num(descriptive["population_p95"])} человек. Эти характеристики относятся к фиксированным 30 пунктам, а не ко всем поселениям областей. Числа сохранены в report/data_descriptive.json.'))
    def clock(minutes):return f'{int(minutes)//60:02d}:{int(minutes)%60:02d}'
    legs=transfer['legs'];route=[names[legs[0]['origin_id']]]+[names[f['destination_id']] for f in legs]
    blocks.append(('Разбор пересадки и порожнего рейса',f'Проверяемый маршрут: {" → ".join(route)}. Первый аппарат {legs[0]["aircraft_id"]}: {clock(legs[0]["departure_min"])}–{clock(legs[0]["arrival_min"])}; следующий {legs[1]["aircraft_id"]}: {clock(legs[1]["departure_min"])}–{clock(legs[1]["arrival_min"])}. Это одна завершённая поездка с годовым весом 330, а не две поездки по числу участков. Отдельный синтетический экземпляр использует реальные координаты двух пунктов, но специально изменённые населения и K; ровно один пассажир в сутки летит в одном направлении, аппарат возвращается пустым. Ответ за три года — 990 поездок; энергия обратного рейса включена в расходы. Примеры не подменяют основную выборку.'))
    blocks.append(('Полная постановка и область границы','Формулы потокового баланса, зарядных ресурсов, фиксированных интервалов движений, накопленного бюджета и межгодовых перегонов приведены в MODEL_V2.md. Временной MIP учитывает энергию межгодовых перемещений, но их часы строятся после оптимизации в 35 неэксплуатационных дней и независимо проверяются. Поэтому допустимость расписания и верхняя оценка решателя сообщаются отдельно. Все численные параметры каждого экспериментального результата находятся рядом с ним в config.json.'))
    blocks.append(('Финансовый баланс модели','Для каждого года y: Rᵧ = Rᵧ₋₁ + Bᵧ − Cᵧ ≥ 0, R₀ = 0. Здесь Cᵧ = 90·10⁶ ΔXᵧ + 250·10⁶ ΔNᵧ + 12·10⁶ Xᵧ + 18·10⁶ Nᵧ + 330 Σₑ Eₑ Aₑᵧ + Σₑ Eₑ rₑᵧ, Eₑ = ceil(40Dₑ). Xᵧ и Nᵧ — все введённые порты и аппараты, Δ — новые покупки, A — число рейсов в типичные сутки, r — однократные межгодовые перегоны. Равносильное накопленное ограничение: Σᵧ≤Y Cᵧ ≤ Σᵧ≤Y Bᵧ для каждого Y. Поэтому остаток разрешает расходы больше одного транша в отдельном позднем году.'))
    blocks.append(('Ресурсные ограничения модели','Для каждой базы h поток аппаратов выходит из (h,08:00) и возвращается в (h,20:00) в одинаковом количестве. На остальных временных узлах входящий поток равен исходящему. На каждом рейсе сумма пассажирских потоков к назначениям не больше 10-кратного числа аппаратов. Для каждого порта и момента: сумма прибывших, но ещё не закончивших зарядку аппаратов ≤ 2. Для каждого порта и фиксированного 90-минутного интервала: число отправлений плюс число прибытий ≤ 2. Сохранение пассажирского потока и единый сток назначения исключают повторный подсчёт пересадок.'))
    budget_curve=exp[exp.experiment=='budget'].sort_values('value').copy();budget_curve['gain']=budget_curve.completed_trips.diff();budget_curve['previous']=budget_curve.value.shift()
    jumps=budget_curve.nlargest(4,'gain')
    blocks.append(('Где меняется бюджетный результат','Крупнейшие приросты на проверенной сетке: '+'; '.join(f'{r.previous:g}→{r.value:g} млн руб./год: +{num(r.gain)} поездок' for r in jumps.itertuples())+'. Эти интервалы характеризуют набор найденных допустимых планов. Они не доказывают точные экономические пороги и могут измениться при более сильном поиске. При одинаковых перевозках предпочтение отдаётся меньшим фактическим расходам.'))
    bounds=json.loads((folder/'aggregate_bounds.json').read_text()) if (folder/'aggregate_bounds.json').exists() else []
    for bound in bounds:
        if bound.get('upper_bound') is None: continue
        mask=methods.instance==bound['nodes']; upper=bound['upper_bound']
        for mip in mips:
            if mip['nodes']==bound['nodes'] and mip.get('upper_bound') is not None: upper=min(upper,mip['upper_bound'])
        methods.loc[mask,'upper_bound']=upper
        methods.loc[mask,'certified_gap']=(upper-methods.loc[mask,'completed_trips']).clip(lower=0)/methods.loc[mask,'completed_trips'].clip(lower=1)
    methods.to_csv(out/'method_comparison_complete.csv',index=False)
    for bound in bounds:
        candidates=methods[methods.instance==bound['nodes']]
        if bound.get('upper_bound') is not None and len(candidates):
            incumbent=float(candidates.completed_trips.max()); gap=max(0,(bound['upper_bound']-incumbent)/max(1,incumbent))
            blocks.append((f'Граница качества: {bound["nodes"]} пунктов',f'Лучший опубликованный допустимый план: {num(incumbent)}. Верхняя граница агрегированной непрерывной релаксации: {num(bound["upper_bound"])}. Разрыв (UB−LB)/LB: {gap:.2%}. Релаксация разрешает дробные активы и рейсы, не требует точного времени отправлений и не начисляет энергию перебазирования; поэтому её значение является верхней оценкой, а не расписанием.'))
    order=['Постановка и результат','Данные и происхождение','Распределения и недостижимый спрос','Спрос и качество данных','Техника, время и финансы','Математическая постановка','Финансовый баланс модели','Ресурсные ограничения модели','Полная постановка и область границы','Область применимости','Методы и вычислительный протокол','Расписание и независимая проверка','Разбор пересадки и порожнего рейса','Эксперименты и статистика','Где меняется бюджетный результат','Граница качества','Стресс-тесты и робастность','Поиск путей и игра','Выводы и незакрытые пункты']
    blocks.sort(key=lambda item:order.index('Граница качества' if item[0].startswith('Граница качества:') else item[0]))
    # Flowing PDF with embedded Unicode fonts, captions and source references.
    fonts=ROOT/'assets/fonts'
    if not fonts.exists():fonts=Path('/usr/share/fonts/truetype/dejavu')
    pdfmetrics.registerFont(TTFont('DV',str(fonts/'DejaVuSans.ttf'))); pdfmetrics.registerFont(TTFont('DV-B',str(fonts/'DejaVuSans-Bold.ttf')))
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='BodyRU',fontName='DV',fontSize=9,leading=14,spaceAfter=9)); styles.add(ParagraphStyle(name='HeadRU',fontName='DV-B',fontSize=14,leading=18,spaceBefore=14,spaceAfter=9)); styles.add(ParagraphStyle(name='CaptionRU',fontName='DV',fontSize=8,leading=11,spaceAfter=12))
    story=[Paragraph('Сеть дронопортов России · вариант И',styles['HeadRU']),Paragraph(f'Расширенная исследовательская версия · {folder.name}',styles['BodyRU'])]
    if manifest.get('status')!='calculated' or manifest.get('additional_mip_pending'):story.append(Paragraph('Промежуточная версия: вычислительный запуск ещё не завершён. Статусы и таблицы будут обновлены после оставшихся расчётов.',styles['BodyRU']))
    for title,text in blocks: story += [Paragraph(html.escape(title),styles['HeadRU']),Paragraph(html.escape(text),styles['BodyRU'])]
    def add_table(title,frame):
        story.append(Paragraph(title,styles['HeadRU']))
        frame=frame.copy().rename(columns={'instance':'Пунктов','method':'Метод','completed_trips':'Поездки','served_share':'Доля спроса','wall_seconds':'Время, с','gap':'Разрыв','ports':'Порты','fleet':'Флот','cost_million_rub':'Расходы, млн руб.','n':'Пунктов','status':'Статус','bound':'Верхняя граница','minimum':'Минимум','median':'Медиана','best':'Максимум','mean_paired_gain':'Средний прирост','mean_run_seconds':'Запуск, с'})
        frame=frame.replace({'greedy':'Greedy','annealing_best':'Отжиг: 600 с','annealing_preliminary':'Отжиг: 200 ит.','deployment_polish':'Доработка плана','sequential_greedy':'Greedy по годам','sequential_mip':'MIP по годам','mip':'MIP','Time limit reached':'Лимит времени','Memory limit reached':'Лимит памяти','MEMORY_LIMIT':'Лимит памяти','RESOURCE_GUARD':'Лимит матрицы'}).fillna('—')
        rows=[[Paragraph(html.escape(str(v)),styles['CaptionRU']) for v in row] for row in [list(frame.columns)]+frame.astype(str).values.tolist()]
        table=Table(rows,repeatRows=1,hAlign='LEFT',colWidths=[480/len(frame.columns)]*len(frame.columns))
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8f0f4')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.5,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),5)])); story.append(table)
    add_table('Годовой план',pd.DataFrame({'Год':[1,2,3],'Порты':budget.active_ports,'Аппараты':budget.active_aircraft,'Поездки':base['annual_completed'],'Расходы, млн':(budget.spend_rub/1e6).round(2),'Остаток, млн':(budget.carry_rub/1e6).round(2)}))
    performance=methods[['instance','method','completed_trips','served_share','wall_seconds']].copy()
    performance['served_share']=performance.served_share.map(lambda v:f'{v:.2%}')
    if 'certified_gap' in methods: performance['gap']=methods.certified_gap.map(lambda v:f'{v:.2%}')
    add_table('Сравнение алгоритмов: качество и время',performance.round(4))
    investments=methods[['instance','method','ports','fleet','cost_rub']].copy();investments['cost_rub']=investments.cost_rub/1e6;investments=investments.rename(columns={'cost_rub':'cost_million_rub'})
    add_table('Сравнение алгоритмов: ресурсы',investments.round(3))
    if (folder/'seed_summary.csv').exists():
        summary=pd.read_csv(folder/'seed_summary.csv')
        add_table('Серия seed: распределение и парный прирост к greedy',summary[['instance','minimum','median','best','mean_paired_gain','mean_run_seconds']].round(2))
    if 'refinement_seconds' in methods:
        stages=methods[methods.method=='deployment_polish'][['instance','initial_plan_seconds','refinement_seconds','wall_seconds']].rename(columns={'initial_plan_seconds':'Получение входов, с','refinement_seconds':'Доработка, с'})
        add_table('Время доработки с учётом получения исходных планов',stages.round(2))
    grid=exp[exp.experiment=='grid_small'][['value','completed_trips','cost_rub']].copy()
    baseline_grid=methods[(methods.instance==8)&(methods.method=='greedy')].iloc[0]
    grid.loc[len(grid)]=[10,baseline_grid.completed_trips,baseline_grid.cost_rub]
    grid['cost_rub']=(grid.cost_rub/1e6).round(2);grid=grid.sort_values('value').rename(columns={'value':'Шаг, мин','cost_rub':'Расходы, млн руб.'})
    add_table('Сетка времени: 8 пунктов, один и тот же greedy',grid)
    if mips: add_table('Статусы MIP',pd.DataFrame([dict(n=r['nodes'],status=r['status'],bound=num(r['upper_bound']) if r.get('upper_bound') is not None else '—',gap=f'{r["gap"]:.2%}' if r.get('gap') is not None else '—') for r in mips]))
    story += [NextPageTemplate('figures'),PageBreak()]
    for index,chart in enumerate(charts,1):
        from PIL import Image as PILImage
        path=figures/(chart['name']+'.png'); w,h=PILImage.open(path).size; width=min(746,430*w/h); height=width*h/w
        story.append(KeepTogether([Image(str(path),width=width,height=height),Paragraph(f'Рисунок {index}. '+html.escape(chart['caption'])+'<br/>Данные: '+html.escape(chart['evidence']),styles['CaptionRU'])]))
        if index<len(charts):story.append(PageBreak())
    def footer(canvas,doc):
        canvas.setFont('DV',7); canvas.drawString(40,24,folder.name+' · учебные спрос и цены'); canvas.drawRightString(canvas._pagesize[0]-40,24,str(doc.page))
    doc=BaseDocTemplate(str(out/'report.pdf'),pagesize=(595,842),leftMargin=48,rightMargin=48,topMargin=40,bottomMargin=40,title='Сеть дронопортов России · вариант И',author='Учебный исследовательский проект',subject='Временная модель, инвестиции, расписания и устойчивость')
    doc.addPageTemplates([PageTemplate(id='text',frames=[Frame(48,40,499,762,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=footer,pagesize=(595,842)),
        PageTemplate(id='figures',frames=[Frame(48,40,746,515,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=footer,pagesize=(842,595))])
    doc.build(story)
    markdown='# Сеть дронопортов · вариант И\n\n'+'\n\n'.join('## '+t+'\n\n'+v for t,v in blocks)
    markdown+='\n\n'+'\n\n'.join(f'![{c["caption"]}](figures/{c["name"]}.png)\n\nДанные: {c["evidence"]}' for c in charts)
    (out/'report.md').write_text(markdown,encoding='utf-8')
    markup='<!doctype html><meta charset="utf-8"><title>Дронопорты · исследование</title><style>body{max-width:1050px;margin:40px auto;padding:20px;font:16px/1.6 system-ui;color:#223749}img{max-width:100%}td,th{padding:8px;border:1px solid #ccc}table{border-collapse:collapse}small{color:#657987}</style><h1>Сеть дронопортов · вариант И</h1><p><a href="report.pdf">PDF</a> · <a href="maps/network.html">Автономная карта</a></p>'
    markup+=''.join(f'<h2>{html.escape(t)}</h2><p>{html.escape(v)}</p>' for t,v in blocks)+methods.to_html(index=False)
    markup+=''.join(f'<figure><img src="figures/{c["name"]}.png"><figcaption>{html.escape(c["caption"])}</figcaption><small>{html.escape(c["evidence"])}</small></figure>' for c in charts)
    (out/'report.html').write_text(markup,encoding='utf-8')
    (out/'maps').mkdir(exist_ok=True); offline_map(folder,out/'maps/network.html')
    names={r.place_id:r.name_original for r in towns.itertuples()}; executive=blocks[0][1]+'\n\n'
    for y in (1,2,3):
        opened=[towns.iloc[i].name_original for i,v in enumerate(base['plan']['open_years']) if v==y]
        fleet=sum(a['year']==y for a in base['plan']['aircraft'])
        executive+=f'Год {y}: открыть {", ".join(opened) or "новых портов нет"}; приобрести аппаратов: {fleet}; поездок: {base["annual_completed"][y-1]:,}.\n\n'
    executive+=next(text for title,text in blocks if title=='Стресс-тесты и робастность')+'\n\n'+next(text for title,text in blocks if title=='Выводы и незакрытые пункты')
    (out/'executive_summary.txt').write_text(executive,encoding='utf-8')
    (out/'executive_summary.md').write_text('# Управленческая записка · вариант И\n\n'+executive,encoding='utf-8')
    if (folder/'cp_ga/search_best_scenario_manifest.json').exists():
        from .report_cp_ga import append_experiments
        append_experiments(folder)
    if (folder/'regional/manifest.json').exists():
        from .report_regional import append_regional
        append_regional(folder)
    save(out/'report_manifest.json',{'run_id':folder.name,'figures':len(json.loads((out/'figure_manifest.json').read_text())),'artifacts':{str(p.relative_to(out)):checksum(p) for p in out.rglob('*') if p.is_file() and p.name!='report_manifest.json'}})
    print(f'Report ready: {out}',flush=True)
