"""Compiler: сборка окна контекста главы (FR-C1…FR-C6).

Окно собирается строго по шаблону v1.1 (шаблон `окно.md.j2`), детерминированно:
одинаковые вход и выгрузки → байт-в-байт одинаковое окно (FR-C4).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from . import exporter, guard, mdparse
from .paths import Workspace
from .schemas import Brief, StopRule

SECTION_RE = re.compile(r"<!-- СЕКЦИЯ: (.+?) -->")

# Нормы прозы, показываемые Писателю; служебные пороги верификатора
# (n-граммы, TTR-окно, допуск объёма) в окно не входят.
WINDOW_NORM_IDS = [
    "средняя_длина",
    "доля_коротких",
    "доля_длинных",
    "максимум_длины",
    "короткая_фраза_порог",
    "длинная_фраза_порог",
    "был_на_250",
    "усилители_на_1000",
]


def _template_text(ws: Workspace) -> str:
    override = ws.templates / "окно.md.j2"
    if override.exists():
        return override.read_text(encoding="utf-8")
    return resources.files("ugar").joinpath("templates/окно.md.j2").read_text(encoding="utf-8")


def _style_sections(library: Path) -> str:
    """«Регистр и стиль» — из 02 §1–4 и §6.1 (FR-C1). Полный файл не включается (FR-C3)."""
    path = sorted(library.glob("02_*.md"))[0]
    sections = mdparse.parse_sections(path)
    wanted: list[str] = []
    for s in sections:
        m = re.match(r"§\s*(\d+(?:\.\d+)?)", s.title)
        if not m:
            continue
        num = m.group(1)
        if num in {"1", "2", "3", "4", "6.1"}:
            wanted.append(f"### {s.title}\n{s.body}")
    return "\n\n".join(wanted)


def _focalization_laws(library: Path) -> str:
    """Общие законы фокализации — секция «Общие законы» из 03 (FR-C1)."""
    path = sorted(library.glob("03_*.md"))[0]
    sec = mdparse.find_section(mdparse.parse_sections(path), r"Общие законы")
    return sec.body if sec else ""


def _line_rules(stoplists: list[StopRule], participants: list[str], year: int | None) -> list[dict]:
    """Правила линий только участников сцены + лексика года главы (FR-C1, FR-V1.5)."""
    result = []
    for rule in sorted(stoplists, key=lambda r: (r.scope, r.rule_id)):
        if rule.kind == "усилитель":
            continue
        applies = rule.applies_to
        if "focal" in applies and applies["focal"] not in participants:
            continue
        if "year" in applies and year is not None:
            y = applies["year"]
            if "before" in y and year >= y["before"]:
                continue
            if "from" in y and not (y["from"] <= year <= y.get("to", 9999)):
                continue
        if "focal" in applies:
            scope_note = f"линия «{applies['focal']}»"
        elif rule.scope == "0.3":
            scope_note = "все линии (0.3)"
        else:
            scope_note = f"лексика эпохи ({rule.scope})"
        result.append(
            {"rule_id": rule.rule_id, "items": sorted(rule.items), "action": rule.action, "scope_note": scope_note}
        )
    return result


def chapter_plants(exports_dir: Path, brief: Brief) -> list:
    """Закладки, назначенные главе (FR-C2): по брифу и/или по реестру (placed = том/глава)."""
    plants = exporter.load_plants(exports_dir)
    selected = [
        p
        for p in plants
        if p.plant_id in brief.plants
        or (p.placed.get("vol") == brief.volume and p.placed.get("ch") == brief.chapter)
    ]
    return sorted(selected, key=lambda p: p.plant_id)


def compile_window(ws: Workspace, library: Path, chapter: int, soft_limit_chars: int = 80_000) -> tuple[Path, dict[str, int]]:
    """Собирает окно главы N. Возвращает (путь, раскладка размеров по секциям)."""
    exports_dir = ws.exports
    brief = exporter.load_brief(exports_dir, chapter)
    norms = exporter.load_norms(exports_dir)
    stoplists = exporter.load_stoplists(exports_dir)
    matrix = exporter.load_matrix(exports_dir)
    dossiers = exporter.load_dossiers(exports_dir)
    infobans = exporter.load_infobans(exports_dir)

    participants = sorted(set([brief.focal, *brief.participants]) - {""})

    # «что знает фокал»: только факты с from_chapter ≤ N (FR-C1, FR-C3)
    known = sorted(
        (
            f
            for f in matrix
            if f.subject == brief.focal and f.from_chapter is not None and f.from_chapter <= chapter
        ),
        key=lambda f: f.fact_id,
    )

    scene_dossiers = sorted((d for d in dossiers if d.name in participants), key=lambda d: d.name)

    intensifiers = sorted(
        {w for r in stoplists if r.kind == "усилитель" for w in r.items}
    )

    # запреты брифа + запреты информрежима 2.2 как явные «НЕ упоминать» (FR-C3)
    bans = list(brief.bans) + [
        f"НЕ упоминать (информрежим {b.ban_id}): {b.text}"
        for b in sorted(infobans, key=lambda b: b.ban_id)
        if b.until_volume is None or brief.volume <= b.until_volume
    ]

    env = Environment(undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    window = env.from_string(_template_text(ws)).render(
        brief=brief,
        norms={k: v for k, v in norms.items() if k in WINDOW_NORM_IDS},
        style_sections=_style_sections(library),
        focalization_laws=_focalization_laws(library),
        line_rules=_line_rules(stoplists, participants, brief.year),
        dossiers=scene_dossiers,
        known_facts=known,
        plants=chapter_plants(exports_dir, brief),
        bans=bans,
        intensifiers=intensifiers,
    )

    path = ws.window_path(chapter)
    guard.write_text(path, window)

    breakdown = section_breakdown(window)
    if len(window) > soft_limit_chars:
        lines = [
            f"⚠ Окно главы {chapter} превышает мягкий лимит {soft_limit_chars} символов (Д-12): {len(window)}.",
            "Раскладка по секциям (символов):",
        ] + [f"  - {name}: {size}" for name, size in breakdown.items()]
        guard.write_text(ws.chapter_dir(chapter) / "window_size_флаг.md", "\n".join(lines) + "\n")
    return path, breakdown


def section_breakdown(window: str) -> dict[str, int]:
    """Размер окна по секциям (FR-C5) — по маркерам <!-- СЕКЦИЯ: ... -->."""
    parts = SECTION_RE.split(window)
    breakdown: dict[str, int] = {}
    # parts: [до первой секции, имя1, тело1, имя2, тело2, ...]
    for i in range(1, len(parts) - 1, 2):
        breakdown[parts[i]] = len(parts[i + 1])
    return breakdown
