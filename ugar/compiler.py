"""Compiler: сборка окна контекста главы (FR-C1…FR-C6).

Окно собирается строго по шаблону v1.1 (шаблон `окно.md.j2`), детерминированно:
одинаковые вход и выгрузки → байт-в-байт одинаковое окно (FR-C4).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from . import circles, exporter, guard, mdparse
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
    "объём_главы",
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
        # «§1. …» (демо) либо «## 1. …» / «## 6.1. …» (реальный регламент)
        m = re.match(r"(?:§\s*)?(\d+(?:\.\d+)?)\.?\s", s.title + " ")
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


def ban_active(b, brief: Brief) -> bool:
    """Запрет информрежима действует для главы? Единый фильтр компилятора и Э2 (FR-C3)."""
    if b.until_chapter is not None:  # реестр тайн: до главы раскрытия читателю
        return brief.chapter < b.until_chapter
    return b.until_volume is None or brief.volume <= b.until_volume


_FUTURE_RE = re.compile(r"(?:\bт\.\s*(\d+)|\bтом[аеу]?\s+(\d+)|\bт\.(\d+)[–-]\d+|Ф-19\d\d|Р-\d{3}|\bцикл)", re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+|\n+")


def _safe_sentences(text: str, markers: list[str], volume: int) -> str:
    """Оставляет только фразы без маркеров незнакомых фокалу тайн и без ссылок на будущие тома (Р-022)."""
    kept: list[str] = []
    low_markers = [m.lower() for m in markers if m]
    for sent in _SENT_SPLIT_RE.split(text):
        sent = sent.strip()
        if not sent or sent.lower().startswith("возраст по томам"):
            continue
        low = sent.lower()
        if any(m in low for m in low_markers):
            continue
        future = False
        for m in _FUTURE_RE.finditer(sent):
            num = next((g for g in m.groups() if g), None)
            if num is None or int(num) > volume:
                future = True
                break
        if future:
            continue
        kept.append(sent)
    return " ".join(kept)


def safe_dossier(d, brief: Brief, infobans: list, participants: list[str]):
    """Проекция досье для окна (FR-C3, Р-022): без каркаса/арки/статуса, без фраз о тайнах,
    которых фокал не знает к этой главе, без будущих томов; отношения — только к участникам сцены."""
    markers: list[str] = []
    for b in infobans:
        if b.secret and not b.known_to(brief.focal, brief.chapter):
            markers.extend(b.markers)
    relations = {
        k: _safe_sentences(v, markers, brief.volume)
        for k, v in d.relations.items()
        if any(k.lower().startswith(n.lower()) or n.lower().startswith(k.lower()) for n in participants if n != d.name)
    }
    return d.model_copy(update={
        "profile": _safe_sentences(d.profile, markers, brief.volume),
        "physique": _safe_sentences(d.physique, markers, brief.volume),
        "speech": _safe_sentences(d.speech, markers, brief.volume),
        "relations": {k: v for k, v in relations.items() if v},
    })


def chapter_plants(exports_dir: Path, brief: Brief) -> list:
    """Закладки, назначенные главе (FR-C2): по брифу и/или по реестру (placed = том/глава)."""
    plants = exporter.load_plants(exports_dir)
    selected = [
        p
        for p in plants
        if p.plant_id in brief.plants
        or (p.placed.get("vol") == brief.volume and p.placed.get("ch") == brief.chapter)
        or (p.placed.get("vol") == brief.volume and brief.chapter in p.chapters)
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
            # частичное/неверное знание (курсив матрицы) — Писателю показывается текст пометки, не сам факт (FR-C3)
            f.model_copy(update={"fact": f.note.split(":", 1)[1].strip() + " (знание неполное)"})
            if f.note.startswith("частично") else f
            for f in matrix
            if f.subject == brief.focal and f.from_chapter is not None and f.from_chapter <= chapter
        ),
        key=lambda f: f.fact_id,
    )

    scene_dossiers = sorted(
        (safe_dossier(d, brief, infobans, participants) for d in dossiers if d.name in participants),
        key=lambda d: d.name,
    )

    # «НЕ знает»: только явные формулировки брифа. Содержание тайн из матрицы
    # в окно НЕ попадает (FR-C3) — Писатель не должен знать то, чего не знает фокал;
    # число скрытых фактов сообщается без раскрытия.
    hidden = sum(
        1 for f in matrix
        if f.subject == brief.focal and (f.from_chapter is None or f.from_chapter > chapter)
    )
    not_knows = list(brief.not_knows) + (
        [f"ещё {hidden} факт(ов) матрицы фокалу недоступны — никаких намёков в их сторону"] if hidden else []
    )

    intensifiers = sorted(
        {w for r in stoplists if r.kind == "усилитель" for w in r.items}
    )

    # запреты брифа + запреты информрежима 2.2 как явные «НЕ упоминать» (FR-C3)
    def _ban_text(b) -> str:
        if b.secret:
            # тайна реестра: содержание Писателю не сообщаем (FR-C3), только факт запрета
            when = f"читатель узнаёт в гл. {b.until_chapter}" if b.until_chapter else "не раскрывается в этом томе"
            return f"НЕ раскрывать и не намекать: тайна {b.ban_id} реестра информрежима ({when})"
        return f"НЕ упоминать (информрежим {b.ban_id}): {b.text}"

    bans = list(brief.bans) + [
        _ban_text(b) for b in sorted(infobans, key=lambda b: b.ban_id) if ban_active(b, brief)
    ]

    # каркас драматургии (Р-020): только из канона (2.1 → circles.json), не из черновиков
    try:
        drama = circles.frame_for_chapter(exporter.load_circles(exports_dir), exporter.load_acts(exports_dir), chapter)
    except FileNotFoundError:
        drama = circles.frame_for_chapter([], [], chapter)

    env = Environment(undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    window = env.from_string(_template_text(ws)).render(
        brief=brief,
        norms={k: v for k, v in norms.items() if k in WINDOW_NORM_IDS},
        style_sections=_style_sections(library),
        focalization_laws=_focalization_laws(library),
        line_rules=_line_rules(stoplists, participants, brief.year),
        dossiers=scene_dossiers,
        known_facts=known,
        not_knows=not_knows,
        plants=chapter_plants(exports_dir, brief),
        bans=bans,
        intensifiers=intensifiers,
        volume_norm=norms.get("объём_главы"),
        drama=drama,
        drama_lines=circles.frame_lines(drama),
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
