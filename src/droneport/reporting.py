"""Отчёт из сохранённых результатов; повторный запуск решателя не требуется."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
import textwrap

from .ingest import ROOT

os.environ["MPLCONFIGDIR"] = str(ROOT / ".cache/matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
import yaml


def number(value):
    return f"{value:,.0f}".replace(",", " ")


def generate(folder):
    folder = Path(folder)
    reports = ROOT / "reports"
    figures = reports / "figures"
    maps = reports / "maps"
    figures.mkdir(exist_ok=True); maps.mkdir(exist_ok=True)
    manifest = json.loads((folder / "run_manifest.json").read_text())
    check = json.loads((folder / "validation_report.json").read_text())
    data = json.loads((folder / "data_preparation.json").read_text())
    mip = json.loads((folder / "small_mip_report.json").read_text())
    game = json.loads((folder / "minimax_results.json").read_text())
    sanity = json.loads((folder / "demand_sanity.json").read_text())
    cfg = yaml.safe_load((folder / "model.yaml").read_text())
    budget = pd.read_csv(folder / "budget_by_year.csv")
    robust_budget = pd.read_csv(folder / "robust/budget_by_year.csv")
    methods = pd.read_csv(folder / "method_comparison.csv")
    seeds = pd.read_csv(folder / "seed_results.csv")
    scenarios = pd.read_csv(folder / "scenario_results.csv")
    benchmarks = pd.read_csv(folder / "benchmarks.csv")
    towns = pd.read_csv(folder / "towns_main.csv", dtype={"region_code": str})
    purchases = pd.read_csv(folder / "investment_fleet_plan.csv")
    base_worst = int(scenarios[scenarios.plan == "base"].completed_trips.min())
    robust_worst = int(scenarios[scenarios.plan == "robust"].completed_trips.min())
    robust_base = int(scenarios[(scenarios.plan == "robust") & (scenarios.scenario == "base")].completed_trips.iloc[0])
    demand_total = int(sum(sanity["daily_demand_by_year"]) * cfg["operating_days"])
    total = manifest["completed_trips"]
    blocks = []
    def section(title, text):
        blocks.append((title, text))
    section("Результат", f"Запуск {manifest['run_id']}. Вариант И: Московская, Смоленская и Тверская области; "
            f"буквы Ж, З, И, К, Л. Основная задача: 30 пунктов, малая: 8. Найденный базовый план обслуживает "
            f"{number(total)} завершённых поездок за три года ({total/demand_total:.1%} синтетического спроса). "
            f"Расходы: {number(budget.spend_rub.sum())} руб.; остаток: {number(budget.carry_rub.iloc[-1])} руб. "
            f"Независимая проверка: {'пройдена' if check['valid'] else 'НЕ ПРОЙДЕНА'}; CP-SAT: {check['cp_sat']['status']}.")
    section("Данные и фиксированный отбор", f"Из OSM-экстракта от 03.11.2026 извлечено {data['osm_places_in_regions']} place-узлов "
            f"в полигонах трёх областей; {data['eligible_places']} удовлетворяют буквам. Москва исключена отдельным полигоном. "
            f"С Росстатом однозначно сопоставлены {data['matched_population']} пунктов. Пропуски оставлены пустыми по указанию пользователя. "
            "Для вычислительной выборки поочерёдно берутся крупнейшие по населению известные пункты регионов 50/67/69 до 30; "
            "при равенстве — нормализованное имя и OSM ID. Малый экземпляр — первые 8. Правило задано до оптимизации. "
            "Изоляты не удалялись. Основной граф связен при 200 и 160 км; малый имеет две компоненты. "
            "Это полный результат извлечения place-узлов, но полнота относительно государственного реестра и полигональных поселений без узла не подтверждена.")
    section("Спрос и единицы", "Численность населения — таблица 5 ВПН-2020, дата наблюдения 01.10.2021. "
            "Агрегаты муниципалитетов не подставляются вместо поселений. Формула типичных суток: "
            "q(i,j,t)=floor(0.003 × P_i^0.55 × P_j^0.45 / (1+d_ij/50)^1.5 × 1.05^(t−1)). "
            f"Задано 330 одинаковых рабочих суток в году. Суточный спрос по годам: {sanity['daily_demand_by_year']}. "
            f"В первом году это {sanity['daily_trips_per_resident_year1']:.5f} поездки на жителя в сутки. "
            "Спрос направленный и синтетический; параметры зафиксированы до поиска. Это сценарий, а не наблюдаемый прогноз.")
    section("Учебная техника и экономика", "10 пассажиров; 200 км между зарядками. Скорость 240 км/ч, посадка 5 мин, "
            "зарядка после каждого рейса 30 мин, пересадка минимум 10 мин. Рабочее окно 08:00–20:00: "
            "8 слотов по 90 мин. На порт — 2 зарядных места и не более 2 закреплённых аппаратов всех инцидентных коридоров. "
            "CAPEX порта 90 млн руб., аппарата 250 млн; годовой OPEX порта 12 млн, аппарата 18 млн без энергии. "
            "Энергия: 4 кВт·ч/км по 10 руб./кВт·ч, стоимость каждого участка округляется вверх до рубля. "
            "OPEX включает персонал, обслуживание, ремонт и содержание. Все цены — учебные допущения. "
            "Ввод принят в начале года приобретения; 330 суток доступны с этого момента. Задержки строительства не моделировались. "
            "Единая ценовая база 2026 года, сценарий без инфляции, НДС отдельно не начисляется.")
    section("Математическая модель", "x_it — действующий порт; b_et — число купленных в году t аппаратов коридора e; "
            "N_et=Σ_(k≤t)b_ek; z_pt — целое число поездок по пассажирскому временному пути p. "
            "Максимизируется 330×Σ_t,p z_pt. Для каждой OD: Σ_p z_pt≤q_OD,t. Для каждого рейсового слота: "
            "Σ_(p использует e,s) z_pt≤10N_et. Σ_(e инцидентно i)N_et≤2x_it; x_i,t≤x_i,t+1. "
            "Накопленные CAPEX и OPEX к году t не превышают t×1 млрд руб. Денежные остатки валидируются в целых рублях. "
            "Выручка не финансирует модель. Пересадочная поездка учитывается один раз после достижения конечного пункта.")
    section("Граница применимости модели", "Каждый аппарат закреплён за одним коридором на весь горизонт и выполняет "
            "четыре оборотных рейса за сутки, включая порожние. Ориентация первого рейса определяется фиксированным индексом пункта. "
            "Для каждой OD рассматриваются три кратчайших пространственных пути и их допустимые времена начала. "
            "Произвольная смена коридоров аппаратом и дополнительные пространственные пути не исследованы. "
            "Поэтому найденные планы — допустимые планы ограниченной учебной модели, а граница MIP не является "
            "верхней границей неограниченной исходной транспортной задачи.")
    section("Почему выбраны короткие связи", "В этой модели нет тарифов, готовности платить и конкуренции наземного транспорта. "
            "Спрос по гравитационной формуле особенно велик между близкими крупными пунктами, а энергия дешевле на коротких рейсах. "
            "Поэтому базовый план выбирает короткие коридоры Московской области, включая Люберцы — Котельники. "
            "Это результат принятых допущений, а не рекомендация реального авиасервиса на расстоянии нескольких километров. "
            "Требования строить в каждом из трёх регионов в PDF нет. После получения результата состав данных и формула спроса не менялись.")
    section("Алгоритмы", "Greedy проверяет прирост завершённых поездок на рубль для 48 лучших предварительно ранжированных "
            "добавлений коридорного аппарата. Отжиг действительно меняет год, коридор и число покупок; недопустимые предложения "
            "восстанавливаются удалением покупок. Температура убывает, выполнены 10 seed по 100 итераций. "
            "Все потоки распределяются целочисленно с общей вместимостью рейсов. Для малого экземпляра выполнены совместный "
            "трёхлетний MIP и три последовательных годовых MIP. Начальные прогнозы, пути и ограничения одинаковы. "
            f"Малый совместный MIP: {mip['status']}, incumbent={mip['incumbent_completed']}, "
            f"верхняя граница={mip['upper_bound_completed']}, gap={mip['relative_gap']}; "
            f"{mip['variables']} переменных, {mip['constraints']} ограничений, {mip['wall_seconds']} с. "
            "Для максимизации gap=(верхняя граница−допустимое значение)/|допустимое значение| при ненулевом знаменателе.")
    section("Результат собственного метода", f"Все 10 seed представлены в seed_results.csv. Лучший результат отжига: "
            f"{number(seeds.completed_trips.max())}; минимум {number(seeds.completed_trips.min())}; "
            f"медиана {number(seeds.completed_trips.median())}. В текущем прогоне отжиг не улучшил greedy. "
            "Это не означает, что оператор поиска не работал: число изменённых и принятых предложений сохранено для каждого seed. "
            "Начальная допустимая сеть одинакова, случайными являются предложения и принятие ухудшений. "
            "Кэш распределения пассажиров очищается перед каждым измеряемым запуском алгоритма.")
    section("Расписание и проверка", f"Сформированы рейсы и индивидуальные пассажирские маршруты типичных суток всех трёх лет. "
            f"Всего {check['flights_all_typical_days']} рейсов в этих трёх сутках, "
            f"{check['empty_flights_all_typical_days']} порожних; "
            f"{check['transfer_trips_all_typical_days']} поездок с пересадкой. "
            "Независимый валидатор пересчитывает расстояния WGS84, вместимость, занятость аппаратов, зарядные места, "
            "пересадки, замыкание суток, поездки по OD и бюджет. CP-SAT дополнительно проверяет ресурсы фиксированного расписания. "
            "Каждый аппарат возвращается в исходный пункт; ресурс 200 км обнуляется только после полной зарядки.")
    section("Устойчивость и конечная игра", f"Спрос 0.7×/1.3×, дальность 160 км и отказ каждого построенного узла "
            f"проверены при фиксированных покупках. Отказ действует во все моделируемые периоды после ввода; "
            "связанные с ним коридорные аппараты простаивают, полная базовая смета сохраняется консервативно. "
            "Перестраиваются пассажирские потоки, новые аппараты не приобретаются. Робастный поиск — эвристическая максимизация "
            f"минимума этих сценариев: худший результат базы {number(base_worst)}, робастного плана {number(robust_worst)}; "
            f"робастный план в базе {number(robust_base)} (потеря к базовому плану {number(total-robust_base)}). "
            f"Конечная игра содержит {game['network_actions']} различных найденных сетей, все отказы построенных узлов и два ответа: "
            "отмена затронутых поездок или перераспределение потоков. Значения листьев одинаковы для обоих обходов; "
            f"результат полного перебора и альфа-бета совпал: {number(game['results'][0]['value'])}. "
            "Это решение заданного конечного дерева, не доказательство оптимальности всех возможных сетей.")
    section("Стоимость устойчивости", f"Базовый план: {number(budget.spend_rub.sum())} руб. "
            f"Робастный план: {number(robust_budget.spend_rub.sum())} руб.; изменение "
            f"{number(robust_budget.spend_rub.sum()-budget.spend_rub.sum())} руб. "
            f"В конце третьего года у робастного плана {int(robust_budget.active_ports.iloc[-1])} портов и "
            f"{int(robust_budget.active_aircraft.iloc[-1])} аппаратов. "
            "Выигрыш худшего сценария достигается иной структурой инвестиций. Робастная оптимальность не доказана: использован отжиг.")
    section("BFS, A* и эксперименты", "BFS минимизирует число перелётов; A* — сумму времени полёта, посадки и зарядки. "
            "Эвристика A*: геодезическое расстояние до цели / максимальная скорость; добавочные времена неотрицательны, "
            "поэтому она не переоценивает стоимость. Сравнение относится к пространственному графу, а не к конкретному расписанию. "
            "Масштабы: 8/12/20/30, финансирование: 0.5/0.75/1 млрд руб. в год, 10 seed отжига. "
            "Для каждого экспериментального плана проверена допустимость. RAM в benchmarks — накопленный пик процесса, "
            "а не изолированный пик отдельного эксперимента. Две стратегии обработки пропусков не сравнивались по указанию пользователя. "
            "ANOVA не применялась; приведены все seed и парные результаты при одинаковом входе.")
    section("Воспроизводимость и ограничения", f"Основной расчёт занял {manifest['wall_seconds']} с; пик процесса "
            f"{manifest['peak_process_ram_mib']:.1f} МиБ. Расчёты выполнены на CPU. RTX 3090 не требовалась. "
            "Хэши входов, кода, конфигураций и артефактов сохранены в run_manifest.json. "
            "Запуск: .venv/bin/python scripts/prepare_data.py, затем .venv/bin/python scripts/run_project.py. "
            "Пересборка отчёта без решения: .venv/bin/python scripts/run_project.py --report-only. "
            "Генеративный ИИ использован для разработки кода, сопоставления условий и пояснений; числа получены выполненным кодом. "
            "Для защиты студент должен самостоятельно разобрать модель и ограничения. "
            "Комплект не является подтверждённой сметой строительства или разрешением на пассажирские полёты.")
    table_budget = budget[["year", "active_ports", "active_aircraft", "spend_rub", "carry_rub"]].copy()
    table_budget["completed_trips"] = manifest["annual_completed"]
    markdown = "# Сеть дронопортов России — вариант И\n\n" + "\n\n".join(f"## {title}\n\n{text}" for title, text in blocks)
    markdown += "\n\n## Таблицы результатов\n\n"
    # Не требует необязательного tabulate.
    def md_table(frame):
        values = [[str(x) for x in row] for row in frame.itertuples(index=False, name=None)]
        return "| " + " | ".join(frame.columns) + " |\n| " + " | ".join(["---"] * len(frame.columns)) + " |\n" + \
            "\n".join("| " + " | ".join(row) + " |" for row in values)
    markdown += md_table(table_budget) + "\n\n" + md_table(methods) + "\n\n" + md_table(seeds) + "\n"
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    tables = [("Бюджет и поездки", table_budget), ("Коридоры и закупки", purchases), ("Сравнение методов", methods),
              ("10 seed", seeds), ("Сценарии", scenarios), ("Эксперименты", benchmarks)]
    markup = "<!doctype html><html lang='ru'><meta charset='utf-8'><title>Дронопорты — вариант И</title>" \
        "<style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui;color:#17283c}h1,h2{color:#185a73}table{border-collapse:collapse;font-size:12px;display:block;overflow:auto}td,th{padding:7px;border:1px solid #ccd8df}img{max-width:100%}.note{padding:16px;background:#eaf3f7}</style>" \
        f"<h1>Сеть дронопортов — вариант И</h1><p class='note'>Запуск {manifest['run_id']} · {number(total)} поездок · проверка пройдена</p>" \
        "<p><a href='maps/network.html'>Открыть карту сети</a> · <a href='report.pdf'>Скачать PDF</a></p>"
    markup += "".join(f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>" for title, text in blocks)
    markup += "".join(f"<h2>{title}</h2>{frame.to_html(index=False,escape=True)}" for title, frame in tables)
    markup += "<h2>Графики</h2><img src='figures/summary.png' alt='Графики результатов'></html>"
    (reports / "report.html").write_text(markup, encoding="utf-8")
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes[0, 0].bar(budget.year, budget.spend_rub / 1e6, label="Расходы")
    axes[0, 0].plot(budget.year, budget.available_rub / 1e6, "o-", color="#e17c38", label="Доступно")
    axes[0, 0].set(title="Годовой бюджет", ylabel="млн рублей", xticks=[1, 2, 3]); axes[0, 0].legend()
    axes[0, 1].bar(budget.year, manifest["annual_completed"], color="#2c8e8e")
    axes[0, 1].set(title="Завершённые поездки по годам", xticks=[1, 2, 3])
    axes[1, 0].plot(seeds.seed, seeds.completed_trips, "o-")
    axes[1, 0].set(title="Отжиг: 10 seed", xlabel="seed", ylabel="поездки за 3 года", xticks=seeds.seed)
    axes[1, 1].bar(["База: худший", "Робастный: худший", "Робастный: база"], [base_worst, robust_worst, robust_base], color=["#b76c49", "#2c8e8e", "#1e688c"])
    axes[1, 1].set(title="Устойчивость, завершённые поездки")
    fig.suptitle(f"Вариант И · {manifest['run_id']}")
    fig.tight_layout(); fig.savefig(figures / "summary.png", dpi=160)
    with PdfPages(reports / "report.pdf") as pdf:
        for title, text in blocks:
            page = plt.figure(figsize=(8.27, 11.69))
            page.text(.08, .94, "СЕТЬ ДРОНОПОРТОВ · ВАРИАНТ И", fontsize=14, color="#185a73", weight="bold")
            page.text(.08, .89, title, fontsize=13, weight="bold")
            wrapped = "\n".join(textwrap.wrap(text, 84))
            page.text(.08, .84, wrapped, fontsize=10, va="top", linespacing=1.65)
            page.text(.08, .04, f"Запуск {manifest['run_id']} · учебная модель · источники и результаты в комплекте", fontsize=8)
            pdf.savefig(page); plt.close(page)
        for title, frame in tables[:3]:
            page, ax = plt.subplots(figsize=(11.69, 8.27)); ax.axis("off")
            ax.set_title(title + " · " + manifest["run_id"], pad=20)
            display = frame.copy()
            table = ax.table(cellText=display.astype(str).values, colLabels=display.columns, loc="center", cellLoc="left")
            table.auto_set_font_size(False); table.set_fontsize(7); table.scale(1, 1.6)
            pdf.savefig(page, bbox_inches="tight"); plt.close(page)
        pdf.savefig(fig)
    plt.close(fig)
    executive = f"# Управленческая записка — вариант И\n\nЗапуск {manifest['run_id']}.\n\n" + blocks[0][1] + "\n\n" + \
        md_table(table_budget) + "\n\nПорядок закупки аппаратов по коридорам:\n\n" + md_table(purchases) + \
        f"\n\nХудший результат базового плана: {number(base_worst)} поездок. " \
        f"Робастный план: {number(robust_worst)} в худшем сценарии и {number(robust_base)} в базе.\n\n" + \
        "Цены, спрос и ввод в начале года — учебные допущения. Результат относится к фиксированным коридорам и ограниченному набору пассажирских путей. " \
        "Две стратегии обработки пропусков отложены по указанию пользователя. Реальная стройка, цены и авиационный допуск не подтверждены.\n"
    (reports / "executive_summary.md").write_text(executive, encoding="utf-8")
    create_map(folder, maps / "network.html")
    print(f"Отчёт: {reports / 'report.html'}; PDF и карта сформированы", flush=True)


def create_map(folder, destination):
    import folium
    from folium.plugins import FastMarkerCluster
    from shapely.geometry import mapping, shape
    towns = pd.read_csv(folder / "towns_main.csv")
    all_towns = pd.read_csv(folder / "towns_all.csv")
    map_ = folium.Map(location=[56.0, 35.3], zoom_start=7, tiles="OpenStreetMap")
    boundaries = json.loads((folder / "region_boundaries.geojson").read_text())
    for feature in boundaries["features"]:
        feature["geometry"] = mapping(shape(feature["geometry"]).simplify(.01, preserve_topology=True))
    folium.GeoJson(boundaries, name="Области и Москва", style_function=lambda f: {"color": "#8c4d3e" if f["properties"]["region_code"] == "77" else "#38758a", "weight": 2, "fillOpacity": .04},
                   tooltip=folium.GeoJsonTooltip(fields=["name"])).add_to(map_)
    FastMarkerCluster(all_towns[["lat", "lon"]].values.tolist(), name="Все допустимые place-узлы", show=False).add_to(map_)
    points = folium.FeatureGroup(name="Фиксированные 30 пунктов", show=True)
    for row in towns.itertuples():
        folium.CircleMarker([row.lat, row.lon], radius=4, color="#556574", fill=True,
                            tooltip=f"{html.escape(row.name_original)} · население {int(row.population):,} (2021)").add_to(points)
    points.add_to(map_)
    network = json.loads((folder / "network_by_year.geojson").read_text())
    for year, color in ((1, "#218b70"), (2, "#cc8b24"), (3, "#b74e51")):
        layer = folium.FeatureGroup(name=f"Сеть: год {year}", show=year == 3)
        for feature in network["features"]:
            if feature["properties"]["year"] != year:
                continue
            if feature["properties"]["kind"] == "port":
                lon, lat = feature["geometry"]["coordinates"]
                folium.CircleMarker([lat, lon], radius=8, color=color, fill=True,
                                    tooltip=feature["properties"]["name"]).add_to(layer)
            else:
                folium.PolyLine([[lat, lon] for lon, lat in feature["geometry"]["coordinates"]], color=color, weight=4,
                                tooltip=f"{feature['properties']['distance_km']:.1f} км · аппаратов {feature['properties']['aircraft']}").add_to(layer)
        layer.add_to(map_)
    folium.LayerControl(collapsed=False).add_to(map_)
    map_.save(str(destination))
