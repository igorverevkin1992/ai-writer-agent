"""Дашборд (FR-D1): статический HTML + plotly.js.

Графики: правки/1000 слов по главам; метрики Э1 с коридорами и флагом
отклонения >20% от среднего части; TTR нарастающим окном; расход токенов
и стоимость по ролям.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import exporter, guard, textutils
from .apilog import read_log
from .paths import Workspace

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

METRIC_KEYS = [
    ("V1.2a_средняя_длина", "Средняя длина фразы", "средняя_длина"),
    ("V1.2b_доля_коротких", "Доля коротких фраз", "доля_коротких"),
    ("V1.2c_доля_длинных", "Доля длинных фраз", "доля_длинных"),
    ("V1.3_был", "«был» на 250 слов", "был_на_250"),
    ("V1.4_усилители", "Усилители на 1000 слов", "усилители_на_1000"),
]


def _read_metrics(ws: Workspace) -> list[dict]:
    path = ws.logs / "metrics.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    latest: dict[int, dict] = {}
    for r in rows:
        latest[r["chapter"]] = r  # последняя запись главы побеждает
    return [latest[k] for k in sorted(latest)]


def build_dashboard(ws: Workspace) -> Path:
    metrics = _read_metrics(ws)
    chapters = [m["chapter"] for m in metrics]
    try:
        norms = exporter.load_norms(ws.exports)
    except FileNotFoundError:
        norms = {}

    figures: list[dict] = []

    # правки/1000 слов
    figures.append(
        {
            "title": "Правки автора на 1000 слов",
            "data": [{"x": chapters, "y": [m.get("правок_на_1000") for m in metrics], "type": "bar", "name": "правок/1000"}],
            "layout": {"xaxis": {"title": "Глава"}},
        }
    )

    # метрики Э1 с коридорами и флагом отклонения >20% от среднего части
    for key, title, norm_id in METRIC_KEYS:
        values = [m.get(key) for m in metrics]
        known = [v for v in values if v is not None]
        mean = sum(known) / len(known) if known else None
        shapes = []
        norm = norms.get(norm_id)
        if norm is not None:
            for bound, val in (("мин", norm.min), ("макс", norm.max)):
                if val is not None:
                    shapes.append(
                        {"type": "line", "x0": 0, "x1": 1, "xref": "paper", "y0": val, "y1": val,
                         "line": {"dash": "dash", "color": "#888"}}
                    )
        outliers = [
            {"x": [c], "y": [v], "mode": "markers", "marker": {"size": 12, "color": "red"},
             "name": "отклонение >20% от среднего части", "showlegend": False}
            for c, v in zip(chapters, values)
            if v is not None and mean and abs(v - mean) / mean > 0.20
        ]
        figures.append(
            {
                "title": title,
                "data": [{"x": chapters, "y": values, "type": "scatter", "mode": "lines+markers", "name": title}, *outliers],
                "layout": {"xaxis": {"title": "Глава"}, "shapes": shapes},
            }
        )

    # TTR нарастающим окном по корпусу части
    part_tokens: list[str] = []
    if ws.corpus.exists():
        for f in sorted(ws.corpus.glob("*.txt")):
            part_tokens.extend(f.read_text(encoding="utf-8").split())
    win = int(norms["ttr_окно_слов"].max) if "ttr_окно_слов" in norms else 10_000
    rolling = textutils.rolling_ttr(part_tokens, win)
    ttr_shapes = []
    if "ttr_мин" in norms and norms["ttr_мин"].min is not None:
        ttr_shapes.append(
            {"type": "line", "x0": 0, "x1": 1, "xref": "paper",
             "y0": norms["ttr_мин"].min, "y1": norms["ttr_мин"].min, "line": {"dash": "dash", "color": "red"}}
        )
    figures.append(
        {
            "title": f"TTR нарастающим окном {win} слов (по части)",
            "data": [{"x": [p for p, _ in rolling], "y": [v for _, v in rolling], "type": "scatter", "name": "TTR"}],
            "layout": {"xaxis": {"title": "Позиция (слов)"}, "shapes": ttr_shapes},
        }
    )

    # расход токенов и стоимость по ролям
    api_rows = read_log(ws.logs)
    roles = sorted({r.get("role") for r in api_rows if r.get("role")})
    tokens_by_role = [
        sum((r.get("tokens_in") or 0) + (r.get("tokens_out") or 0) for r in api_rows if r.get("role") == role)
        for role in roles
    ]
    cost_by_role = [
        round(sum(r.get("cost_est") or 0 for r in api_rows if r.get("role") == role), 4) for role in roles
    ]
    figures.append(
        {
            "title": "Токены по ролям",
            "data": [{"x": roles, "y": tokens_by_role, "type": "bar", "name": "токены"}],
            "layout": {},
        }
    )
    figures.append(
        {
            "title": "Оценка стоимости по ролям",
            "data": [{"x": roles, "y": cost_by_role, "type": "bar", "name": "стоимость"}],
            "layout": {},
        }
    )

    divs = []
    scripts = []
    for i, fig in enumerate(figures):
        divs.append(f'<h2>{fig["title"]}</h2><div id="fig{i}" style="height:360px"></div>')
        layout = {"margin": {"t": 20}, **fig["layout"]}
        scripts.append(f'Plotly.newPlot("fig{i}", {json.dumps(fig["data"], ensure_ascii=False)}, {json.dumps(layout, ensure_ascii=False)});')

    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>КОНВЕЙЕР УГАР · Дашборд</title>
<script src="{PLOTLY_CDN}"></script>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}}h2{{margin-top:2rem}}</style>
</head><body>
<h1>КОНВЕЙЕР УГАР · метрики по главам</h1>
<p>Сгенерировано командой <code>ugar dashboard</code>. Пороги — из norms.json (02 §5).</p>
{''.join(divs)}
<script>{''.join(scripts)}</script>
</body></html>
"""
    path = ws.root / "dashboard.html"
    guard.write_text(path, html)
    return path
