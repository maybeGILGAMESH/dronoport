"""LaTeX and network-free MathML edition of the preserved comparative article."""
from pathlib import Path
import json,re,html,hashlib
from latex2mathml.converter import convert
from .ingest import ROOT,checksum
from .latex_content import FORMULAS,AXES


def escape(value):
    chars={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(chars.get(c,c) for c in str(value))


def enhanced_blocks(article):
    result=[];equation=0
    for original in article['blocks']:
        b=dict(original)
        if b['kind']=='equation':
            equation+=1;result.append(dict(kind='math',key=str(equation)));continue
        text=b.get('text','')
        after=[]
        if text.startswith('Совокупный спрос фиксированной'):
            b['text']=text.replace('Индекс направленной асимметрии первого года, Σ|qᵢⱼ − qⱼᵢ| / Σqᵢⱼ, равен 0,101.','Индекс направленной асимметрии первого года равен 0,101; его точное определение приведено ниже.')
            after=['1a']
        elif text.startswith('Множество V содержит'):
            b['text']=text.replace('Внутри суток используются моменты t = 0,…,T, где T = 720/Δ и Δ = 10 мин.','Внутри суток используются моменты сетки от 0 до T с шагом 10 минут. Продолжительности определены в формуле (1b).')
            after=['1b']
        elif text.startswith('В каждом промежуточном узле'):
            b['text']=text.replace('Общая вместимость ограничивается на каждой дуге рейса:','Сохранение потока аппаратов записано в формуле (2a), а общая вместимость ограничивается на каждой дуге рейса формулой (3).')
            after=['2a']
        elif text.startswith('Рейс разрешён только между'):
            after=['3a']
        elif text.startswith('Здесь Xᵧ и Nᵧ'):
            b['text']='Покупки и введённые активы связаны с годовым бюджетом формулой (6). Неотрицательный остаток из формулы (5) равносилен накопленному ограничению (5a) для каждого префикса горизонта. Оно разрешает тратить остаток прошлых лет и запрещает расходовать будущие транши. Объекты вводятся в начале года, поэтому им начисляются полный годовой OPEX и 330 суток эксплуатации.'
            after=['5a']
        elif text.startswith('Смешанно-целочисленная постановка'):
            b['text']=text.replace('нижнюю оценку F*','нижнюю оценку F').replace('В статье разрыв определяется как (U − F)/max(F,1).','Разрыв определяется формулой (8); его область действия всегда указывается вместе с результатом.')
            after=['8']
        elif text.startswith('На потенциальном графе и построенных'):
            b['text']=text.replace('Эвристика h(i,d) = 60Dᵢd/240 не превышает стоимость допустимого пути,','Эвристика из формулы (9) не превышает стоимость допустимого пути,')
            after=['9']
        elif text.startswith('В объединённый архив включены'):
            b['text']=text+' Настоящая редакция набрана LaTeX, все выделенные формулы сопровождаются расшифровкой обозначений. Подробные карты получены локально из OSM, проверены при выключенном сервере и отключённой сети, затем включены в приложение C.'
        result.append(b)
        result.extend(dict(kind='math',key=key) for key in after)
    assert equation==7
    return result


PREAMBLE=r'''\documentclass[10pt,a4paper]{article}
\usepackage{fontspec,polyglossia,amsmath,amssymb,graphicx,geometry,longtable,booktabs,array,caption,float,fancyhdr,enumitem,xcolor,hyperref,pdflscape}
\setdefaultlanguage{russian}
\setmainfont{DejaVuSerif.ttf}[Path=fonts/,BoldFont=DejaVuSerif-Bold.ttf,ItalicFont=DejaVuSerif-Italic.ttf,BoldItalicFont=DejaVuSerif-BoldItalic.ttf]
\setsansfont{DejaVuSans.ttf}[Path=fonts/,BoldFont=DejaVuSans-Bold.ttf]
\setmonofont{DejaVuSansMono.ttf}[Path=fonts/]
\newfontfamily\cyrillicfont{DejaVuSerif.ttf}[Path=fonts/,BoldFont=DejaVuSerif-Bold.ttf,ItalicFont=DejaVuSerif-Italic.ttf]
\newfontfamily\cyrillicfontsf{DejaVuSans.ttf}[Path=fonts/,BoldFont=DejaVuSans-Bold.ttf]
\geometry{left=21mm,right=21mm,top=22mm,bottom=22mm,headheight=14pt}
\definecolor{ink}{HTML}{172033}\definecolor{accent}{HTML}{0072B2}
\color{ink}\hypersetup{colorlinks=true,linkcolor=accent,urlcolor=accent,pdftitle={Сеть дронопортов: три варианта, формулы и автономные карты},pdfauthor={Учебное исследование, вариант И}}
\pagestyle{fancy}\fancyhf{}\fancyhead[L]{\sffamily\scriptsize Сеть дронопортов: инвестиции, расписание и регионы}\fancyfoot[L]{\sffamily\scriptsize Вариант И · 06.11.2026}\fancyfoot[R]{\sffamily\scriptsize\thepage}
\renewcommand{\headrulewidth}{0.3pt}\setlength{\parindent}{0pt}\setlength{\parskip}{5pt}\linespread{1.08}
\setlength{\emergencystretch}{3em}\tolerance=1800
\captionsetup{font=small,labelfont=bf,justification=raggedright,singlelinecheck=false}
\renewcommand{\figurename}{Рисунок}\renewcommand{\tablename}{Таблица}
\setlist[itemize]{leftmargin=1.3em,itemsep=2pt,topsep=3pt,parsep=0pt}
\begin{document}
'''


def build(out):
    source=ROOT/'reports/article';article=json.loads((source/'article.json').read_text());figures=json.loads((source/'figure_manifest.json').read_text());blocks=enhanced_blocks(article)
    audit_path=ROOT/'reports/research_audit/article_addendum.json'
    audit=json.loads(audit_path.read_text())
    insert_at=next(i for i,b in enumerate(blocks) if b.get('text','').startswith('11. Обсуждение'))
    for b in blocks:
        if b.get('text','').startswith('11. Обсуждение'):b['text']=b['text'].replace('11.','15.',1)
        if b.get('text','').startswith('12. Выводы'):b['text']=b['text'].replace('12.','16.',1)
    blocks[insert_at:insert_at]=audit['blocks']
    screenshots=json.loads((out/'screenshots_manifest.json').read_text()) if (out/'screenshots_manifest.json').exists() else []
    tex=[PREAMBLE,r'{\sffamily\bfseries\LARGE '+escape(article['title'])+r'\par}',r'\vspace{6pt}',escape(article['subtitle'])+r'\par',r'\section*{Аннотация}',escape(article['abstract']),r'\textbf{Ключевые слова:} '+escape(article['keywords'])]
    page=['<h1>'+html.escape(article['title'])+'</h1>','<p class="subtitle">LaTeX-редакция · вариант И · 06.11.2026</p>','<h2>Аннотация</h2><p>'+html.escape(article['abstract'])+'</p>']
    md=['# '+article['title'],'LaTeX-редакция · 06.11.2026','## Аннотация',article['abstract']]
    used=[]
    def para(t):
        assert '\u2014' not in t
        tex.append(escape(t));page.append('<p>'+html.escape(t)+'</p>');md.append(t)
    for b in blocks:
        kind=b['kind']
        if kind=='h':
            tex.append(r'\section*{'+escape(b['text'])+'}');page.append('<h2>'+html.escape(b['text'])+'</h2>');md.append('## '+b['text'])
        elif kind=='p':para(b['text'])
        elif kind=='math':
            key=b['key'];expression,definitions=FORMULAS[key];used.append(key)
            if key=='1b':expression=expression.replace(r',\qquad \tau_{ij}',r',\\ \tau_{ij}').replace(r',\qquad \tau_c',r',\\ \tau_c');expression=r'\begin{gathered}'+expression+r'\end{gathered}'
            tex.extend([r'\noindent\begin{minipage}{\linewidth}\stepcounter{equation}',r'\begin{equation}\label{eq:'+key+'}'+expression+r'\tag{'+key+r'}\end{equation}',r'\textbf{Где:}',r'\begin{itemize}'])
            page.append('<div class="equation" id="eq-'+key+'">'+convert(expression,display='block')+'<span>('+key+')</span></div><p><strong>Где:</strong></p><ul class="definitions">')
            md.extend(['$$\n'+expression+'\n$$','**Где:**'])
            for symbol,meaning in definitions:
                tex.append(r'\item $'+symbol+'$: '+escape(meaning))
                page.append('<li>'+convert(symbol)+'<span>: '+html.escape(meaning)+'</span></li>')
                md.append('- $'+symbol+'$: '+meaning)
            tex.append(r'\end{itemize}\end{minipage}\par');page.append('</ul>')
        elif kind in ('figure','audit_figure'):
            n=b['number'];extra=kind=='audit_figure';f=audit['figures'][n-19] if extra else figures[n-1]
            prefix='' if extra else '../article/';plotpath=prefix+f['pdf'];guide=f['axes'] if extra else AXES[n]
            tex.extend([r'\begin{figure}[H]\centering',r'\includegraphics[width=\linewidth,height=.34\textheight,keepaspectratio]{'+plotpath+'}',r'\caption{'+escape(f['title'])+r'}\label{fig:'+str(n)+'}',r'{\footnotesize Данные: '+escape(f['source'])+r'\par}',r'\end{figure}',r'\textbf{Как читать рисунок '+str(n)+r'.} '+escape(guide)])
            page.append('<figure><img loading="lazy" src="'+prefix+f['svg']+'" alt="'+html.escape(f['title'])+'"><figcaption>Рисунок '+str(n)+'. '+html.escape(f['title'])+'</figcaption><small>Данные: '+html.escape(f['source'])+'</small></figure><p class="reading"><strong>Как читать рисунок '+str(n)+'.</strong> '+html.escape(guide)+'</p>')
            md.extend([f'![Рисунок {n}. {f["title"]}]({prefix}{f["png"]})','**Как читать рисунок '+str(n)+'.** '+guide])
        elif kind=='table':
            headers=b['headers'];rows=b['rows'];n=len(headers);widths=b.get('widths') or [1]*n
            if b['title'].startswith('Таблица 1.'):widths=[55,230,210]
            total=sum(widths);fractions=[w/total for w in widths]
            # Reserve tabular column padding within the text width.
            colspec=''.join(r'>{\raggedright\arraybackslash}p{\dimexpr'+f'{f:.5f}'+r'\linewidth-2\tabcolsep\relax}' for f in fractions)
            tex.extend([r'{\small\textbf{'+escape(b['title'])+r'}\par}',r'{\scriptsize\setlength{\tabcolsep}{4pt}\renewcommand{\arraystretch}{1.2}',r'\begin{longtable}{'+colspec+'}',r'\toprule',' & '.join(r'\textbf{'+escape(h)+'}' for h in headers)+r'\\\midrule\endhead'])
            tex.extend(' & '.join(escape(v) for v in row)+r'\\' for row in rows);tex.extend([r'\bottomrule\end{longtable}}'])
            page.append('<div class="table-scroll"><table><caption>'+html.escape(b['title'])+'</caption><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>')
            md.extend([b['title'],'| '+' | '.join(headers)+' |','| '+' | '.join(['---']*n)+' |']+['| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in rows])
        elif kind=='reference':
            line='['+b['number']+'] '+b['text'];tex.append(r'{\small '+escape(line)+(r' \href{'+b['url']+r'}{Источник}' if b['url'] else '')+r'\par}')
            page.append('<p class="reference">'+html.escape(line)+(f' <a href="{html.escape(b["url"],quote=True)}">Источник</a>' if b['url'] else '')+'</p>');md.append(line+(' '+b['url'] if b['url'] else ''))
    assert set(used)==set(FORMULAS) and len(used)==len(FORMULAS)
    title='Приложение C. Подробные сети на локальной подложке OSM'
    tex.extend([r'\clearpage',r'\section*{'+title+'}']);page.append('<h2>'+title+'</h2>');md.append('## '+title)
    cartography=json.loads((ROOT/'data/cartography/provenance.json').read_text())
    para(f'Подложка построена из локальной выгрузки OpenStreetMap от 03.11.2026. В неё включены основные и жилые дороги, железнодорожные линии, реки, замкнутые водные объекты и названия поселений. Это выборочная светлая картография, а не полный стандартный стиль OSM Carto: здания и составные водные отношения не отрисованы. Сохранены {cartography["features"]} геометрий и {cartography["places"]} подписываемых поселений. Карта не обращается к общественным серверам тайлов; атрибуция OpenStreetMap и лицензия ODbL указаны на каждом снимке.')
    para('Сначала локальный сервер на 127.0.0.1 отрисовывает необходимые тайлы, затем последовательно снимаются фиксированные виды. После остановки сервера те же HTML открываются как локальные файлы в браузерах с отключённой сетью. Снимки Chromium сравниваются попиксельно с вариантом через локальный сервер; Firefox проверяет те же виды независимо. В автономном режиме гарантированы сохранённые области и масштабы, а не произвольная детализация всей страны. Оптимизаторы при этой сборке не запускаются.')
    para('На снимках нет привычных координатных осей: север направлен вверх, восток вправо; линейка внизу слева задаёт расстояние на местности. Используется Web Mercator, поэтому визуальные длины нельзя сравнивать между масштабами без линейки. Точки показывают введённые порты, цветные прямые линии фактические рейсы типичных суток. Для отдельной версии толщина связана с числом рейсов в обоих направлениях, но не с числом уникальных пассажиров. Прямые отрезки не являются автомобильными дорогами или разрешёнными воздушными трассами.')
    tex.append(r'\begin{landscape}')
    for idx,s in enumerate(screenshots,19+len(audit['figures'])):
        caption=s['title']+'. Снимок автономной карты после остановки сервера.'
        if s['variant']=='ABC':explanation='Сравниваются сети третьего года на одинаковой территории. Синий, зелёный и охристый цвета обозначают A, B и C. Толщина и штрих различают версии; совпадающие линии частично перекрыты. Дополнительный маршрут к Зубцову и Кардымову относится к C. Наложение показывает географию связей, а не разницу качества расписаний при одних активах.'
        elif s['view']=='overview':explanation='Обзор охватывает территорию трёх областей. Масштаб одинаков для всех обзорных снимков, поэтому видна концентрация строительства и появление межрегиональных связей. Детальные дороги и близкие порты следует рассматривать на следующем увеличенном виде. Число поездок в заголовке относится к данному году, а не к накопленному итогу.'
        elif s['view'] in ('moscow','smolensk','tver'):explanation='Увеличенный фрагмент регионального варианта C в третьем году. Границы кадра обрезают часть длинных связей; их конечные порты следует сверять с общим видом сети. Подложка даёт географический контекст, но маршруты аппаратов не привязаны к дорожному графу. Линейка масштаба относится только к этому снимку.'
        else:explanation='Камера приближена к действующим портам выбранной версии и года. Названия отмечают места введённых объектов, линии объединяют выполненные рейсы между одной парой портов. Масштаб подбирается под охват сети и может отличаться от соседнего года; сравнивать длины следует по линейке. Спрос и расписание остаются теми же, что в сохранённом расчёте.'
        tex.extend([r'\clearpage',r'\begin{figure}[H]\centering',r'\includegraphics[width=\linewidth,height=.77\textheight,keepaspectratio]{'+s['file']+'}',r'\caption{'+escape(caption)+'}',r'\end{figure}',r'{\small '+escape(explanation)+r'\par}'])
        page.append('<figure class="map"><img loading="lazy" src="'+s['file']+'" alt="'+html.escape(caption)+'"><figcaption>Рисунок '+str(idx)+'. '+html.escape(caption)+'</figcaption></figure><p>'+html.escape(explanation)+'</p>')
        md.extend([f'![Рисунок {idx}. {caption}]({s["file"]})',explanation])
    tex.extend([r'\end{landscape}',r'\end{document}'])
    source_tex='\n\n'.join(tex);assert '\u2014' not in source_tex
    (out/'report.tex').write_text(source_tex)
    css='body{background:white;color:#172033;margin:0;font:17px/1.65 Georgia,serif}main{max-width:1100px;margin:auto;padding:45px 30px}h1,h2,caption,figcaption,.subtitle{font-family:system-ui,sans-serif}h1{font-size:35px;line-height:1.2}h2{margin-top:32px;font-size:23px}p{text-align:justify}figure{margin:28px 0}figure img{width:100%;height:auto}figcaption,small{font-size:13px;line-height:1.45}table{width:100%;border-collapse:collapse;font:13px/1.5 system-ui}td,th{border-bottom:1px solid #dce2e8;padding:8px;vertical-align:top;text-align:left}caption{text-align:left;font-weight:bold;padding:10px 0}th{background:#f0f4f7}.table-scroll,.equation{overflow-x:auto}.equation{display:flex;align-items:center;justify-content:center;gap:18px;padding:18px 4px;border-bottom:1px solid #e1e7ec}.equation math{font-size:1.15em}.definitions li{padding:3px 0}.definitions math{display:inline-block}.reading{border-left:3px solid #0072b2;padding-left:14px;font-size:16px}a{color:#0072b2}.reference{font-size:14px}@media(max-width:650px){main{padding:22px 14px}h1{font-size:28px}}'
    (out/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(article['title'])+'</title><style>'+css+'</style><main><nav><a href="report.pdf">PDF из LaTeX</a> · <a href="report.tex">Исходник TeX</a> · <a href="maps/index.html">Автономная карта</a></nav>'+''.join(page)+'</main></html>')
    (out/'article.md').write_text('\n\n'.join(md))
    manifest=dict(formulas=len(used),formula_keys=used,definitions=sum(len(FORMULAS[k][1]) for k in used),graph_reading_guides=len(AXES)+len(audit['figures']),screenshots=len(screenshots),figures=len(figures)+len(audit['figures'])+len(screenshots),research_audit=True,source_article_sha256=checksum(source/'article.json'),tex_sha256=checksum(out/'report.tex'),html_sha256=checksum(out/'report.html'),source_files={str(p.relative_to(ROOT)):checksum(p) for p in [ROOT/'src/droneport/latex_content.py',ROOT/'src/droneport/latex_article.py',audit_path]})
    (out/'content_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(json.dumps(manifest,ensure_ascii=False),flush=True)
    return manifest
