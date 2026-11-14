"""Comparative atlas built only from archived numerical evidence."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from shapely.geometry import shape
from .article_theme import apply_theme,atlas,COLORS,SEQUENTIAL,INK,MUTED
from .event_model import EventInstance
from .event_validation import validate
from .ingest import ROOT,checksum
from .pipeline_v2 import save,metrics

VARIANTS={'A':('Базовая временная модель','base'),'B':('CP-SAT и поиск GA/SA','cp_ga/final_best'),'C':('Обслуживание трёх областей','regional/final_best')}
REGIONS={50:'Московская',67:'Смоленская',69:'Тверская'}

def build(folder,out):
    apply_theme();out.mkdir(parents=True,exist_ok=True);reg=atlas.FigureRegistry(out/'figures',out/'evidence',dpi=300)
    towns=pd.read_csv(folder/'towns_main.csv');cfg=json.loads((folder/'config.json').read_text());inst=EventInstance(towns,cfg)
    results={};rows=[];yearrows=[];sources={};checks=[]
    for tag,(label,path) in VARIANTS.items():
        p=folder/path;r=json.loads((p/'result.json').read_text());c=json.loads((p/'config.json').read_text())
        check=validate(towns,r,c);assert check['valid'],check;checks.append(dict(variant=tag,**check));results[tag]=r
        rows.append(dict(variant=tag,label=label,result_path=str((p/'result.json').relative_to(ROOT)),**metrics(inst,r)))
        for b in r['budget']:yearrows.append(dict(variant=tag,completed_trips=r['annual_completed'][b['year']-1],**b))
        sources[str((p/'result.json').relative_to(ROOT))]=checksum(p/'result.json')
    summary=pd.DataFrame(rows);annual=pd.DataFrame(yearrows);reg.table(summary,'variants');reg.table(annual,'annual')
    save(out/'source_validation.json',dict(valid=True,plans=checks,sources=sources))
    methods=pd.read_csv(folder/'method_comparison.csv');experiments=pd.read_csv(folder/'experiments.csv');seeds=pd.read_csv(folder/'seed_results.csv')
    search=pd.read_csv(folder/'cp_ga/search_results.csv');scenario=pd.read_csv(folder/'scenario_results.csv');bfs=pd.read_csv(folder/'bfs_astar.csv')
    names=dict(zip(towns.place_id,towns.name_original));points=towns.set_index('place_id')
    boundaries=json.loads((ROOT/'data/processed/region_boundaries.geojson').read_text())
    def panel(ax,label,title):
        ax.set_title(label+'  '+title,loc='left',pad=8);ax.grid(axis='y',alpha=.6)
    def finish(fig,stem,caption,evidence,data=None,aggregation='Сохранённые значения без сглаживания',uncertainty='Не оценивалась: расчётные сценарии',comparability='См. подпись'):
        if data is not None:reg.table(data,stem)
        reg.save(fig,stem,caption,source=evidence,n_obs=len(data) if data is not None else None,aggregation=aggregation,uncertainty=uncertainty,comparability=comparability)
        (out/'figures/svg').mkdir(exist_ok=True)
        fig.savefig(out/'figures/svg'/f'{stem}.svg',facecolor='white',bbox_inches='tight',pad_inches=.28)
        plt.close(fig);print(stem,flush=True)
    def canvas(rows=1,cols=2,height=3.4):return plt.subplots(rows,cols,figsize=(7.2,height),squeeze=False,layout='constrained')
    def geography(ax,result=None,year=3,allpoints=None):
        for feature in boundaries['features']:
            geo=shape(feature['geometry']);polys=list(geo.geoms) if geo.geom_type=='MultiPolygon' else [geo]
            for p in polys:ax.plot(*p.exterior.xy,color='#b0bac6',lw=.45,zorder=0)
        if allpoints is not None:ax.scatter(allpoints.lon,allpoints.lat,s=.9,c='#b0bac6',rasterized=True)
        ax.scatter(towns.lon,towns.lat,s=9,c='#9da8b3',marker='x',linewidths=.7)
        if result:
            for a,b in {(f['origin_id'],f['destination_id']) for f in result['flights'] if f['year']==year}:
                aa=points.loc[a];bb=points.loc[b];ax.plot([aa.lon,bb.lon],[aa.lat,bb.lat],color='#0072b2',lw=1,zorder=2)
            active=[i for i,y in enumerate(result['plan']['open_years']) if 0<y<=year]
            ax.scatter(towns.iloc[active].lon,towns.iloc[active].lat,s=22,c='#bb4e12',edgecolors='white',linewidths=.4,zorder=3)
            for i in active:
                t=towns.iloc[i]
                if t.region_code!=50:ax.annotate(t.name_original,(t.lon,t.lat),xytext=(3,4),textcoords='offset points',fontsize=7)
        ax.set(xlim=(30.7,39),ylim=(54.3,58.5),xlabel='Долгота, °',ylabel='Широта, °');ax.grid(False)
    # 1. Registry and explicit coordinate uncertainty.
    allpoints=pd.read_csv(ROOT/'data/processed_v2/towns_all.csv');gar=json.loads((ROOT/'data/processed_v2/gar_audit.json').read_text())
    fig,axs=canvas(height=4);geography(axs[0,0],allpoints=allpoints);panel(axs[0,0],'a','Территория и фиксированная выборка');axs[0,0].grid(False)
    counts=pd.DataFrame([dict(region=r,official=gar['eligible_by_region'][str(r)],sample=int((towns.region_code==r).sum())) for r in REGIONS])
    x=np.arange(3);axs[0,1].bar(x,counts.official,color='#0072b2');axs[0,1].set_xticks(x,[REGIONS[r] for r in counts.region],rotation=25,ha='right');axs[0,1].set_ylabel('Допустимых поселений в ГАР')
    for i,row in counts.iterrows():axs[0,1].text(i,row.official+35,f'{row.official}\nвыборка: {row["sample"]}',ha='center',fontsize=8)
    axs[0,1].set_ylim(0,2600);panel(axs[0,1],'b','Реестр и вычислительные 30 пунктов')
    finish(fig,'01_data','Серые точки показывают OSM-пункты с координатами, кресты обозначают фиксированную выборку. Официальный перечень содержит 4480 допустимых поселений; координаты однозначно сопоставлены для 2093. Наличие списка не означает полноту географического сопоставления.','data/processed_v2/gar_audit.json; towns_all.csv; towns_main.csv',counts)
    # 2. Population and distances, preserving all 30 points.
    fig,axs=canvas(height=3.4)
    for j,(region,g) in enumerate(towns.groupby('region_code')):
        p=np.sort(g.population.to_numpy());axs[0,0].step(p,np.arange(1,len(p)+1)/len(p),where='post',marker=['o','s','^'][j],ms=3,label=f'{REGIONS[region]} (n={len(p)})')
    axs[0,0].set(xscale='log',xlabel='Население, человек (log₁₀)',ylabel='Эмпирическая доля');axs[0,0].legend(fontsize=6.8);panel(axs[0,0],'a','Неравномерность населения')
    dist=inst.distance[np.triu_indices(inst.n,1)];bins=np.linspace(0,np.ceil(dist.max()/50)*50,15)
    axs[0,1].hist(dist,bins=bins,color='#0072b2',edgecolor='white');axs[0,1].axvline(200,color='#bb4e12',ls='--',label='200 км');axs[0,1].set(xlabel='Расстояние пары, км',ylabel='Число неупорядоченных пар');axs[0,1].legend();panel(axs[0,1],'b','Географические расстояния')
    finish(fig,'02_distributions','Распределения фиксированной выборки. Население показано на логарифмической шкале; малочисленная смоленская подвыборка не характеризует распределение всей области. Пунктир отмечает дальность одного участка, а не максимальную длину поездки с пересадками.','towns_main.csv; config.json',towns[['place_id','name_original','region_code','population']])
    reg.table(pd.DataFrame({'distance_km':dist}),'02_pair_distances')
    # 3. Directed demand.
    fig,axs=canvas(height=3.6);q=inst.demand[0];im=axs[0,0].imshow(np.ma.masked_equal(q,0),norm=LogNorm(vmin=1,vmax=q.max()),cmap=SEQUENTIAL,interpolation='nearest',aspect='auto')
    axs[0,0].set(xlabel='Индекс назначения',ylabel='Индекс отправления');panel(axs[0,0],'a','OD-спрос, первый год');axs[0,0].grid(False);fig.colorbar(im,ax=axs[0,0],label='Поездки/сутки, log₁₀',shrink=.8)
    a,b=np.triu_indices(30,1);axs[0,1].scatter(q[a,b],q[b,a],s=10,color='#0072b2',alpha=.65,rasterized=True)
    lim=max(q[a,b].max(),q[b,a].max());axs[0,1].plot([0,lim],[0,lim],color='#697585',ls='--',lw=.8);axs[0,1].set(xlabel='qᵢⱼ, поездки/сутки',ylabel='qⱼᵢ, поездки/сутки');panel(axs[0,1],'b','Направленная асимметрия')
    frame=pd.DataFrame([dict(origin=inst.ids[i],destination=inst.ids[j],year=y+1,distance_km=inst.distance[i,j],daily_demand=int(inst.demand[y,i,j])) for y in range(3) for i in range(30) for j in range(30) if i!=j])
    finish(fig,'03_demand','Синтетический направленный спрос задан до оптимизации. Серые клетки матрицы соответствуют нулю, включая диагональ. Все 30 пунктов входят в одну компоненту потенциальных перелётов до 200 км; это не гарантирует доступность поездки в расписании.','towns_main.csv; config.json',frame)
    # 4. Main comparison, zero baselines.
    fig,axs=canvas(height=3.2)
    for ax,col,scale,label in [(axs[0,0],'completed_trips',1000,'Поездки за 3 года, тыс.'),(axs[0,1],'cost_rub',1e9,'Расходы за 3 года, млрд руб.')]:
        vals=summary[col]/scale;bars=ax.bar(summary.variant,vals,color=[COLORS[t] for t in summary.variant],width=.6)
        for rect,v in zip(bars,vals):ax.text(rect.get_x()+rect.get_width()/2,v+max(vals)*.02,f'{v:.1f}' if scale==1000 else f'{v:.3f}',ha='center',fontsize=9)
        ax.set_ylabel(label);ax.set_ylim(0,max(vals)*1.16);ax.grid(axis='y',alpha=.6)
    panel(axs[0,0],'a','Перевозки');panel(axs[0,1],'b','Ресурсы бюджета')
    finish(fig,'04_comparison','A: базовая временная модель; B: улучшение расписания CP-SAT и поисковая серия; C: порты и рейсы во всех трёх областях. A и B используют одинаковые инвестиции. C решает более строгую задачу, поэтому три столбца не являются рейтингом алгоритмов на одном допустимом множестве.','base/result.json; cp_ga/final_best/result.json; regional/final_best/result.json',summary)
    # 5. Same geographic scale for all networks.
    fig,axs=canvas(cols=3,height=3.8)
    for ax,tag in zip(axs[0],VARIANTS):geography(ax,results[tag]);panel(ax,tag,f'Год 3: {summary[summary.variant==tag].iloc[0].ports} портов');ax.grid(False)
    finish(fig,'05_networks','Сети третьего года в одинаковом географическом масштабе. A и B сохраняют одну географию строительства, но различаются расписаниями. В C появляются Зубцов и Кардымово. Серые кресты сохраняют все пункты выборки.','Три result.json; towns_main.csv')
    fig,axs=canvas(cols=3,height=3.8)
    for ax,y in zip(axs[0],(1,2,3)):geography(ax,results['C'],year=y);panel(ax,chr(96+y),f'Год {y}');ax.grid(False)
    finish(fig,'06_network_years','Ввод сети C по годам. В первые два года состав активов совпадает с A и B; дополнительное региональное условие выполняется в третьем году. Линии означают фактические рейсы.','regional/final_best/result.json')
    # 7. Annual output and expenditure with carryover.
    fig,axs=canvas(height=3.6);x=np.arange(3)
    for j,tag in enumerate(VARIANTS):
        rows=annual[annual.variant==tag];offset=(j-1)*.24
        axs[0,0].bar(x+offset,rows.completed_trips/1000,.23,color=COLORS[tag],label=tag)
        axs[0,1].plot(x,rows.carry_rub/1e6,marker=['o','s','^'][j],color=COLORS[tag],label=tag)
    for ax in axs[0]:ax.set_xticks(x,['Год 1','Год 2','Год 3']);ax.legend(ncol=3)
    axs[0,0].set_ylabel('Поездки за год, тыс.');axs[0,1].set_ylabel('Остаток бюджета, млн руб.');axs[0,1].set_ylim(bottom=0)
    panel(axs[0,0],'a','Перевозки по годам');panel(axs[0,1],'b','Перенос средств')
    finish(fig,'07_annual','Три года перевозок и неотрицательные денежные остатки. Во втором году расход 1044,400 млн руб. допустим благодаря переносу 46,895 млн руб. из первого года. Будущие транши не используются.','Три budget_by_year.csv',annual)
    # 8. Cost composition.
    fig,axs=canvas(height=3.4);categories=[('port_capex_rub','Порты: CAPEX'),('aircraft_capex_rub','Флот: CAPEX'),('port_opex_rub','Порты: OPEX'),('aircraft_opex_rub','Флот: OPEX'),('energy_rub','Энергия')]
    left=np.zeros(3)
    for key,label in categories:
        vals=np.array([annual[annual.variant==t][key].sum()/1e9 for t in VARIANTS]);axs[0,0].barh(list(VARIANTS),vals,left=left,label=label);left+=vals
    axs[0,0].set_xlabel('Затраты за 3 года, млрд руб.');axs[0,0].legend(fontsize=6.5,loc='upper center',bbox_to_anchor=(.5,-.24),ncol=2);panel(axs[0,0],'a','Состав затрат')
    diff=annual[annual.variant=='C'].set_index('year').spend_rub-annual[annual.variant=='B'].set_index('year').spend_rub
    vals=[180,24,(summary.set_index('variant').loc['C','cost_rub']-summary.set_index('variant').loc['B','cost_rub'])/1e6-204]
    axs[0,1].bar(['Новые\nпорты','Их\nOPEX','Дополнительная\nэнергия'],vals,color=['#0072b2','#007f5f','#bb4e12']);axs[0,1].set_ylabel('Доплата C к B, млн руб.');panel(axs[0,1],'b','Цена регионального условия')
    finish(fig,'08_costs','CAPEX начисляется при покупке, OPEX включает все введённые активы. Межгодовые перегоны учтены в итоговых суммах, но их величина менее 0,01 млн руб. неразличима в левой панели. Доплата C к B составляет 211,441 млн руб.','Три budget_by_year.csv',annual)
    # 9. Algorithms, distinguishing a run from a series.
    fig,axs=canvas(height=3.6);ml={'greedy':'Greedy','annealing_best':'Отжиг: лучший из 10','mip':'MIP','deployment_polish':'Доработка портфеля'}
    method_colors={'greedy':'#0072b2','annealing_best':'#007f5f','mip':'#bb4e12','deployment_polish':'#8064a2'}
    for j,(method,label) in enumerate(ml.items()):
        g=methods[methods.method==method].sort_values('instance');axs[0,0].plot(g.instance,g.completed_trips/1000,marker=['o','s','^','D'][j],label=label,color=method_colors[method])
    axs[0,0].set(xlabel='Число пунктов',ylabel='Поездки, тыс.',xticks=[8,12,20,30]);axs[0,0].legend(fontsize=6.5);panel(axs[0,0],'a','Качество решения')
    for method,label in [('greedy','Greedy: один запуск'),('mip','MIP: одна попытка')]:
        g=methods[methods.method==method].sort_values('instance');axs[0,1].plot(g.instance,g.wall_seconds,marker='o' if method=='greedy' else '^',label=label,color=method_colors[method])
    g=seeds.groupby('instance').wall_seconds.agg(['mean','sum']);axs[0,1].plot(g.index,g['mean'],marker='s',label='Отжиг: средний запуск',color=method_colors['annealing_best']);axs[0,1].plot(g.index,g['sum'],marker='D',ls='--',label='Отжиг: сумма 10 запусков',color=method_colors['annealing_best'])
    axs[0,1].set(yscale='log',xlabel='Число пунктов',ylabel='Время, с (log₁₀)',xticks=[8,12,20,30]);axs[0,1].legend(fontsize=6.2);panel(axs[0,1],'b','Вычислительный бюджет')
    finish(fig,'09_methods','Основная серия A. Доработка портфеля использует результаты нескольких методов и не считается независимым быстрым запуском. MIP на 30 пунктах остановлен по памяти и сохранил допустимый старт; точка не означает найденный оптимум. Времена одного запуска и суммы серии показаны раздельно.','method_comparison.csv; seed_results.csv',methods)
    # 10. Explicit raw seeds, using the original Cinematic Atlas primitive.
    fig,axs=canvas(height=3.4);seed_table=[]
    for j,n in enumerate((8,12,20,30)):
        g=seeds[seeds.instance==n];baseline=methods[(methods.instance==n)&(methods.method=='greedy')].iloc[0].completed_trips;gain=(g.completed_trips-baseline)/1000
        atlas.beeswarm(axs[0,0],gain,y=j,color='#0072b2',s=24,alpha=.85,width=.18,rng=np.random.default_rng(42))
        seed_table.extend(dict(instance=n,seed=int(s),gain_trips=int(v*1000)) for s,v in zip(g.seed,gain))
    axs[0,0].set_yticks(range(4),['8','12','20','30']);axs[0,0].set(xlabel='Прирост к greedy, тыс. поездок',ylabel='Размер задачи');panel(axs[0,0],'a','Отжиг: все 10 seed')
    paired=search.pivot(index='seed',columns='method',values='completed_trips');axs[0,1].plot(paired.index,paired.sa/1000,'o-',label='Отжиг + CP',color=COLORS['A']);axs[0,1].plot(paired.index,paired.ga/1000,'s--',mfc='white',label='GA + CP',color=COLORS['C'])
    axs[0,1].axhline(501.6,color=COLORS['B'],ls=':',label='После распределения');axs[0,1].set(ylim=(495,503),xlabel='Парный seed',ylabel='Поездки, тыс.');axs[0,1].legend(fontsize=6.7);panel(axs[0,1],'b','Серия B: равные результаты')
    finish(fig,'10_seeds','Слева каждая точка соответствует одному seed, вертикальное смещение служит только различению точек. Справа все 10 пар GA и отжига дали 498300 поездок. Последующее распределение пассажиров дало 501600; этот прирост не приписывается GA. Интервалы прогнозной неопределённости не строились.','seed_results.csv; cp_ga/search_results.csv',pd.DataFrame(seed_table),uncertainty='Полный наблюдаемый разброс по 10 seed, не доверительный интервал')
    reg.table(search,'10_cp_ga_seeds')
    # 11. Budget response, preserve discrete evaluated points and resource steps.
    g=experiments[experiments.experiment=='budget'].sort_values('value');fig,axs=canvas(height=3.5)
    axs[0,0].plot(g.value,g.completed_trips/1000,'o-',ms=2.5,color=COLORS['A']);axs[0,0].set(xlabel='Транш, млн руб./год',ylabel='Поездки за 3 года, тыс.');panel(axs[0,0],'a','Найденная бюджетная зависимость')
    axs[0,1].step(g.value,g.ports,where='post',label='Порты',marker='o',ms=2.5);axs[0,1].step(g.value,g.fleet,where='post',label='Аппараты',marker='s',ms=2.5);axs[0,1].set(xlabel='Транш, млн руб./год',ylabel='Количество к году 3',ylim=(0,max(g.ports.max(),g.fleet.max())+2));axs[0,1].legend();panel(axs[0,1],'b','Изменения состава сети')
    finish(fig,'11_budget','Проверены транши от 250 до 1000 млн руб. с шагом 50 млн и уточнениями 10 млн. Показан лучший допустимый план из сохранённого портфеля. Линии соединяют рассчитанные точки и не доказывают пороги оптимальной бюджетной функции.','experiments.csv',g)
    # 12. One-at-a-time sensitivity with explicit common reference.
    labels={'port_capex_rub':'CAPEX порта','aircraft_capex_rub':'CAPEX аппарата','port_opex_rub_per_year':'OPEX порта','aircraft_opex_rub_per_year':'OPEX аппарата','flight_speed_kmh':'Скорость','charging_minutes':'Зарядка, мин','demand.gamma':'Затухание γ','demand.yearly_growth':'Годовой рост'}
    g=experiments[experiments.experiment.isin(labels)].copy();reference=methods[(methods.instance==30)&(methods.method=='greedy')].iloc[0].completed_trips
    g['change_percent']=(g.completed_trips/reference-1)*100;g['label']=[labels[r.experiment]+f': {r.value:g}' for r in g.itertuples()]
    fig,axs=canvas(cols=1,height=4.7);ax=axs[0,0];y=np.arange(len(g));ax.hlines(y,0,g.change_percent,color='#b0bac6');ax.scatter(g.change_percent,y,color=COLORS['A'],s=28);ax.axvline(0,color=MUTED,lw=.8);ax.set_yticks(y,g.label,fontsize=7.3);ax.set_xlabel('Изменение перевозок к исходному greedy, %');ax.grid(axis='x',alpha=.6)
    finish(fig,'12_sensitivity','Изменение одного допущения за раз. CAPEX, OPEX и скорость умножаются на 0,8 или 1,2; зарядка проверена при 20 и 45 мин вместо 30. Для каждого сценария оценивается допустимый портфель; нулевой прирост не доказывает нечувствительность глобального оптимума.','experiments.csv; method_comparison.csv',g)
    # 13. Matched robust study only, not mixed recourse protocols.
    fig,axs=canvas(height=3.8);fail=scenario[scenario.scenario.str.startswith('failed_')];stats=scenario.groupby('plan').completed_trips.min()
    x=np.arange(2);basevals=[results['A']['completed_trips'],json.loads((folder/'robust/result.json').read_text())['completed_trips']]
    axs[0,0].bar(x-.17,np.array(basevals)/1000,.34,label='Базовый режим',color=COLORS['A']);axs[0,0].bar(x+.17,stats.reindex(['base','robust']).to_numpy()/1000,.34,label='Худший сценарий',color=COLORS['C']);axs[0,0].set_xticks(x,['Базовый план','Робастный план']);axs[0,0].set_ylabel('Поездки за 3 года, тыс.');axs[0,0].legend(fontsize=7);panel(axs[0,0],'a','Цена устойчивости в серии A')
    for j,tag in enumerate(['base','robust']):
        g=fail[fail.plan==tag];vals=np.sort(g.completed_trips/1000);axs[0,1].plot(vals,np.arange(1,len(vals)+1)/len(vals),marker=['o','s'][j],label=tag)
    axs[0,1].set(xlabel='Поездки при отказе, тыс.',ylabel='Доля отказов с результатом ≤ x');axs[0,1].legend();panel(axs[0,1],'b','Все отказы введённых портов')
    finish(fig,'13_robust','Сопоставление базового и робастного планов в исходном общем протоколе перепланирования. Робастный план найден эвристически. Число отказов зависит от числа введённых портов; правые кривые описывают сценарии, а не вероятности аварий.','scenario_results.csv; robust/result.json',scenario)
    # 14. New variant stress, policies not hidden.
    stress_frames=[]
    for tag,p in [('A',None),('B','cp_ga/search_best_scenarios.csv'),('C','regional/scenarios.csv')]:
        g=scenario[scenario.plan=='base'].copy() if p is None else pd.read_csv(folder/p)
        g['variant']=tag;stress_frames.append(g)
    allstress=pd.concat(stress_frames,ignore_index=True);reg.table(allstress,'14_all_stress')
    fig,axs=canvas(cols=1,height=4.4);g=allstress[(allstress.variant=='C')&allstress.scenario.str.startswith('failed_')].sort_values('completed_trips');ax=axs[0,0]
    ax.barh([names.get(n[7:],n) for n in g.scenario],g.completed_trips/1000,color=COLORS['C']);ax.axvline(results['C']['completed_trips']/1000,color=INK,ls='--',label='C без отказа');ax.set_xlabel('Поездки за 3 года, тыс.');ax.legend(fontsize=7);ax.grid(axis='x',alpha=.6)
    finish(fig,'14_regional_failures','Отказ каждого порта сети C. Активы и постоянные расходы сохраняются; CP-SAT перепланирует рейсы. Обслуживание всех областей требуется только в базовом режиме. Протокол усилен относительно A и B, поэтому различия худших значений не измеряют чистый эффект географии.','regional/scenarios.csv; scenario_cp_manifest.json',g)
    # 15. Annual planning and game.
    yearly=pd.read_csv(folder/'annual_comparison.csv');fig,axs=canvas(height=3.4)
    for ax,n in zip(axs[0],[8,30]):
        for mode,sub in yearly[yearly.instance==n].groupby('mode'):
            ax.plot(sub.year,sub.completed_trips/1000,marker='o' if mode=='joint' else 's',label=mode)
        ax.set(xlabel='Год',ylabel='Поездки за год, тыс.',xticks=[1,2,3]);ax.legend(fontsize=7);panel(ax,'a' if n==8 else 'b',f'{n} пунктов: эвристические планы')
    finish(fig,'15_planning','Последовательный и совместный выбор инвестиций на одинаковом спросе. Панели относятся к сохранённым эвристическим решениям. Отдельное сравнение MIP на 8 пунктах приведено в таблице; полного доказанного сравнения на 30 пунктах нет.','annual_comparison.csv',yearly)
    # 16. Schedule, regional route and residual capacity.
    fig,axs=canvas(cols=1,height=4.2);ax=axs[0,0];fs=pd.DataFrame(results['C']['flights']);fs=fs[fs.year==3];aids=sorted(fs.aircraft_id.unique())
    for j,aid in enumerate(aids):
        for f in fs[fs.aircraft_id==aid].itertuples():
            ax.barh(j,(f.arrival_min-f.departure_min)/60,left=f.departure_min/60,height=.42,color=COLORS['A']);ax.barh(j,(f.charge_end_min-f.arrival_min)/60,left=f.arrival_min/60,height=.42,color='#d6a244')
    ax.set_yticks(range(len(aids)),aids);ax.set(xlim=(8,20),xticks=list(range(8,21,2)),xlabel='Час типичных суток, год 3',ylabel='Аппарат');ax.grid(axis='x',alpha=.6)
    ax.plot([],[],color=COLORS['A'],lw=6,label='Полёт и посадка');ax.plot([],[],color='#d6a244',lw=6,label='Зарядка');ax.legend(ncol=2,loc='upper center',bbox_to_anchor=(.5,1.16))
    finish(fig,'16_schedule','Пять непрерывных суточных маршрутов варианта C. Белые промежутки означают ожидание. Каждый аппарат возвращается к исходному размещению; полная зарядка после каждого перелёта является учебным допущением.','regional/final_best/flights_and_schedule.csv',fs)
    # 17. Routing algorithms, grid and data quality.
    fig,axs=canvas(height=3.5);g=bfs[(bfs.graph=='potential')&bfs.reachable].copy();axs[0,0].scatter(g.bfs_minutes,g.astar_minutes,s=6,color=COLORS['A'],alpha=.4,rasterized=True)
    lim=max(g.bfs_minutes.max(),g.astar_minutes.max());axs[0,0].plot([0,lim],[0,lim],ls='--',lw=.8,color=MUTED);axs[0,0].set(xlabel='Время пути BFS, мин',ylabel='Время пути A*, мин');panel(axs[0,0],'a','Число перелётов и время пути')
    grids=experiments[experiments.experiment=='grid_small'][['value','completed_trips']].copy();grids.loc[len(grids)]=[10,methods[(methods.instance==8)&(methods.method=='greedy')].iloc[0].completed_trips];grids=grids.sort_values('value');axs[0,1].bar(grids.value.astype(int).astype(str),grids.completed_trips/1000,color=COLORS['A']);axs[0,1].set(xlabel='Шаг временной сетки, мин',ylabel='Поездки, тыс.');panel(axs[0,1],'b','8 пунктов: дискретизация')
    finish(fig,'17_paths_grid','BFS минимизирует число участков, A* использует время перелёта, посадки и зарядки. Совпадение A* с Дейкстрой проверено отдельно. В правой панели сравнивается один конструктивный метод при сетках 5, 10 и 15 мин; это не сравнение оптимумов.','bfs_astar.csv; experiments.csv',g)
    reg.table(grids,'17_grid')
    # 18. Quality-data intervention and geographic activity.
    quality=experiments[experiments.experiment=='quality_cap'].iloc[0];qr=json.loads((folder/quality.result_path/'result.json').read_text())
    fig,axs=canvas(height=3.4);vals=[reference,quality.completed_trips];axs[0,0].bar(['Исходное\nнаселение','Ограничение\n95-м процентилем'],np.array(vals)/1000,color=[COLORS['A'],COLORS['C']]);axs[0,0].set_ylabel('Поездки за 3 года, тыс.');panel(axs[0,0],'a','Влияние крайних значений')
    service=pd.read_csv(folder/'regional/region_service.csv');g=service[service.year==3];bars=axs[0,1].bar([REGIONS[r] for r in g.region_code],g.daily_flights,color=[COLORS['A'],COLORS['C'],COLORS['B']]);axs[0,1].bar_label(bars,padding=3,fontsize=8);axs[0,1].tick_params(axis='x',rotation=25);axs[0,1].set_ylabel('Рейсы с вылетом или посадкой, в сутки');axs[0,1].set_ylim(0,72);panel(axs[0,1],'b','Рейсы по областям')
    finish(fig,'18_quality_regions','Слева ограничено только влияние населения на спрос; исходные значения и пункты сохранены, крупное население не объявляется ошибкой. Справа показаны выполненные рейсы C. Межобластной рейс учитывается в обеих областях, поэтому столбцы не суммируются.','experiments.csv; regional/region_service.csv',service)
    # Machine-readable export registry and immutable source provenance.
    for row in reg.rows:
        for key in ('png','pdf'):row[key]=str(Path(row[key]).relative_to(out))
        row['svg']='figures/svg/'+row['figure_id']+'.svg'
        row['png_sha256']=checksum(out/row['png']);row['pdf_sha256']=checksum(out/row['pdf'])
    save(out/'figure_manifest.json',reg.rows)
    for name,frame in [('methods',methods),('experiments',experiments),('seeds',seeds),('search',search),('planning',yearly),('source_requirements',pd.read_csv(folder/'requirements_matrix.csv'))]:reg.table(frame,name)
    provenance={str(p.relative_to(ROOT)):checksum(p) for p in [folder/'towns_main.csv',folder/'config.json',folder/'method_comparison.csv',folder/'experiments.csv',folder/'seed_results.csv',folder/'annual_comparison.csv',folder/'scenario_results.csv',folder/'bfs_astar.csv',folder/'mip_reports.json',folder/'minimax_results.json',folder/'cp_ga/search_results.csv',folder/'cp_ga/search_best_scenarios.csv',folder/'regional/scenarios.csv',folder/'regional/region_service.csv',ROOT/'data/processed_v2/gar_audit.json',ROOT/'data/processed_v2/towns_all.csv',ROOT/'data/processed/region_boundaries.geojson']}
    save(out/'provenance.json',dict(run_id=folder.name,source_hashes={**sources,**provenance},framework='Cinematic Atlas: user-supplied module with white adapter',framework_sha256=checksum(ROOT/'src/droneport/vendor/atlas_theme.py'),font='DejaVu Sans',background='#ffffff',dpi=300,publisher_specific_compliance='not claimed',figures=len(reg.rows)))
    return summary,reg.rows
