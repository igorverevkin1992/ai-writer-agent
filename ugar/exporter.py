"""Exporter: MD-библиотека → JSON-выгрузки (FR-X1…FR-X3, модель данных 5.2).

Выгрузки генерируются ТОЛЬКО экспортёром; правка руками бессмысленна —
перетираются. Идемпотентен: одинаковый канон → байт-в-байт одинаковые файлы.
Хэши выгрузок пишутся в logs/export.jsonl для контроля дрейфа канона.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from . import guard, mdparse, textutils
from .mdparse import MarkupError, cell, parse_number
from .schemas import (
    Brief,
    ContinuityEvent,
    Dossier,
    InfoBan,
    MatrixFact,
    Norm,
    Plant,
    StopRule,
)

# Обязательные идентификаторы норм (02 §5) — verifier-1 берёт пороги только отсюда.
REQUIRED_NORMS = [
    "средняя_длина",
    "доля_коротких",
    "доля_длинных",
    "максимум_длины",
    "короткая_фраза_порог",
    "длинная_фраза_порог",
    "был_на_250",
    "усилители_на_1000",
    "ttr_окно_слов",
    "ttr_мин",
    "объём_допуск",
    "утечка_нграмма",
    "повтор_нграмма",
]


def _find_file(library: Path, pattern: str) -> Path:
    matches = sorted(library.glob(pattern))
    if not matches:
        raise MarkupError(library / pattern, 0, "файл канона не найден")
    return matches[0]


def _dump(path: Path, model: BaseModel | list | dict) -> str:
    if isinstance(model, BaseModel):
        data = model.model_dump(by_alias=True)
    elif isinstance(model, list):
        data = [m.model_dump(by_alias=True) if isinstance(m, BaseModel) else m for m in model]
    else:
        data = {k: (v.model_dump() if isinstance(v, BaseModel) else v) for k, v in model.items()}
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    guard.write_text(path, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ разборы


def export_norms(library: Path) -> dict[str, Norm]:
    path = _find_file(library, "02_*.md")
    table = mdparse.require_table(path, ["id", "мин", "макс"], section_pattern=r"§\s*5")
    norms: dict[str, Norm] = {}
    for row in table.rows:
        norm_id = cell(row, "id")
        if not norm_id:
            continue
        norms[norm_id] = Norm(
            min=parse_number(cell(row, "мин")),
            max=parse_number(cell(row, "макс")),
            brak=parse_number(cell(row, "брак")),
            unit=cell(row, "единиц"),
            source=f"{path.name} §5",
        )
    missing = [n for n in REQUIRED_NORMS if n not in norms]
    if missing:
        raise MarkupError(path, table.line, f"в таблице норм §5 нет обязательных id: {missing}")
    return norms


def export_stoplists(library: Path) -> list[StopRule]:
    rules: list[StopRule] = []

    # 0.3 — стоп-листы линий (по фокалу)
    p03 = _find_file(library, "03_*.md")
    t = mdparse.require_table(p03, ["rule_id", "фокал", "слова"])
    for row in t.rows:
        rules.append(
            StopRule(
                scope="0.3",
                rule_id=cell(row, "rule_id"),
                items=[w.strip() for w in cell(row, "слова").split(";") if w.strip()],
                applies_to={"focal": cell(row, "фокал")} if cell(row, "фокал") not in {"", "все"} else {"all": True},
                action="запрет" if "запрет" in cell(row, "действ") else "флаг",
            )
        )

    # 0.4 — лексика эпохи (по году главы)
    p04 = _find_file(library, "04_*.md")
    t = mdparse.require_table(p04, ["rule_id", "слова", "годы"])
    for row in t.rows:
        years = cell(row, "годы")
        applies: dict = {"all": True}
        m = re.match(r"до\s+(\d{4})", years)
        if m:
            applies = {"year": {"before": int(m.group(1))}}
        else:
            m = re.match(r"(\d{4})\s*[–-]\s*(\d{4})", years)
            if m:
                applies = {"year": {"from": int(m.group(1)), "to": int(m.group(2))}}
        rules.append(
            StopRule(
                scope="0.4",
                rule_id=cell(row, "rule_id"),
                items=[w.strip() for w in cell(row, "слова").split(";") if w.strip()],
                applies_to=applies,
                action="запрет" if "запрет" in cell(row, "действ") else "флаг",
            )
        )

    # Р-016 — словарь наречий-усилителей (02, секция «усилител»)
    p02 = _find_file(library, "02_*.md")
    t = mdparse.require_table(p02, ["слово"], section_pattern=r"[Уу]силител")
    intensifiers = [cell(row, "слово") for row in t.rows if cell(row, "слово")]
    rules.append(
        StopRule(
            scope="0.4",
            rule_id="Р-016",
            items=intensifiers,
            applies_to={"all": True},
            action="флаг",
            kind="усилитель",
        )
    )
    return rules


def export_matrix(library: Path) -> list[MatrixFact]:
    path = _find_file(library, "31_*.md")
    t = mdparse.require_table(path, ["fact_id", "факт", "субъект"])
    facts = []
    for row in t.rows:
        ch = parse_number(cell(row, "узнаёт"))
        facts.append(
            MatrixFact(
                fact_id=cell(row, "fact_id"),
                fact=cell(row, "факт"),
                subject=cell(row, "субъект"),
                from_chapter=int(ch) if ch is not None else None,
                source=cell(row, "источник"),
                note=cell(row, "примечани"),
            )
        )
    return facts


_PLACE_RE = re.compile(r"т\s*(\d+)(?:\s*гл\s*(\d+))?", re.IGNORECASE)


def _parse_place(text: str) -> dict:
    m = _PLACE_RE.search(text)
    if not m:
        return {}
    place: dict = {"vol": int(m.group(1))}
    if m.group(2):
        place["ch"] = int(m.group(2))
    return place


def export_plants(library: Path) -> list[Plant]:
    path = _find_file(library, "32_*.md")
    t = mdparse.require_table(path, ["plant_id", "что", "положена"])
    plants = []
    for row in t.rows:
        fires = [
            _parse_place(x) for x in cell(row, "выстрел").split(";") if _parse_place(x)
        ]
        plants.append(
            Plant(
                plant_id=cell(row, "plant_id"),
                what=cell(row, "что"),
                placed=_parse_place(cell(row, "положена")),
                fires=fires,
                status=cell(row, "статус"),
            )
        )
    return plants


def export_continuity(library: Path) -> list[ContinuityEvent]:
    path = _find_file(library, "33_*.md")
    t = mdparse.require_table(path, ["дата", "событие"])
    return [
        ContinuityEvent(
            date=cell(row, "дата"),
            event=cell(row, "событие"),
            chapters=cell(row, "глав"),
            note=cell(row, "примечани"),
        )
        for row in t.rows
    ]


def export_briefs(library: Path) -> list[Brief]:
    briefs: list[Brief] = []
    for path in sorted(library.glob("23_*.md")):
        vol_m = re.search(r"Том\s*(\d+)", path.name)
        volume = int(vol_m.group(1)) if vol_m else 1
        for sec in mdparse.parse_sections(path):
            m = re.match(r"Глава\s+(\d+)", sec.title)
            if not m:
                continue
            body = sec.body
            date = mdparse.parse_kv(body, "Дата")
            year_s = mdparse.parse_kv(body, "Год")
            year = int(year_s) if year_s.isdigit() else None
            if year is None:
                ym = re.search(r"(19|20)\d{2}", date)
                year = int(ym.group()) if ym else None
            vol = parse_number(mdparse.parse_kv(body, "Объём"))
            briefs.append(
                Brief(
                    chapter=int(m.group(1)),
                    volume=volume,
                    date=date,
                    year=year,
                    focal=mdparse.parse_kv(body, "Фокал"),
                    scenes=mdparse.parse_list_items(body, "Сцены"),
                    participants=mdparse.parse_list_items(body, "Участники"),
                    beats=mdparse.parse_list_items(body, "Биты"),
                    bans=mdparse.parse_list_items(body, "Запреты"),
                    not_knows=mdparse.parse_list_items(body, "НЕ знает"),
                    volume_words=int(vol) if vol else None,
                    plants=[p.strip() for p in mdparse.parse_kv(body, "Закладки").split(";") if p.strip()],
                )
            )
    if not briefs:
        raise MarkupError(library / "23_*.md", 0, "поглавник не найден или в нём нет секций «## Глава N»")
    return briefs


def export_dossiers(library: Path) -> list[Dossier]:
    dossiers = []
    for path in sorted(library.glob("Досье/*.md")):
        sections = mdparse.parse_sections(path)
        name = next((s.title for s in sections if s.level == 1), path.stem)
        rel: dict[str, str] = {}
        rel_sec = mdparse.find_section(sections, r"Отношени")
        if rel_sec:
            for t in mdparse.parse_tables(path, rel_sec.body, start_line=rel_sec.line + 1):
                for row in t.rows:
                    rel[cell(row, "к кому")] = cell(row, "отношени")

        def body_of(pattern: str) -> str:
            s = mdparse.find_section(sections, pattern)
            return s.body if s else ""

        dossiers.append(
            Dossier(
                name=name,
                profile=body_of(r"Профил"),
                physique=body_of(r"Физик"),
                speech=body_of(r"Речев"),
                relations=rel,
            )
        )
    return dossiers


def export_infobans(library: Path) -> list[InfoBan]:
    matches = sorted(library.glob("2.2_*.md"))
    if not matches:
        return []
    path = matches[0]
    t = mdparse.require_table(path, ["ban_id", "запрет"])
    bans = []
    for row in t.rows:
        until = parse_number(cell(row, "до тома"))
        bans.append(
            InfoBan(
                ban_id=cell(row, "ban_id"),
                text=cell(row, "запрет"),
                until_volume=int(until) if until else None,
            )
        )
    return bans


def export_corpus(library: Path, exports_dir: Path) -> dict[str, str]:
    """corpus/ — принятые главы в нормализованном виде (для n-грамм и TTR)."""
    corpus_dir = exports_dir / "corpus"
    hashes: dict[str, str] = {}
    seen: set[str] = set()
    for path in sorted(library.glob("Проза/*.md")):
        tokens = textutils.normalize(textutils.narrator_text(path.read_text(encoding="utf-8")))
        out = corpus_dir / (path.stem + ".txt")
        text = " ".join(tokens) + "\n"
        guard.write_text(out, text)
        seen.add(out.name)
        hashes[out.name] = hashlib.sha256(text.encode()).hexdigest()
    if corpus_dir.exists():
        for stale in corpus_dir.glob("*.txt"):
            if stale.name not in seen:
                stale.unlink()
    return hashes


# --------------------------------------------------------------- запуск


def run_export(library: Path, exports_dir: Path, logs_dir: Path) -> dict[str, str]:
    """Перегенерирует все выгрузки (FR-X1). Возвращает {файл: sha256}."""
    hashes: dict[str, str] = {}
    hashes["norms.json"] = _dump(exports_dir / "norms.json", export_norms(library))
    hashes["stoplists.json"] = _dump(exports_dir / "stoplists.json", export_stoplists(library))
    hashes["matrix.json"] = _dump(exports_dir / "matrix.json", export_matrix(library))
    hashes["plants.json"] = _dump(exports_dir / "plants.json", export_plants(library))
    hashes["continuity.json"] = _dump(exports_dir / "continuity.json", export_continuity(library))
    hashes["briefs.json"] = _dump(exports_dir / "briefs.json", export_briefs(library))
    hashes["dossiers.json"] = _dump(exports_dir / "dossiers.json", export_dossiers(library))
    hashes["infobans.json"] = _dump(exports_dir / "infobans.json", export_infobans(library))
    hashes.update(export_corpus(library, exports_dir))

    manifest = {"files": hashes}
    guard.write_text(
        exports_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    guard.append_text(
        logs_dir / "export.jsonl",
        json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(), "hashes": hashes},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
    )
    return hashes


# --------------------------------------------------------------- чтение


def load_export(exports_dir: Path, name: str):
    path = exports_dir / name
    if not path.exists():
        raise FileNotFoundError(
            f"Выгрузка {name} не найдена. Выполните `ugar export` (экспорт обязателен перед compile, риск R-5)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_norms(exports_dir: Path) -> dict[str, Norm]:
    return {k: Norm.model_validate(v) for k, v in load_export(exports_dir, "norms.json").items()}


def load_stoplists(exports_dir: Path) -> list[StopRule]:
    return [StopRule.model_validate(r) for r in load_export(exports_dir, "stoplists.json")]


def load_matrix(exports_dir: Path) -> list[MatrixFact]:
    return [MatrixFact.model_validate(r) for r in load_export(exports_dir, "matrix.json")]


def load_plants(exports_dir: Path) -> list[Plant]:
    return [Plant.model_validate(r) for r in load_export(exports_dir, "plants.json")]


def load_briefs(exports_dir: Path) -> list[Brief]:
    return [Brief.model_validate(r) for r in load_export(exports_dir, "briefs.json")]


def load_brief(exports_dir: Path, chapter: int) -> Brief:
    for b in load_briefs(exports_dir):
        if b.chapter == chapter:
            return b
    raise FileNotFoundError(f"В поглавнике (briefs.json) нет главы {chapter}.")


def load_dossiers(exports_dir: Path) -> list[Dossier]:
    return [Dossier.model_validate(r) for r in load_export(exports_dir, "dossiers.json")]


def load_infobans(exports_dir: Path) -> list[InfoBan]:
    return [InfoBan.model_validate(r) for r in load_export(exports_dir, "infobans.json")]
