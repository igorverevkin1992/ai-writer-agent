"""Круги истории (восемь шагов) для книги, частей (актов) и глав — роль аналитика (Claude).

Результаты — черновики в рабочей области `круги_истории/`; в канон их вносит
автор через правку библиотеки и `ugar canon-commit` (FR-K3). Без API промпты
сохраняются для ручного прогона (NFR-3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from . import adapters, exporter, guard, llmjson
from .config import Config
from .paths import Workspace

SCOPES = ("книга", "части", "главы", "всё")


def _template(ws: Workspace) -> str:
    override = ws.templates / "круг_истории_система.md"
    if override.exists():
        return override.read_text(encoding="utf-8")
    return resources.files("ugar").joinpath("templates/круг_истории_система.md").read_text(encoding="utf-8")


def _dir(ws: Workspace) -> Path:
    return ws.root / "круги_истории"


# ------------------------------------------------------------ материалы


def _chapter_rows(briefs, lo: int | None = None, hi: int | None = None) -> list[str]:
    rows = []
    for b in sorted(briefs, key=lambda b: b.chapter):
        if lo is not None and b.chapter < lo:
            continue
        if hi is not None and b.chapter > hi:
            continue
        beats = "; ".join(x for x in b.beats if not x.lower().startswith("кладём"))
        rows.append(f"- гл. {b.chapter} · {b.date} · фокал {b.focal}: {beats}")
    return rows


def build_material(ws: Workspace, scope: str, key: int | None = None) -> tuple[str, str]:
    """(заголовок, материал) для круга: книга / часть N / глава N."""
    ex = ws.exports
    briefs = exporter.load_briefs(ex)
    bans = exporter.load_infobans(ex)
    secrets = [
        f"- {b.text} (читатель узнаёт: {'гл. ' + str(b.until_chapter) if b.until_chapter else 'не в этом томе'})"
        for b in bans if b.secret
    ]
    if scope == "книга":
        parts = exporter.load_parts(ex)
        parts_lines = [f"- Часть {p['part']} «{p['title']}» — {p['period']} (гл. {p['from_chapter']}–{p['to_chapter']})" for p in parts]
        material = "\n".join(
            ["## Части тома", *parts_lines, "", "## Главы тома", *_chapter_rows(briefs), "", "## Реестр тайн (режим читателя)", *secrets]
        )
        return "Книга (том целиком)", material
    if scope == "часть":
        part = next((p for p in exporter.load_parts(ex) if p["part"] == key), None)
        if part is None:
            raise FileNotFoundError(f"части {key} нет в реестре")
        lo, hi = part["from_chapter"], part["to_chapter"]
        material = "\n".join(
            [f"## Часть {part['part']} «{part['title']}» — {part['period']}", *_chapter_rows(briefs, lo, hi), "",
             "## Тайны, раскрываемые читателю в этой части",
             *[s for b, s in zip([b for b in bans if b.secret], secrets) if b.until_chapter and lo <= b.until_chapter <= hi]]
        )
        return f"Часть {part['part']} «{part['title']}»", material
    if scope == "глава":
        brief = exporter.load_brief(ex, key)
        matrix = exporter.load_matrix(ex)
        known = [f"- [{f.fact_id}] {f.fact}" for f in matrix
                 if f.subject == brief.focal and f.from_chapter is not None and f.from_chapter <= key]
        from . import compiler

        plants = [f"- [{p.plant_id}] {p.what}" for p in compiler.chapter_plants(ex, brief)]
        material = "\n".join(
            [f"## Глава {key} · {brief.date} · фокал {brief.focal}", "### Сцены", *[f"- {s}" for s in brief.scenes],
             "### Биты", *[f"- {b}" for b in brief.beats], "### Что знает фокал", *known, "### Закладки главы", *plants]
        )
        return f"Глава {key}", material
    raise ValueError(f"неизвестный охват: {scope}")


# ---------------------------------------------------------------- прогон


def targets(ws: Workspace, scope: str, chapter: int | None = None) -> list[tuple[str, int | None]]:
    """Список (охват, ключ) по выбору: книга | части | главы | всё | одна глава."""
    if scope == "книга":
        return [("книга", None)]
    if scope == "части":
        return [("часть", p["part"]) for p in exporter.load_parts(ws.exports)]
    if scope == "главы":
        if chapter is not None:
            return [("глава", chapter)]
        return [("глава", b.chapter) for b in sorted(exporter.load_briefs(ws.exports), key=lambda b: b.chapter)]
    if scope == "всё":
        return targets(ws, "книга") + targets(ws, "части") + targets(ws, "главы")
    raise ValueError(f"охват должен быть одним из {SCOPES}")


def _file_stem(scope: str, key: int | None) -> str:
    if scope == "книга":
        return "книга"
    if scope == "часть":
        return f"часть_{key}"
    return f"глава_{int(key or 0):02d}"


def render_md(circle: dict) -> str:
    lines = [f"# Круг истории · {circle.get('title', '')}", ""]
    if circle.get("summary"):
        lines += [f"**Суть:** {circle['summary']}", ""]
    for st in circle.get("steps", []):
        lines.append(f"## {st.get('n')}. {st.get('name')}" + (f" ({st['chapters']})" if st.get("chapters") else ""))
        lines.append(st.get("text", ""))
        lines.append("")
    if circle.get("weak_spot"):
        lines += ["## Слабое место", circle["weak_spot"], ""]
    return "\n".join(lines)


def save_circle(ws: Workspace, scope: str, key: int | None, circle: dict) -> Path:
    stem = _file_stem(scope, key)
    circle = {**circle, "scope": scope, "key": key, "generated": datetime.now(timezone.utc).isoformat()}
    guard.write_text(_dir(ws) / f"{stem}.json", json.dumps(circle, ensure_ascii=False, indent=2) + "\n")
    path = _dir(ws) / f"{stem}.md"
    guard.write_text(path, render_md(circle))
    return path


def run(ws: Workspace, cfg: Config, scope: str, chapter: int | None = None, only_missing: bool = True) -> dict:
    """Генерация кругов. Возвращает {готово: [...], промпты: [...]} — промпты для ручного прогона."""
    done: list[str] = []
    prompts: list[str] = []
    system = _template(ws)
    manual_reason = None
    for sc, key in targets(ws, scope, chapter):
        stem = _file_stem(sc, key)
        if only_missing and (_dir(ws) / f"{stem}.json").exists():
            continue
        title, material = build_material(ws, sc, key)
        user = f"# {title}\n\n{material}"
        prompt_path = _dir(ws) / "промпты" / f"{stem}.md"
        guard.write_text(prompt_path, f"<!-- system -->\n{system}\n\n<!-- user -->\n{user}\n")
        if manual_reason:
            prompts.append(str(prompt_path))
            continue
        try:
            raw = adapters.call_anthropic(system, user, cfg.canonist, cfg.api, ws.logs, role="аналитик (круг истории)")
            circle = llmjson.extract_json(raw, dict)
            circle.setdefault("title", title)
            done.append(str(save_circle(ws, sc, key, circle)))
        except adapters.ManualModeNeeded as e:
            manual_reason = e.reason
            prompts.append(str(prompt_path))
    return {"готово": done, "промпты": prompts, "ручной_режим": manual_reason}


def accept_manual(ws: Workspace, scope: str, key: int | None, raw: str) -> Path:
    """Ручной режим: вставленный ответ модели → файл круга."""
    circle = llmjson.extract_json(raw, dict)
    circle.setdefault("title", build_material(ws, scope, key)[0])
    return save_circle(ws, scope, key, circle)


def list_circles(ws: Workspace) -> list[dict]:
    out = []
    for p in sorted(_dir(ws).glob("*.json")) if _dir(ws).exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    order = {"книга": 0, "часть": 1, "глава": 2}
    return sorted(out, key=lambda c: (order.get(c.get("scope"), 9), c.get("key") or 0))
