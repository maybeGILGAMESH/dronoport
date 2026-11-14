"""New experimental section, followed by the preserved baseline study."""
from pathlib import Path
import io,json,html,shutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from reportlab.platypus import BaseDocTemplate,Frame,PageTemplate,NextPageTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader,PdfWriter
from .pipeline_v2 import save
from .ingest import checksum


def append_experiments(folder):
    from .report_v2 import offline_map
    out=folder/'report';root=folder/'cp_ga';figdir=out/'figures';charts=[]
    fixed=pd.read_csv(root/'fixed_results.csv');search=pd.read_csv(root/'search_results.csv')
    base=json.loads((folder/'base/result.json').read_text());portfolio=json.loads((root/'portfolio_30/result.json').read_text())
    cp_report=json.loads((root/'portfolio_30/solver_report.json').read_text());manifest=json.loads((root/'search_manifest.json').read_text())
    search_best=json.loads((root/'search_best/result.json').read_text());best=json.loads((root/'final_best/result.json').read_text());scenarios=pd.read_csv(root/'search_best_scenarios.csv')
    towns=pd.read_csv(folder/'towns_main.csv');names=dict(zip(towns.place_id,towns.name_original))
    initial=json.loads((root/'search_start/result.json').read_text());paired=search.pivot(index='seed',columns='method',values='completed_trips');paired['ga_minus_sa']=paired.ga-paired.sa
    paired.to_csv(root/'paired_results.csv');cost=lambda r:sum(b['spend_rub'] for b in r['budget'])
    summary=[['Сохранённая база',base['completed_trips'],cost(base)/1e6],['CP-SAT, 8 потоков',portfolio['completed_trips'],cost(portfolio)/1e6]]
    for method,label in [('sa','Отжиг + CP-SAT'),('ga','GA + CP-SAT')]:
        row=search[search.method==method].sort_values(['completed_trips','cost_rub'],ascending=[False,True]).iloc[0]
        summary.append([label,int(row.completed_trips),row.cost_rub/1e6])
    summary.append(['После распределения потоков',best['completed_trips'],cost(best)/1e6])
    summary_frame=pd.DataFrame(summary,columns=['method','completed_trips','cost_million']);summary_frame.to_csv(root/'summary.csv',index=False)
    def finish(fig,stem,title,source):
        fig.tight_layout();fig.savefig(figdir/(stem+'.png'),dpi=170);fig.savefig(figdir/(stem+'.pdf'));plt.close(fig)
        charts.append(dict(name=stem,title=title,source=source,caption=title,evidence=source,png=f'figures/{stem}.png',sha256=checksum(figdir/(stem+'.png'))))
    fig,ax=plt.subplots(figsize=(10,5));values=summary_frame.completed_trips/1000
    labels=['Исходная\nбаза','CP-SAT\n8 потоков','Отжиг\n+ CP-SAT','GA\n+ CP-SAT','Дораспределение\nпассажиров']
    ax.bar(labels,values,color=['#8193a2','#187f8c','#d28c23','#b33e58','#586a95']);ax.set_ylabel('Завершённые поездки за 3 года, тыс.')
    for i,v in enumerate(values):ax.text(i,v+2,f'{v:g}',ha='center')
    ax.set_ylim(0,max(values)*1.14);ax.set_title('Сохранённая база, новое расписание и поиск сети')
    finish(fig,'21_cp_ga_quality','В поисковых сериях показан лучший из 10 seed. Последний столбец — отдельное перераспределение пассажиров после серии; его улучшение не приписывается GA или отжигу.','cp_ga/summary.csv')
    fig,axs=plt.subplots(1,2,figsize=(12,6))
    for ax,label in zip(axs,['base','robust']):
        data=fixed[fixed.name.str.startswith(label+'_failed_')].sort_values('before');x=np.arange(len(data))
        ax.barh(x-.17,data.before/1000,height=.32,label='До CP-SAT');ax.barh(x+.17,data.completed_trips/1000,height=.32,label='После CP-SAT')
        ax.set_yticks(x,[names.get(n.split('_failed_')[1],n) for n in data.name]);ax.set_title('Исходная сеть' if label=='base' else 'Робастная сеть');ax.set_xlabel('Поездки за 3 года, тыс.');ax.legend(fontsize=8)
    finish(fig,'22_cp_failures','Отказ каждого построенного порта: инвестиции и плановые базы фиксированы, постоянные расходы сохраняются. Только актуальные сценарии исходного запуска.','cp_ga/fixed_results.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,5));axs[0].boxplot([paired.sa/1000,paired.ga/1000],tick_labels=['Отжиг + CP','GA + CP'])
    for _,r in paired.iterrows():axs[0].plot([1,2],[r.sa/1000,r.ga/1000],alpha=.4,marker='o')
    axs[0].axhline(initial['completed_trips']/1000,ls='--',color='gray',label='Общий старт');axs[0].legend(fontsize=8);axs[0].set_ylabel('Поездки, тыс.')
    axs[1].bar(paired.index,paired.ga_minus_sa/1000,color='#187f8c');axs[1].axhline(0,color='gray');axs[1].set_xlabel('Seed');axs[1].set_ylabel('GA − отжиг, тыс. поездок')
    finish(fig,'23_cp_ga_seeds','Парные seed имеют одинаковый старт, данные, ремонт и CP-декодер. Линии соединяют соответствующие seed; это не независимые наблюдения пассажирского спроса.','cp_ga/search_results.csv; cp_ga/paired_results.csv')
    fig,axs=plt.subplots(1,2,figsize=(11,5))
    for ax,method in zip(axs,['sa','ga']):
        for row in search[search.method==method].itertuples():
            h=pd.read_csv(folder/row.result_path/'history.csv');ax.step(h.elapsed,h.best/1000,where='post',alpha=.65,label=str(row.seed))
        ax.set_title('Отжиг + CP' if method=='sa' else 'GA + CP');ax.set_xlabel('Прошедшее время, с');ax.set_ylabel('Лучшие поездки, тыс.');ax.legend(title='Seed',ncol=5,fontsize=7)
    finish(fig,'24_cp_ga_search','История лучшего допустимого результата. Лимит относится ко всему запуску; уже начатая оценка кандидата может немного выйти за него.','cp_ga/search/*/seed_*/history.csv')
    records=[]
    for row in search.itertuples():
        path=folder/row.result_path/'decoder_evaluations.csv';f=pd.read_csv(path)
        records.append(dict(method=row.method,seed=row.seed,evaluations=len(f),cp_improved=int((f.cp_improvement.fillna(0)>0).sum()),
            seconds=float(f.wall_seconds.sum()),failed=int(f.status.eq('PROCESS_FAILED').sum())))
    decoder=pd.DataFrame(records);decoder.to_csv(root/'decoder_summary.csv',index=False)
    fig,axs=plt.subplots(1,2,figsize=(10,5));agg=decoder.groupby('method').sum(numeric_only=True).reindex(['sa','ga']);x=np.arange(2)
    axs[0].bar(x-.18,agg.evaluations,.35,label='Все оценки');axs[0].bar(x+.18,agg.cp_improved,.35,label='CP улучшил расписание');axs[0].set_xticks(x,['Отжиг','GA']);axs[0].legend();axs[0].set_ylabel('Число кандидатов за 10 seed')
    axs[1].bar(x,agg.seconds/60);axs[1].set_xticks(x,['Отжиг','GA']);axs[1].set_ylabel('Сумма времени оценок, мин')
    finish(fig,'25_cp_decoder','Оба метода используют один построитель расписания. Ограниченный пул рейсов ускоряет оценки; его верхняя граница не относится ко всем расписаниям или инвестиционным сетям.','cp_ga/decoder_summary.csv')
    fig,axs=plt.subplots(1,3,figsize=(12,5))
    for ax,r,label in zip(axs,[base,portfolio,best],['Исходная сеть','CP: те же инвестиции','Итог после проверки']):
        ax.scatter(towns.lon,towns.lat,s=8,color='#bcc6cc')
        for a,b in {(f['origin_id'],f['destination_id']) for f in r['flights'] if f['year']==3}:
            aa=towns[towns.place_id==a].iloc[0];bb=towns[towns.place_id==b].iloc[0];ax.plot([aa.lon,bb.lon],[aa.lat,bb.lat],color='#187f8c',alpha=.6)
        ids=[i for i,y in enumerate(r['plan']['open_years']) if y];ax.scatter(towns.iloc[ids].lon,towns.iloc[ids].lat,s=30,color='#b33e58')
        ax.set_title(label);ax.set_xlabel('Долгота, °');ax.set_ylabel('Широта, °')
    finish(fig,'26_cp_ga_networks','Сети третьего года на одной фиксированной выборке. Изменение количества поездок может происходить за счёт расписания и пассажирских потоков без изменения географии.','base/result.json; cp_ga/portfolio_30/result.json; cp_ga/final_best/result.json')
    fig,axs=plt.subplots(1,2,figsize=(11,5));x=np.arange(3)
    for shift,r,label in [(-.25,base,'Исходная база'),(0,portfolio,'CP-SAT'),(.25,best,'Итоговый план')]:
        axs[0].bar(x+shift,np.array(r['annual_completed'])/1000,.25,label=label)
        axs[1].bar(x+shift,np.array([b['spend_rub'] for b in r['budget']])/1e6,.25,label=label)
    for ax in axs:ax.set_xticks(x,['Год 1','Год 2','Год 3']);ax.legend(fontsize=8)
    axs[0].set_ylabel('Поездки, тыс.');axs[1].set_ylabel('Расходы за год, млн руб.')
    finish(fig,'27_cp_ga_annual','Расходы включают реальные рейсы и межгодовые перегоны; превышение годового транша допустимо только за счёт накопленного остатка. Последний вариант включает отдельное распределение пассажиров после поиска.','base/result.json; cp_ga/portfolio_30/result.json; cp_ga/final_best/result.json')
    fig,ax=plt.subplots(figsize=(11,6));f=scenarios.sort_values('completed_trips');labels=[names.get(n[7:],n) if n.startswith('failed_') else {'base':'База','demand_070':'Спрос −30%','demand_130':'Спрос +30%','range_160':'Дальность 160 км'}[n] for n in f.scenario]
    ax.barh(labels,f.completed_trips/1000,color='#187f8c');ax.set_xlabel('Поездки за 3 года, тыс.');ax.set_title('Отдельная проверка сети, выбранной новым поиском')
    finish(fig,'28_cp_ga_stress','Новый лучший план проверен заново: при отказах фиксированы его собственные инвестиции. Это оценка сценариев, а не новый робастный оптимум.','cp_ga/search_best_scenarios.csv')
    nfmt=lambda v:f'{v:,.0f}'.replace(',',' ')
    paragraphs=[
        ('Дополнение: CP-SAT и генетический алгоритм',f'Новый запуск {folder.name}. Базовое исследование сохранено без подмены результатов: {nfmt(base["completed_trips"])} поездок, {nfmt(cost(base))} руб. Первоначальные результаты и эксперименты приведены далее отдельным разделом. Новое исследование проверяет улучшение расписания фиксированной сети, затем сравнивает GA и отжиг на общем построителе расписания.'),
        ('Что изменил CP-SAT',f'При тех же портах, датах покупок и базах аппаратов найдено {nfmt(portfolio["completed_trips"])} поездок; изменение {nfmt(portfolio["completed_trips"]-base["completed_trips"])}. Расходы {nfmt(cost(portfolio))} руб. Статус {cp_report["status"]}; верхняя граница {nfmt(cp_report["upper_bound"])} относится только к фиксированным инвестициям и принятой временной сетке. Восемь поисковых потоков, лимит 180 с, фактическое время процесса {cp_report["process_wall_seconds"]:.1f} с, пик RSS {cp_report["peak_rss_mib"]/1024:.2f} ГиБ. Потолок виртуальной памяти 20 ГиБ. Первая попытка с одним потоком и повтор с восемью сохранены отдельно; полный расход времени включает обе попытки.'),
        ('Постановка CP-SAT','На открытых узлах строится сеть событий с шагом 10 минут. Целочисленные потоки аппаратов разделены по фактическим базам: столько же аппаратов возвращается на каждую базу к 20:00, сколько вышло из неё в 08:00. Дуга полёта включает посадку и последующую полную зарядку; дуги ожидания сохраняют местоположение. Потоки пассажиров разделены по назначениям, ограничены OD-спросом и вместимостью выбранных рейсов. Зарядки ограничены в каждый момент, движения — в фиксированных 90-минутных интервалах. Все три года решаются совместно с накопленным бюджетом. Межгодовые базы фиксированы, перегоны и расходы проверяются отдельно. Это CP-SAT на целочисленной временной сети, без непрерывных времён отправления.'),
        ('Сценарии фиксированной сети',f'В основной таблице {len(fixed)} случаев: малая задача, основная и робастная сети, спрос ±30%, дальность 160 км и отказы каждого построенного порта. В сценариях использован один поисковый поток и 60 с. Число улучшенных случаев: {int((fixed.gain>0).sum())}. Полный сценарный перебор не использует восемь потоков из отдельной основной попытки. Неодинаковые лимиты и режимы явно разделены. Исторические каталоги прежних сетей исключены из сравнительной таблицы по актуальному манифесту сценариев.'),
        ('Хромосома и восстановление допустимости','Первая часть хромосомы: 30 генов со значениями 0/1/2/3 — отсутствие порта или год открытия. Для каждого из 12 возможных аппаратов: год закупки (0 означает отсутствие) и базы трёх лет. Мутации меняют порт, год покупки, одну или несколько баз либо одновременно покупку и базу. Ремонт открывает необходимые базы вовремя и удаляет поздние необязательные активы до выполнения накопленных фиксированных затрат. Перегоны и энергия проверяются при построении расписания. Недопустимый кандидат не получает положительную оценку. Названия аппаратов не считаются разнообразием сети.'),
        ('Как сравнивались GA и отжиг',f'Оба метода начинают с {nfmt(initial["completed_trips"])} поездок и имеют одинаковые мутации, ремонт и CP-декодер. GA: популяция 12, турнир из трёх кандидатов, скрещивание по портам и блокам аппаратов, сохранение двух лучших, удаление дублей. Отжиг: один текущий план, вероятностное принятие ухудшений, линейное охлаждение по времени. По 10 seed, по {manifest["seconds_per_seed"]:g} секунд на запуск. Одновременно до {manifest["workers"]} запусков, поэтому это сравнение при совместной нагрузке, не изолированный процессорный тест. Сумма времён запусков {manifest["summed_run_seconds"]:.1f} с; время серии {manifest["wall_seconds"]:.1f} с.'),
        ('Общий построитель расписания','Для каждой сети создаются три конструктивных расписания с фиксированными seed. CP-SAT выбирает и комбинирует рейсы из их объединения и начального расписания; ограничения пассажирских потоков и ресурсов сохраняются. На оценку: 0.2 единицы детерминированной работы CP-SAT и страховочный предел 10 секунд, один поток, seed 0. Существующее допустимое расписание сохраняется, если решатель не улучшил его. Это ограниченная поисковая окрестность; оптимум её CP-модели не является оптимумом полной временной сети. Общий старт получен отдельным полным CP-расчётом, его затраты не включены в десятиминутный бюджет каждого метода и приведены отдельно.'),
        ('Результаты парного сравнения',f'GA лучше отжига по поездкам в {int((paired.ga_minus_sa>0).sum())} seed, хуже в {int((paired.ga_minus_sa<0).sum())}, совпал в {int((paired.ga_minus_sa==0).sum())}. Медианная парная разность GA − отжиг: {nfmt(paired.ga_minus_sa.median())} поездок. Лучший результат самой поисковой серии {nfmt(search_best["completed_trips"])} поездок. При равных поездках выбирается меньшая стоимость. Это описательное сравнение десяти пар; преимущества метода за пределами этих экземпляра, настроек и бюджета не утверждаются. При последующей сценарной проверке повторное целочисленное распределение пассажиров по найденным рейсам дало {nfmt(best["completed_trips"])} поездок, расходы {nfmt(cost(best))} руб. Этот отдельный этап использует существующий потоковый MIP и полный CP-SAT для проверки/улучшения; его прирост не относится к GA или отжигу. Итоговый эксплуатационный план сохранён в cp_ga/final_best.'),
        ('Ограничения и проверка',f'Новый лучший план проверен в {len(scenarios)} сценариях; худшее найденное значение {nfmt(scenarios.completed_trips.min())} поездок. GA не доказывает оптимальность; границы CP-SAT условны относительно фиксированных инвестиций и, в быстром декодере, пула рейсов. Сохраняются прежние ограничения данных и незавершённый последовательный MIP на 30 пунктах. Все публикуемые расписания проверяет независимый валидатор; численные строки связаны с JSON, конфигурациями и снимками исходников. Ошибок запуска CP-декодера в поисковой серии: {int(decoder.failed.sum())}.')]
    flights_cp={f['flight_id']:f for f in portfolio['flights']}
    multi=[t for t in portfolio['itineraries'] if t['transfers']>0]
    changes=sum(len({flights_cp[k]['aircraft_id'] for k in json.loads(t['flight_ids'])})>1 for t in multi)
    flight_counts=lambda r:[sum(f['year']==y for f in r['flights']) for y in (1,2,3)]
    paragraphs[1]=(paragraphs[1][0],paragraphs[1][1]+f' Рейсов в типичные сутки по годам: {flight_counts(base)} → {flight_counts(portfolio)}. Дополнительные расходы {nfmt(cost(portfolio)-cost(base))} руб. Многоучастковых поездок в трёх типичных суточных расписаниях {len(multi)}, из них со сменой аппарата {changes}; остальные продолжаются на том же аппарате после промежуточной посадки и зарядки.')
    segments=sum(f['passengers'] for f in portfolio['flights'] if f['year']==3);completed=sum(t['year']==3 for t in portfolio['itineraries'])
    paragraphs[1]=(paragraphs[1][0],paragraphs[1][1]+f' В типичные сутки третьего года занято {segments} мест на отдельных участках, но завершено {completed} поездок: промежуточные участки не увеличивают целевой пассажиропоток.')
    style=ParagraphStyle('cpbody',fontName='DV',fontSize=9,leading=13,spaceAfter=8);head=ParagraphStyle('cphead',fontName='DV-B',fontSize=13,leading=17,spaceBefore=12,spaceAfter=8)
    story=[]
    for i,(title,text) in enumerate(paragraphs):
        story.extend([Paragraph(html.escape(title),head),Paragraph(html.escape(text),style)])
        if i==1:
            table=[['Метод','Поездки','Расходы, млн руб.']]+[[r[0],nfmt(r[1]),f'{r[2]:.3f}'] for r in summary]
            t=Table(table,colWidths=[220,115,175],repeatRows=1);t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'DV'),('FONTSIZE',(0,0),(-1,-1),8),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eff3')),('BOTTOMPADDING',(0,0),(-1,-1),8)]));story.append(t)
    story.extend([Paragraph('Структура документа',head),Paragraph('Далее представлены рисунки дополнительного эксперимента, затем сохранённое базовое исследование. Его показатели не заменены результатами нового поиска. Актуальное сравнение CP-SAT, GA и отжига находится в начале документа.',style),NextPageTemplate('figures'),PageBreak()])
    for k,chart in enumerate(charts,21):
        story.extend([Paragraph(f'Рисунок {k}. '+html.escape(chart['title']),head),Image(str(out/chart['png']),width=746,height=390,kind='proportional'),Paragraph('Данные: '+html.escape(chart['source']),style)])
        if k<20+len(charts):story.append(PageBreak())
    supplement=out/'cp_ga_supplement.pdf'
    doc=BaseDocTemplate(str(supplement),pagesize=(595,842),leftMargin=42,rightMargin=42,topMargin=36,bottomMargin=38)
    doc.addPageTemplates([PageTemplate(id='text',frames=[Frame(42,38,511,768,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],pagesize=(595,842)),
        PageTemplate(id='figures',frames=[Frame(48,40,746,515,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],pagesize=(842,595))])
    doc.build(story)
    baseline=out/'baseline_report.pdf';shutil.copy2(out/'report.pdf',baseline);writer=PdfWriter()
    for filename in (supplement,baseline):
        for page in PdfReader(filename).pages:writer.add_page(page)
    for i,page in enumerate(writer.pages,1):
        stream=io.BytesIO();canvas=Canvas(stream,pagesize=(float(page.mediabox.width),float(page.mediabox.height)))
        canvas.setFillColor(colors.white);canvas.rect(float(page.mediabox.width)-75,15,65,20,fill=1,stroke=0);canvas.setFillColor(colors.black);canvas.setFont('DV',7);canvas.drawRightString(float(page.mediabox.width)-40,24,str(i));canvas.save();stream.seek(0);page.merge_page(PdfReader(stream).pages[0])
    writer.add_metadata({'/Title':'Сеть дронопортов: CP-SAT, генетический алгоритм и базовое исследование','/Author':'Учебный исследовательский проект'})
    with (out/'report.pdf').open('wb') as f:writer.write(f)
    md='\n\n'.join('## '+h+'\n\n'+t for h,t in paragraphs)
    md+='\n\n'+'\n\n'.join(f'![{c["title"]}]({c["png"]})\n\nДанные: {c["source"]}' for c in charts)
    (out/'cp_ga_supplement.md').write_text(md)
    investments=[];executive=[]
    for y in (1,2,3):
        opened=[i for i,v in enumerate(best['plan']['open_years']) if v==y]
        bought=[a for a in best['plan']['aircraft'] if a['year']==y]
        executive.append(f'Год {y}: новые порты — '+(', '.join(towns.iloc[i].name_original for i in opened) or 'нет')+f'; аппаратов купить {len(bought)}; поездок {nfmt(best["annual_completed"][y-1])}; расходы {nfmt(best["budget"][y-1]["spend_rub"])} руб.')
        for i in opened:investments.append(dict(kind='port',year=y,name=towns.iloc[i].name_original,place_id=towns.iloc[i].place_id,aircraft_id=''))
        for a in bought:investments.append(dict(kind='aircraft',year=y,name=towns.iloc[a['home']].name_original,place_id=towns.iloc[a['home']].place_id,aircraft_id=a['id']))
    pd.DataFrame(investments).to_csv(out/'optimized_investments.csv',index=False)
    for filename in ('report.md','executive_summary.md','executive_summary.txt'):
        p=out/filename;old=p.read_text();p.write_text(md+'\n\n---\n\nСохранённое базовое исследование\n\n'+old if filename=='report.md' else paragraphs[0][1]+'\n\n'+paragraphs[1][1]+'\n\n'+paragraphs[-2][1]+'\n\n'+'\n\n'.join(executive)+'\n\nСохранённая записка исходного расчёта:\n\n'+old)
    p=out/'report.html';old=p.read_text();addition=''.join('<h2>'+html.escape(h)+'</h2><p>'+html.escape(t)+'</p>' for h,t in paragraphs)
    addition+=''.join('<figure><img style="max-width:100%" src="'+c['png']+'"><figcaption>'+html.escape(c['title'])+'</figcaption></figure>' for c in charts)
    p.write_text(old.replace('</style>','</style><h1>CP-SAT и генетический алгоритм</h1><p><a href="maps/network_cp_ga.html">Карта нового лучшего плана</a></p>'+summary_frame.to_html(index=False)+addition+'<h1>Сохранённое базовое исследование</h1>',1))
    existing=json.loads((out/'figure_manifest.json').read_text());save(out/'figure_manifest.json',existing+charts)
    offline_map(folder,out/'maps/network_cp_ga.html',best)
    save(root/'report_summary.json',dict(baseline_trips=base['completed_trips'],fixed_cp_trips=portfolio['completed_trips'],best_search_trips=search_best['completed_trips'],best_trips=best['completed_trips'],best_cost_rub=cost(best),
        ga_wins=int((paired.ga_minus_sa>0).sum()),sa_wins=int((paired.ga_minus_sa<0).sum()),ties=int((paired.ga_minus_sa==0).sum()),
        best_worst_scenario=int(scenarios.completed_trips.min()),pages=len(writer.pages),figures=len(existing)+len(charts)))
