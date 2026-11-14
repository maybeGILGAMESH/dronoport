"""Regional coverage results, followed by explicitly historical experiments."""
import io,json,html,shutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from shapely.geometry import shape
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader,PdfWriter
from .ingest import ROOT,checksum
from .pipeline_v2 import save


def append_regional(folder):
    from .report_v2 import offline_map
    out=folder/'report';root=folder/'regional';figdir=out/'figures';charts=[]
    r=json.loads((root/'final_best/result.json').read_text());base=json.loads((folder/'cp_ga/final_best/result.json').read_text())
    comp=pd.read_csv(root/'comparison.csv');service=pd.read_csv(root/'region_service.csv');scenarios=pd.read_csv(root/'scenarios.csv')
    manifest=json.loads((root/'manifest.json').read_text());cp=json.loads((root/'cp_reports.json').read_text())
    towns=pd.read_csv(folder/'towns_main.csv');points=towns.set_index('place_id');names=points.name_original.to_dict()
    regions={50:'Московская',67:'Смоленская',69:'Тверская'};cost=lambda result:sum(b['spend_rub'] for b in result['budget'])
    nf=lambda v:f'{v:,.0f}'.replace(',',' ')
    def finish(fig,stem,caption,evidence):
        fig.tight_layout();fig.savefig(figdir/(stem+'.png'),dpi=170);fig.savefig(figdir/(stem+'.pdf'));plt.close(fig)
        charts.append(dict(name=stem,caption=caption,evidence=evidence,png=f'figures/{stem}.png',sha256=checksum(figdir/(stem+'.png'))))
    boundaries=json.loads((ROOT/'data/processed/region_boundaries.geojson').read_text())
    fig,axs=plt.subplots(1,3,figsize=(13,6))
    for ax,y in zip(axs,(1,2,3)):
        for feature in boundaries['features']:
            geom=shape(feature['geometry']);geoms=list(geom.geoms) if geom.geom_type=='MultiPolygon' else [geom]
            for g in geoms:
                x,z=g.exterior.xy;ax.plot(x,z,color='#aab7be',lw=.7)
        ax.scatter(towns.lon,towns.lat,s=10,color='#aab7be',label='Выборка')
        for a,b in {(f['origin_id'],f['destination_id']) for f in r['flights'] if f['year']==y}:
            aa=points.loc[a];bb=points.loc[b];ax.plot([aa.lon,bb.lon],[aa.lat,bb.lat],color='#187f8c',lw=1.5)
        active=[i for i,v in enumerate(r['plan']['open_years']) if 0<v<=y];ax.scatter(towns.iloc[active].lon,towns.iloc[active].lat,color='#b33e58',s=24)
        for i in active:
            row=towns.iloc[i]
            if row.region_code!=50:ax.annotate(row.name_original,(row.lon,row.lat),xytext=(4,6),textcoords='offset points',fontsize=9)
        ax.set_xlim(towns.lon.min()-.6,towns.lon.max()+.6);ax.set_ylim(towns.lat.min()-.4,towns.lat.max()+.4)
        ax.set_title(f'Год {y}: {len(active)} портов');ax.set_xlabel('Долгота, °');ax.set_ylabel('Широта, °')
    finish(fig,'29_regional_networks','Фактические маршруты по годам. Региональное обслуживание обязательно к третьему году; линии показывают выполненные рейсы, а не потенциальные связи.','regional/final_best/result.json; towns_main.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,5));labels=['Прежний\nрезультат','Только\nстроительство','Порты\nи рейсы']
    for ax,vals,title in [(axs[0],comp.completed_trips/1000,'Поездки за 3 года, тыс.'),(axs[1],comp.cost_rub/1e6,'Расходы за 3 года, млн руб.')]:
        ax.bar(labels,vals,color=['#8193a2','#d28c23','#187f8c']);ax.set_ylabel(title);ax.set_ylim(0,max(vals)*1.15)
        for i,v in enumerate(vals):ax.text(i,v+max(vals)*.02,f'{v:.2f}',ha='center')
    finish(fig,'30_regional_price','Цена обязательного присутствия. В среднем варианте новые порты простаивают: он не удовлетворяет требованию рейсов. Прежняя сеть и первые два года инвестиций сохранены.','regional/comparison.csv')
    year=service[service.year==3];fig,axs=plt.subplots(1,2,figsize=(11,5));labels=[regions[int(v)] for v in year.region_code]
    axs[0].bar(labels,year.daily_flights,color='#187f8c');axs[0].set_ylabel('Рейсы с вылетом или посадкой, в сутки')
    axs[1].bar(labels,year.annual_od_trips/1000,color='#b33e58');axs[1].set_ylabel('Поездки с началом или концом в области, тыс./год')
    for ax,vals in zip(axs,[year.daily_flights,year.annual_od_trips/1000]):
        for i,v in enumerate(vals):ax.text(i,v,f'{v:g}',ha='center',va='bottom')
        ax.set_ylim(0,max(vals)*1.15)
    finish(fig,'31_regional_service','Обслуживание каждой области в третьем году. Межобластной рейс и поездка учитываются у обоих концов: региональные столбцы нельзя суммировать как общий поток.','regional/region_service.csv')
    regional_ids=set(towns[towns.region_code!=50].place_id)
    aircraft={f['aircraft_id'] for f in r['flights'] if f['year']==3 and (f['origin_id'] in regional_ids or f['destination_id'] in regional_ids)}
    fig,ax=plt.subplots(figsize=(12,5));flights=[f for f in r['flights'] if f['year']==3 and f['aircraft_id'] in aircraft]
    aids=sorted(aircraft)
    for f in flights:
        y=aids.index(f['aircraft_id']);dep=f['departure_min']/60;arr=f['arrival_min']/60;end=f['charge_end_min']/60
        ax.barh(y,arr-dep,left=dep,height=.3,color='#187f8c');ax.barh(y,end-arr,left=arr,height=.3,color='#d28c23')
        ax.text((dep+arr)/2,y+.2,names[f['origin_id']]+' → '+names[f['destination_id']]+f'\n{f["passengers"]} пасс.',ha='center',fontsize=7,rotation=30)
    ax.set_yticks(range(len(aids)),aids);ax.set_xlim(8,20);ax.set_ylim(-.6,max(1,len(aids))+.7);ax.set_xlabel('Час типичных суток, год 3');ax.set_title('Бирюзовый — перелёт; охра — зарядка; промежутки — ожидание')
    finish(fig,'32_regional_schedule','Замкнутые суточные маршруты аппаратов, обслуживающих дополнительные области. Вместимость, зарядка, движения и возврат на базу проверены независимым валидатором.','regional/final_best/flights_and_schedule.csv')
    fig,ax=plt.subplots(figsize=(11,6));s=scenarios.sort_values('completed_trips');labels=[names.get(n[7:],n) if n.startswith('failed_') else {'base':'База','demand_070':'Спрос −30%','demand_130':'Спрос +30%','range_160':'Дальность 160 км'}[n] for n in s.scenario]
    ax.barh(labels,s.completed_trips/1000,color='#187f8c');ax.set_xlabel('Завершённые поездки за 3 года, тыс.')
    finish(fig,'33_regional_stress','Стресс-проверка регионального плана: постоянные расходы сохраняются, после отказа расписание перестраивается. Требование обслуживания всех областей гарантируется для нормального режима, но не при отказе единственного регионального порта.','regional/scenarios.csv')
    loss=base['completed_trips']-r['completed_trips'];extra=cost(r)-cost(base)
    successful=[p for p in cp if p.get('status')!='PROCESS_FAILED'];last=successful[-1] if successful else {}
    paragraphs=[
        ('Итоговая версия: порты и рейсы в каждой области',f'Вариант И: Тверская, Смоленская и Московская области (задание, с. 4). Пять букв ЖЗИКЛ ограничивают названия пунктов, а не количество областей. Исходное задание на с. 3 не требует строительства в каждом регионе; здесь введено дополнительное условие пользователя. К третьему году в каждой области должен действовать хотя бы один порт и выполняться хотя бы один рейс с вылетом или посадкой в этой области в типичные сутки. Новый запуск: {folder.name}.'),
        ('Полученный результат',f'{nf(r["completed_trips"])} завершённых поездок за три года; расходы {nf(cost(r))} руб.; остаток {nf(r["budget"][-1]["carry_rub"])} руб. Введено {r["budget"][-1]["active_ports"]} портов, приобретено {r["budget"][-1]["active_aircraft"]} аппаратов. По сравнению с сохранённым результатом {nf(base["completed_trips"])} поездок разница составляет {nf(-loss)} поездок ({-loss/base["completed_trips"]:.2%}), дополнительные расходы {nf(extra)} руб. Это цена найденного допустимого решения, а не доказанный минимум потерь от регионального условия.'),
        ('Как обеспечено обслуживание', 'В третьем году добавлены Кардымово в Смоленской области и Зубцов в Тверской. Первый и второй годы инвестиций сохранены. Межрегиональные рейсы выполняет существующий флот; каждый аппарат возвращается на свою базу. Дополнительно приведено строительство тех же портов без рейсов: этот контрольный вариант не выполняет пользовательское условие. Загрузка и региональные OD-поездки показаны отдельно; пустой рейс считается рейсом, но не пассажирской поездкой.'),
        ('Область поиска и статус оптимизации',f'На фиксированной выборке проверено {manifest["candidates"]} вариантов замкнутого маршрута: два смоленских пункта, достижимые тверские посредники, существующие аппараты и сдвиги старта 0/30/60 минут. Допустимых расписаний {manifest["feasible"]}. CP-SAT затем оптимизирует рейсы и пассажирские потоки при фиксированных инвестициях. Последний статус: {last.get("status","нет успешного запуска")}; условная верхняя граница: {nf(last["upper_bound"]) if last.get("upper_bound") is not None else "не получена"} поездок. Лимит 180 секунд, 8 поисковых потоков, ограничение виртуальной памяти 20 ГиБ. Первоначальная техническая ошибка запуска сохранена в журнале и исправлена; она не является результатом оптимизации. Глобальный поиск всех инвестиций заново не выполнялся, оптимальность регионального плана не доказана.'),
        ('Ограничения и воспроизводимость',f'Сохранены временная сетка 10 минут, окно 08:00–20:00, 10 мест, дальность 200 км, полная зарядка после рейса и накопленный бюджет до 3 млрд руб. Независимо проверены основное расписание и {len(scenarios)} сценариев, включая отказ каждого из 13 введённых портов. Худший найденный результат — {nf(scenarios.completed_trips.min())} поездок. Во всех стресс-сценариях инвестиции фиксированы, а региональный минимум рейсов не навязывался: он гарантируется для базового режима. При отказе единственного порта области обслуживание этой области невозможно. После эвристического восстановления выполнен CP-SAT на пуле рейсов: 15 с, 4 потока, два процесса по 9 ГиБ; для двух худших отказов — полная сетка, 60 с и 8 потоков, до 20 ГиБ. Эти результаты являются допустимыми нижними оценками; ограниченный поиск может дать немонотонную зависимость от спроса. Неоднозначности полноты реестра и учебный характер спроса сохраняются. Далее приведены прежние эксперименты без регионального ограничения; их результаты нельзя выдавать за сравнение алгоритмов в новой постановке.')]
    body=ParagraphStyle('regbody',fontName='DV',fontSize=9,leading=13,spaceAfter=8);head=ParagraphStyle('reghead',fontName='DV-B',fontSize=13,leading=17,spaceBefore=10,spaceAfter=8)
    story=[]
    def table(rows,widths):
        t=Table(rows,colWidths=widths,repeatRows=1);t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'DV'),('FONTSIZE',(0,0),(-1,-1),8),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eff3')),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(t)
    for i,(title,text) in enumerate(paragraphs):
        content=[Paragraph(html.escape(title),head),Paragraph(html.escape(text),body)]
        if i==len(paragraphs)-1:story.append(KeepTogether(content))
        else:story.extend(content)
        if i==1:
            table([['Область, год 3','Портов','Рейсов/сутки','С пассажирами']]+[[regions[int(v.region_code)],v.ports,v.daily_flights,v.loaded_flights] for v in year.itertuples()],[165,70,115,145])
        if i==2:
            table([['Год','Поездки','Расходы, млн руб.','Остаток, млн руб.']]+[[y,nf(r['annual_completed'][y-1]),f'{r["budget"][y-1]["spend_rub"]/1e6:.3f}',f'{r["budget"][y-1]["carry_rub"]/1e6:.3f}'] for y in (1,2,3)],[45,120,165,165])
    for j,c in enumerate(charts,29):
        from PIL import Image as PILImage
        path=figdir/(c['name']+'.png');w,h=PILImage.open(path).size
        if j>29:story.append(PageBreak())
        story.append(Image(str(path),width=495,height=495*h/w));story.append(Paragraph(f'Рисунок {j}. '+html.escape(c['caption'])+'<br/>Данные: '+html.escape(c['evidence']),body))
    supplement=out/'regional_supplement.pdf';SimpleDocTemplate(str(supplement),pagesize=(595,842),leftMargin=50,rightMargin=50,topMargin=40,bottomMargin=40).build(story)
    old=out/'previous_cp_ga_report.pdf';shutil.copy2(out/'report.pdf',old);writer=PdfWriter()
    for path in (supplement,old):
        for p in PdfReader(path).pages:writer.add_page(p)
    for i,page in enumerate(writer.pages,1):
        stream=io.BytesIO();c=Canvas(stream,pagesize=(float(page.mediabox.width),float(page.mediabox.height)));c.setFillColor(colors.white);c.rect(float(page.mediabox.width)-75,15,65,20,fill=1,stroke=0);c.setFillColor(colors.black);c.setFont('DV',7);c.drawRightString(float(page.mediabox.width)-40,24,str(i));c.save();stream.seek(0);page.merge_page(PdfReader(stream).pages[0])
    writer.add_metadata({'/Title':'Дронопорты: обязательные порты и рейсы в трёх областях'})
    with (out/'report.pdf').open('wb') as f:writer.write(f)
    md='\n\n'.join('## '+h+'\n\n'+t for h,t in paragraphs)+'\n\n'+'\n\n'.join(f'![{c["caption"]}]({c["png"]})\n\nДанные: {c["evidence"]}' for c in charts)
    (out/'regional_supplement.md').write_text(md)
    investments=[];annual=[]
    for y in (1,2,3):
        opened=[i for i,v in enumerate(r['plan']['open_years']) if v==y];bought=[a for a in r['plan']['aircraft'] if a['year']==y]
        annual.append(f'Год {y}: открыть '+', '.join(towns.iloc[i].name_original for i in opened)+f'; купить аппаратов {len(bought)}; поездок {nf(r["annual_completed"][y-1])}.')
        for i in opened:investments.append(dict(kind='port',year=y,name=towns.iloc[i].name_original,region_code=int(towns.iloc[i].region_code),place_id=towns.iloc[i].place_id,aircraft_id=''))
        for a in bought:investments.append(dict(kind='aircraft',year=y,name=towns.iloc[a['home']].name_original,region_code=int(towns.iloc[a['home']].region_code),place_id=towns.iloc[a['home']].place_id,aircraft_id=a['id']))
    pd.DataFrame(investments).to_csv(out/'regional_investments.csv',index=False)
    for filename in ('report.md','executive_summary.txt','executive_summary.md'):
        p=out/filename;previous=p.read_text();intro=md if filename=='report.md' else '\n\n'.join(t for _,t in paragraphs[:3])+'\n\n'+'\n\n'.join(annual)+'\n\n'+paragraphs[-1][1]
        p.write_text(intro+'\n\n---\n\nПрежние результаты без регионального ограничения\n\n'+previous)
    p=out/'report.html';previous=p.read_text();addition=''.join('<h2>'+html.escape(h)+'</h2><p>'+html.escape(t)+'</p>' for h,t in paragraphs)
    addition+=''.join('<figure><img src="'+c['png']+'"><figcaption>'+html.escape(c['caption'])+'</figcaption></figure>' for c in charts)
    p.write_text(previous.replace('</style>','</style><h1>Порты и рейсы во всех трёх областях</h1><p><a href="maps/network_regional.html">Карта регионального плана</a></p>'+addition+'<h1>Прежние эксперименты без регионального условия</h1>',1))
    existing=json.loads((out/'figure_manifest.json').read_text());save(out/'figure_manifest.json',existing+charts)
    offline_map(folder,out/'maps/network_regional.html',r)
    p=out/'maps/network_regional.html';p.write_text(p.read_text().replace('Дополнительный поиск:','Порты и рейсы в трёх областях:'))
    save(root/'report_summary.json',dict(completed_trips=r['completed_trips'],cost_rub=cost(r),loss_trips=loss,extra_cost_rub=extra,pages=len(writer.pages),figures=len(existing)+len(charts)))
