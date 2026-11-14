"""Flowing journal-style PDF and editable article with identical content."""
from pathlib import Path
import html,json,re
from PIL import Image as PILImage
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Image,Spacer,KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader
from .article_text import manuscript
from .pipeline_v2 import save
from .ingest import ROOT,checksum

def render(folder,out):
    article=manuscript(folder,out);figures=json.loads((out/'figure_manifest.json').read_text());save(out/'article.json',article)
    fonts=Path('/usr/share/fonts/truetype/dejavu')
    for name,file in [('Article','DejaVuSerif.ttf'),('ArticleBold','DejaVuSerif-Bold.ttf'),('ArticleItalic','DejaVuSerif-Italic.ttf'),('Atlas','DejaVuSans.ttf'),('AtlasBold','DejaVuSans-Bold.ttf')]:pdfmetrics.registerFont(TTFont(name,str(fonts/file)))
    pdfmetrics.registerFontFamily('Article',normal='Article',bold='ArticleBold',italic='ArticleItalic',boldItalic='ArticleBold')
    body=ParagraphStyle('article',fontName='Article',fontSize=9.4,leading=14,spaceAfter=7,allowWidows=0,allowOrphans=0)
    head=ParagraphStyle('heading',fontName='AtlasBold',fontSize=12,leading=16,spaceBefore=14,spaceAfter=7,keepWithNext=True)
    title=ParagraphStyle('title',fontName='AtlasBold',fontSize=20,leading=25,spaceAfter=13)
    small=ParagraphStyle('caption',fontName='Atlas',fontSize=7.6,leading=10.5,spaceAfter=8)
    cell=ParagraphStyle('cell',fontName='Atlas',fontSize=7.1,leading=9.6,wordWrap='CJK')
    equation=ParagraphStyle('equation',fontName='Atlas',fontSize=9.2,leading=15,spaceBefore=4,spaceAfter=9)
    abstract=ParagraphStyle('abstract',parent=body,fontName='ArticleItalic',fontSize=9.4,leading=14,leftIndent=9,rightIndent=9,spaceAfter=12)
    esc=lambda t:html.escape(str(t)).replace('—',';')
    story=[Paragraph(esc(article['title']),title),Paragraph(esc(article['subtitle']),small),Paragraph('Аннотация',head),Paragraph(esc(article['abstract']),abstract),Paragraph('Ключевые слова: '+esc(article['keywords']),small)]
    markdown=['# '+article['title'],article['subtitle'],'## Аннотация',article['abstract'],'Ключевые слова: '+article['keywords']]
    webpage=['<h1>'+esc(article['title'])+'</h1>','<p class="subtitle">'+esc(article['subtitle'])+'</p>','<section class="abstract"><h2>Аннотация</h2><p>'+esc(article['abstract'])+'</p></section>']
    used=[]
    for block in article['blocks']:
        kind=block['kind']
        if kind in ('p','h','equation'):
            text=block['text'];style=head if kind=='h' else equation if kind=='equation' else body
            story.append(Paragraph(esc(text),style));markdown.append(('## ' if kind=='h' else '')+text)
            tag='h2' if kind=='h' else 'p';webpage.append(f'<{tag} class="{kind}">'+esc(text)+f'</{tag}>')
        elif kind=='figure':
            n=block['number'];f=figures[n-1];used.append(n);path=out/f['png'];w,h=PILImage.open(path).size
            width=495;height=width*h/w
            caption=f'Рисунок {n}. '+f['title']
            source='Данные: '+f['source']
            story.append(KeepTogether([Spacer(1,6),Image(str(path),width=width,height=height),Paragraph(esc(caption),small),Paragraph(esc(source),ParagraphStyle('src',parent=small,fontSize=6.5,leading=9,textColor=colors.HexColor('#5b6472')))]))
            markdown.extend([f'![{caption}]({f["png"]})',source])
            webpage.append('<figure><img loading="lazy" src="'+f['svg']+'" alt="'+esc(caption)+'"><figcaption>'+esc(caption)+'</figcaption><small>'+esc(source)+'</small><p class="downloads"><a href="'+f['pdf']+'">PDF</a> · <a href="'+f['png']+'">PNG 300 dpi</a></p></figure>')
        elif kind=='table':
            story.append(Paragraph(esc(block['title']),ParagraphStyle('tablehead',parent=small,fontName='AtlasBold',keepWithNext=True,spaceBefore=8)))
            rows=[block['headers']]+block['rows'];rendered=[[Paragraph(esc(v),cell) for v in row] for row in rows]
            widths=block.get('widths') or [495/len(rows[0])]*len(rows[0]);widths=[w*495/sum(widths) for w in widths]
            t=Table(rendered,colWidths=widths,repeatRows=1,hAlign='LEFT');t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef3f6')),('LINEABOVE',(0,0),(-1,0),.8,colors.HexColor('#172033')),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#aab2bf')),('LINEBELOW',(0,-1),(-1,-1),.6,colors.HexColor('#172033')),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]));story.extend([t,Spacer(1,8)])
            markdown.extend([block['title'],'| '+' | '.join(map(str,block['headers']))+' |','| '+' | '.join(['---']*len(block['headers']))+' |']+['| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in block['rows']])
            webpage.append('<div class="table-scroll"><table><caption>'+esc(block['title'])+'</caption><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in block['headers'])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in block['rows'])+'</tbody></table></div>')
        elif kind=='reference':
            txt=f'[{block["number"]}] '+block['text'];linked=esc(txt)+(f' <a href="{html.escape(block["url"],quote=True)}" color="#0072b2">Источник</a>' if block['url'] else '')
            story.append(Paragraph(linked,small));markdown.append(txt+(' [Источник]('+block['url']+')' if block['url'] else ''));webpage.append('<p class="reference">'+linked+'</p>')
    assert sorted(used)==list(range(1,len(figures)+1)),used
    def page(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#cbd3db'));canvas.setLineWidth(.4);canvas.line(50,807,545,807)
        canvas.setFont('Atlas',7);canvas.setFillColor(colors.HexColor('#5b6472'));canvas.drawString(50,815,'Сеть дронопортов · временная модель и региональное обслуживание')
        canvas.drawString(50,25,'Вариант И · вычислительное исследование · 06.11.2026');canvas.drawRightString(545,25,str(doc.page))
    doc=SimpleDocTemplate(str(out/'report.pdf'),pagesize=(595,842),leftMargin=50,rightMargin=50,topMargin=47,bottomMargin=43,title=article['title'],author='Учебное исследование, вариант И',subject='Сравнение трёх проверенных вариантов; белый Cinematic Atlas')
    doc.build(story,onFirstPage=page,onLaterPages=page)
    md='\n\n'.join(markdown);assert '—' not in md
    (out/'article.md').write_text(md,encoding='utf-8')
    css='body{margin:0;background:#fff;color:#172033;font:17px/1.65 Georgia,serif}main{max-width:1000px;margin:auto;padding:48px 30px}h1,h2,th,figcaption,.subtitle{font-family:system-ui,sans-serif}h1{font-size:38px;line-height:1.15;max-width:900px}h2{font-size:23px;margin-top:36px}p{margin:12px 0;text-align:justify}.abstract{border-top:2px solid #0072b2;border-bottom:1px solid #cbd3db;padding:8px 18px}.subtitle,small{color:#5b6472}figure{margin:32px 0}figure img{width:100%;height:auto;background:#fff}figcaption{font-size:14px;line-height:1.5}small{font-size:12px}table{width:100%;border-collapse:collapse;font:13px/1.45 system-ui}caption{text-align:left;font-weight:700;padding:14px 0}th{background:#eef3f6;text-align:left}td,th{padding:9px;border-bottom:1px solid #d9dee8;vertical-align:top}.table-scroll{overflow-x:auto}.equation{font-family:system-ui;font-size:15px;background:#fafbfd;padding:12px}a{color:#006da7}.downloads{font:13px system-ui}.reference{font-size:14px}@media(max-width:650px){main{padding:25px 16px}h1{font-size:28px}}'
    (out/'report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(article['title'])+'</title><style>'+css+'</style><main><nav><a href="report.pdf">Скачать PDF</a> · <a href="article.md">Текст статьи</a> · <a href="evidence/variants.csv">Сравнительная таблица</a> · <a href="maps/network_regional.html">Автономная карта</a></nav>'+''.join(webpage)+'</main></html>')
    pages=len(PdfReader(out/'report.pdf').pages)
    save(out/'editorial_audit.json',dict(skill='humanizer 3.0.0',source='https://github.com/ashgreat/humanizer',em_dashes=md.count('—'),changes=['Удалены повторяющиеся вступления и итоговые дополнения','Методы и результаты объединены в связную статью','Числа, ограничения и область границ сохранены','Статусы незакрытых требований оставлены в приложении'],automated_ai_detection='English detector is not validated for Russian; no authorship or detector-score claim',word_count=len(md.split()),figures=len(figures),pages=pages))
    save(out/'article_manifest.json',dict(run_id=folder.name,pages=pages,figures=len(figures),report_sha256=checksum(out/'report.pdf'),text_sha256=checksum(out/'article.md'),source_files={str(p.relative_to(ROOT)):checksum(p) for p in (ROOT/'src/droneport').glob('article_*.py')}))
    print('Article ready:',pages,'pages,',len(figures),'figures',flush=True)
