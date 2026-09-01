"""Верификатор-2 (Э2): смысловые проверки LLM (FR-V2.1…FR-V2.5).

Вход — текст + релевантные срезы выгрузок (не полные файлы канона).
Выход — flags.json. При недоступности API промпт сохраняется в
chapters/N/verify2_prompt.md для ручного прогона (NFR-3).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from . import adapters, compiler, exporter, guard, llmjson
from .config import Config
from .paths import Workspace
from .schemas import Flag


def _template(ws: Workspace, name: str) -> str:
    override = ws.templates / name
    if override.exists():
        return override.read_text(encoding="utf-8")
    return resources.files("ugar").joinpath(f"templates/{name}").read_text(encoding="utf-8")


def build_prompt(ws: Workspace, chapter: int, draft: int) -> tuple[str, str]:
    """(system, user): срезы матрицы участников, бриф, закладки, информрежим (FR-V2.1)."""
    exports_dir = ws.exports
    brief = exporter.load_brief(exports_dir, chapter)
    matrix = exporter.load_matrix(exports_dir)
    infobans = exporter.load_infobans(exports_dir)
    stoplists = exporter.load_stoplists(exports_dir)
    continuity = exporter.load_continuity(exports_dir)
    plants = compiler.chapter_plants(exports_dir, brief)
    text = ws.draft_path(chapter, draft).read_text(encoding="utf-8")

    participants = sorted(set([brief.focal, *brief.participants]) - {""})
    line_rules = [
        f"- [{r.rule_id}] {r.applies_to.get('focal', 'все линии')}: {'; '.join(sorted(r.items))} ({r.action})"
        for r in stoplists
        if r.kind == "лексика" and r.scope == "0.3"
        and ("focal" not in r.applies_to or r.applies_to["focal"] in participants)
    ]
    matrix_slice = [
        f"- [{f.fact_id}] {f.subject}: {f.fact} "
        + (f"(узнаёт в гл. {f.from_chapter})" if f.from_chapter is not None else "(НЕ знает)")
        for f in matrix
        if f.subject in participants
    ]
    user = "\n".join(
        [
            f"# Проверка главы {chapter} (том {brief.volume}, фокал: {brief.focal}, дата: {brief.date})",
            "",
            "## Срез матрицы знаний (участники сцены)",
            *matrix_slice,
            "",
            "## Бриф главы",
            f"- Сцены: {'; '.join(brief.scenes)}",
            f"- Биты: {'; '.join(brief.beats)}",
            f"- Запреты: {'; '.join(brief.bans)}",
            f"- Фокал НЕ знает: {'; '.join(brief.not_knows)}",
            "",
            "## Закладки, назначенные главе",
            *[f"- [{p.plant_id}] {p.what}" for p in plants],
            "",
            "## Запреты информрежима (резервы будущих томов)",
            *[
                f"- [{b.ban_id}] {b.text}"
                for b in infobans
                # тот же фильтр, что у компилятора: истёкшие запреты — не нарушение
                if b.until_volume is None or brief.volume <= b.until_volume
            ],
            "",
            "## Стоп-листы линий (фокализация)",
            *line_rules,
            "",
            "## Хронология (сверка дат и анахронизмов)",
            *[f"- {c.date}: {c.event}" + (f" (гл. {c.chapters})" if c.chapters else "") for c in continuity],
            "",
            "## ТЕКСТ ГЛАВЫ",
            "",
            text,
        ]
    )
    return _template(ws, "верификатор2_система.md"), user


def parse_flags(raw: str) -> list[Flag]:
    try:
        data = llmjson.extract_json(raw, list)
    except ValueError as e:
        raise ValueError(f"Ответ Верификатора-2: {e}") from e
    flags = []
    for i, item in enumerate(data, start=1):
        item.setdefault("flag_id", f"F-{i:03d}")
        try:
            flags.append(Flag.model_validate(item))
        except ValidationError as e:
            raise ValueError(f"Невалидный флаг №{i}: {e}") from e
    return flags


def run_verify2(ws: Workspace, cfg: Config, chapter: int, draft: int) -> list[Flag]:
    system, user = build_prompt(ws, chapter, draft)
    prompt_path = ws.chapter_dir(chapter) / "verify2_prompt.md"
    guard.write_text(prompt_path, f"<!-- system -->\n{system}\n\n<!-- user -->\n{user}\n")
    raw = adapters.call_anthropic(
        system, user, cfg.verifier2, cfg.api, ws.logs, role="верификатор-2", chapter=chapter
    )
    flags = parse_flags(raw)
    save_flags(ws, chapter, flags)
    return flags


def save_flags(ws: Workspace, chapter: int, flags: list[Flag]) -> None:
    guard.write_text(
        ws.chapter_dir(chapter) / "flags.json",
        json.dumps([f.model_dump() for f in flags], ensure_ascii=False, indent=2) + "\n",
    )


def load_flags(ws: Workspace, chapter: int) -> list[Flag]:
    path = ws.chapter_dir(chapter) / "flags.json"
    if not path.exists():
        return []
    return [Flag.model_validate(f) for f in json.loads(path.read_text(encoding="utf-8"))]
