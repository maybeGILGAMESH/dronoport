"""Publish the validated LaTeX edition while retaining earlier reports."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'reports/latex'
check=json.loads((out/'validation.json').read_text());pipeline=json.loads((out/'pipeline_validation.json').read_text())
assert check['valid'] and len(check['browsers'])==2 and pipeline['valid'] and pipeline['network_namespace']
assert hashlib.sha256((out/'report.pdf').read_bytes()).hexdigest()==check['pdf_sha256']==pipeline['pdf_sha256']
history=ROOT/'reports/historical';history.mkdir(exist_ok=True)
for name in ('report.pdf','report.html','report.md'):
 p=ROOT/'reports'/name;old=history/('before_research_'+name)
 if p.exists() and not old.exists():shutil.copy2(p,old)
shutil.copy2(out/'report.pdf',ROOT/'reports/report.pdf')
(ROOT/'reports/report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=latex/report.html"><title>LaTeX-редакция отчёта</title><a href="latex/report.html">Открыть отчёт с формулами и подробными картами</a></html>')
(ROOT/'reports/report.md').write_text((out/'article.md').read_text().replace('../article/','article/').replace('../research_audit/','research_audit/').replace('](screenshots/','](latex/screenshots/'))
oldhtml=ROOT/'reports/article/report.html';s=oldhtml.read_text()
if 'latex-edition-link' not in s:
 s=s.replace('<main>','<main><p id="latex-edition-link" style="padding:14px;background:#eef5fa;border-left:3px solid #0072b2"><strong>Доступна новая LaTeX-редакция:</strong> <a href="../latex/report.html">формулы с обозначениями, пояснения осей и 25 подробных карт</a>.</p>',1);oldhtml.write_text(s)
p=ROOT/'README.md';s=p.read_text()
lines=s.splitlines()
if lines and lines[0].startswith('> LaTeX-редакция'):s='\n'.join(lines[2:])
s='> LaTeX-редакция после аудита: [PDF](reports/report.pdf), [HTML](reports/latex/report.html), [аудит расчётов](RESEARCH_AUDIT_README.md). '+str(check['pages'])+' страниц, '+str(check['figures'])+' рисунок. Все семь запусков сохранены.\n\n'+s
s=s.replace('Новый сравнительный отчёт: [reports/report.pdf](reports/report.pdf), 24 страницы и 18 рисунков.','Расширенный сравнительный отчёт: [reports/report.pdf](reports/report.pdf).')
p.write_text(s)
p=ROOT/'COMBINED_README.md';s=p.read_text()
import re
s=re.sub(r'LaTeX-статья на \d+ страницах с \d+ рисунками \([^)]*\)', 'LaTeX-статья на '+str(check['pages'])+' страницах с '+str(check['figures'])+' рисунком (26 аналитических рисунков и 25 карт)',s)
s=s.replace('droneport_three_variants_latex_20261106.zip','droneport_three_variants_research_20261106.zip')
if 'RESEARCH_AUDIT_README' not in s:s+='\nАудит всех семи запусков и дополнительные выводы: `RESEARCH_AUDIT_README.md`. Исходные каталоги всех запусков включены в новый комплект.\n'
p.write_text(s)
print('Published LaTeX report:',check['pages'],'pages')
