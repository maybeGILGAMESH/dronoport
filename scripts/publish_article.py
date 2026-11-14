"""Publish a checked comparative article, preserving earlier local reports."""
from pathlib import Path
import json, shutil
root = Path(__file__).resolve().parents[1]
article = root / 'reports/article'
check = json.loads((article / 'article_validation.json').read_text())
assert check['valid'] and len(check['browsers']) == 2
history = root / 'reports/historical'
history.mkdir(exist_ok=True)
for name in ['report.pdf', 'report.md', 'report.html', 'executive_summary.md']:
    p = root / 'reports' / name
    target = history / ('before_article_' + name)
    if p.exists() and not target.exists():
        shutil.copy2(p, target)
shutil.copy2(article / 'report.pdf', root / 'reports/report.pdf')
(root / 'reports/report.md').write_text((article / 'article.md').read_text().replace('](figures/', '](article/figures/'))
(root / 'reports/report.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=article/report.html"><title>Сеть дронопортов: сравнительная статья</title><a href="article/report.html">Открыть сравнительную статью</a></html>')
a = json.loads((article / 'article.json').read_text())
keep = False
parts = ['# Управленческая записка: три варианта сети']
for b in a['blocks']:
    if b['kind'] == 'h':
        if b['text'].startswith('12.'):
            keep = True
            continue
        if keep:
            break
    if keep:
        if b['kind'] == 'p':
            parts.append(b['text'])
        elif b['kind'] == 'table':
            parts += ['| ' + ' | '.join(b['headers']) + ' |', '| ' + ' | '.join(['---'] * len(b['headers'])) + ' |']
            parts += ['| ' + ' | '.join(map(str, row)) + ' |' for row in b['rows']]
parts += ['Региональный план предназначен для нормального режима. При отказах активы и постоянные расходы сохраняются; расписание и пассажирские потоки перепланируются. Синтетический спрос не является прогнозом фактической загрузки. Полнота сопоставления реестра и глобальная оптимальность остаются открытыми.', 'Полное сравнение и проверки: [статья](article/report.html), [PDF](report.pdf), [автономная карта](article/maps/network_regional.html).']
(root / 'reports/executive_summary.md').write_text('\n\n'.join(parts))
readme = root / 'README.md'
text = readme.read_text()
if not text.startswith('> Актуальный'):
    text = '> Актуальный объединённый комплект: [COMBINED_README.md](COMBINED_README.md). Новый сравнительный отчёт: [reports/report.pdf](reports/report.pdf), 24 страницы и 18 рисунков. Три исходных комплекта сохранены отдельно. Разделы ниже описывают историю и команды численных экспериментов.\n\n' + text
text = text.replace('В новом отчёте сначала приведено дополнение, затем сохранённое базовое исследование.', 'В историческом отчёте версии CP-SAT сначала приведено дополнение, затем сохранённое базовое исследование. Текущий reports/report.pdf объединяет результаты в связную сравнительную статью.')
readme.write_text(text)
print('Published comparative article, preserved earlier local reports.')
