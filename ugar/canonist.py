"""Канонист: пакет записей в канон на подпись автору (FR-K1…FR-K4).

Единственный компонент, которому разрешена запись в УГАР_Библиотека/ —
и только после явного подтверждения автора (FR-K2, FR-K3).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from . import adapters, exporter, gitops, guard, llmjson, review, verifier2
from .config import Config
from .paths import Workspace
from .schemas import Verdict

REGISTRY_GLOBS = {
    "3.1": "31_*.md",
    "3.2": "32_*.md",
    "3.3": "33_*.md",
    "1.2": "12_*.md",
}

BATCH_ROW_RE = re.compile(r"^- РЕЕСТР\s+(?P<registry>[\d.]+)\s+→\s+(?P<row>.+)$")
TASTE_ROW_RE = re.compile(r"^- ПРАВИЛО\s+(?P<target>02 §[\d.]+)\s+→\s+(?P<rule>.+)$")


def _template(ws: Workspace) -> str:
    override = ws.templates / "канонист_система.md"
    if override.exists():
        return override.read_text(encoding="utf-8")
    return resources.files("ugar").joinpath("templates/канонист_система.md").read_text(encoding="utf-8")


def _llm_proposals(ws: Workspace, cfg: Config, chapter: int, text: str) -> dict:
    """Предложения Канониста через API; при недоступности — пустой каркас (NFR-3)."""
    edits = review.load_edits(ws, chapter)
    resolutions = review.load_resolutions(ws, chapter)
    flags = {f.flag_id: f for f in verifier2.load_flags(ws, chapter)}
    canonized = [
        {"flag_id": r.flag_id, "quote": flags[r.flag_id].quote if r.flag_id in flags else "", "target": r.target_registry}
        for r in resolutions
        if r.decision == "канонизировать"
    ]
    user = "\n".join(
        [
            f"# Глава {chapter}: материалы для пакета записей",
            "",
            "## Правки автора",
            *[f"{e.seq}. БЫЛО: {e.before} → СТАЛО: {e.after}" for e in edits],
            "",
            "## Канонизированные самоволки (решение автора уже принято)",
            *[f"- {c['flag_id']}: {c['quote']} (целевой реестр: {c['target'] or 'предложи'})" for c in canonized],
            "",
            "## ПРИНЯТЫЙ ТЕКСТ ГЛАВЫ",
            "",
            text,
        ]
    )
    system = _template(ws)
    guard.write_text(ws.chapter_dir(chapter) / "canonist_prompt.md", f"<!-- system -->\n{system}\n\n<!-- user -->\n{user}\n")
    try:
        raw = adapters.call_anthropic(
            system, user, cfg.canonist, cfg.api, ws.logs, role="канонист", chapter=chapter
        )
        return llmjson.extract_json(raw, dict)
    except (adapters.ManualModeNeeded, ValueError, json.JSONDecodeError) as e:
        # деградация (NFR-3): пакет собирается без LLM, самоволки — дословными строками
        reason = e.reason if isinstance(e, adapters.ManualModeNeeded) else f"ответ не распарсен: {e}"
        return {
            "facts": [],
            "samovolki": [
                {"flag_id": c["flag_id"], "registry": c["target"] or "3.1", "row": f"| — | {c['quote']} | (сформулировать) |"}
                for c in canonized
            ],
            "edit_classes": [],
            "taste_rules": [],
            "_manual_mode": reason,
        }


def build_batch(ws: Workspace, cfg: Config, chapter: int, draft: int) -> Path:
    """FR-K1: формирует canon_batch.md на подпись автора."""
    unresolved = review.unresolved_samovolki(ws, chapter)
    if unresolved:
        raise RuntimeError(
            f"Не решены самоволки: {', '.join(unresolved)}. Заполните decision в chapters/{chapter:03d}/resolutions.json (FR-V2.5)."
        )
    text = ws.draft_path(chapter, draft).read_text(encoding="utf-8")
    proposals = _llm_proposals(ws, cfg, chapter, text)
    guard.write_text(
        ws.chapter_dir(chapter) / "canon_batch.json",
        json.dumps(proposals, ensure_ascii=False, indent=2) + "\n",
    )

    edits = review.load_edits(ws, chapter)
    classes = {c.get("seq"): c for c in proposals.get("edit_classes", [])}
    for e in edits:
        cls = classes.get(e.seq, {}).get("class")
        if cls in {"вкус", "факт", "канон"}:
            e.class_ = cls  # класс проставляет Канонист, подтверждает автор (5.3)
    review.save_edits(ws, chapter, edits)

    lines = [
        f"# Пакет записей в канон · Глава {chapter}",
        "",
        "Удалите строки, которые НЕ принимаете (отклонённые будут залогированы, FR-K4).",
        "Применение: `ugar canonize " + str(chapter) + " --apply` (подпись автора, FR-K2).",
        "",
        "## Новые факты",
    ]
    for f in proposals.get("facts", []):
        lines.append(f"- РЕЕСТР {f.get('registry', '3.1')} → {f.get('row', '')}  <!-- {f.get('reason', '')} -->")
    lines += ["", "## Канонизированные самоволки"]
    for s in proposals.get("samovolki", []):
        lines.append(f"- РЕЕСТР {s.get('registry', '3.1')} → {s.get('row', '')}  <!-- {s.get('flag_id', '')} -->")
    lines += ["", "## Кандидаты в правила вкуса (из повторяющихся правок)"]
    for t in proposals.get("taste_rules", []):
        lines.append(f"- ПРАВИЛО {t.get('target', '02 §6.1')} → {t.get('rule', '')}  <!-- {t.get('evidence', '')} -->")
    lines += [
        "",
        "## Классы правок (подтвердите/исправьте в chapters/N/edits.jsonl)",
        *[f"- {e.seq}: {e.class_ or '—'} — {e.before[:60]} → {e.after[:60]}" for e in edits],
        "",
    ]
    if proposals.get("_manual_mode"):
        lines.insert(1, f"\n⚠ Канонист работал без LLM (ручной режим): {proposals['_manual_mode']}\n")
    path = ws.chapter_dir(chapter) / "canon_batch.md"
    guard.write_text(path, "\n".join(lines) + "\n")
    return path


def _append_table_row(path: Path, row: str) -> None:
    """Вставляет строку в конец первой таблицы файла реестра.

    Число ячеек выравнивается по заголовку таблицы (недостающие — «—»),
    чтобы структура реестра оставалась валидной для экспортёра (Д-1).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    header_cols = None
    last_row = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|"):
            if header_cols is None:
                header_cols = len([c for c in line.strip().strip("|").split("|")])
            last_row = i
        elif last_row is not None and line.strip() and not line.strip().startswith("|"):
            break
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    if header_cols is not None:
        cells = (cells + ["—"] * header_cols)[:header_cols]
    fixed = "| " + " | ".join(cells) + " |"
    if last_row is None:
        lines += ["", fixed]
    else:
        lines.insert(last_row + 1, fixed)
    guard.write_text(path, "\n".join(lines) + "\n")


def _chapter_prose_name(ws: Workspace, chapter: int) -> str:
    brief = exporter.load_brief(ws.exports, chapter)
    return f"Том{brief.volume}_Глава{chapter:02d}.md"


def apply_batch(ws: Workspace, cfg: Config, library: Path, chapter: int, draft: int) -> str:
    """FR-K2: применяет подписанный пакет = правки MD + export + атомарный git-коммит.

    Вызывается ТОЛЬКО после явного подтверждения автора (CLI, Д-8).
    Перед ЛЮБОЙ записью — проверки, что коммит завершится: повторное применение
    после сорвавшегося коммита продублировало бы строки реестров.
    """
    if gitops.is_repo(library):
        if gitops.dirty(library):
            raise RuntimeError(
                "в библиотеке незакоммиченные изменения — применение пакета требует чистого git "
                "(защита от двойного применения). Закоммитьте их (`ugar canon-commit`) или откатите "
                "(`git restore .`), затем повторите."
            )
        if not gitops.has_identity(library):
            raise RuntimeError(
                "git не настроен: задайте user.name/user.email в библиотеке "
                "(git config user.email …) — иначе коммит приёмки сорвётся после записи в канон."
            )
    batch_path = ws.chapter_dir(chapter) / "canon_batch.md"
    proposals = json.loads((ws.chapter_dir(chapter) / "canon_batch.json").read_text(encoding="utf-8"))
    accepted_rows: list[tuple[str, str]] = []
    accepted_rules: list[tuple[str, str]] = []
    for line in batch_path.read_text(encoding="utf-8").splitlines():
        m = BATCH_ROW_RE.match(line.strip())
        if m:
            accepted_rows.append((m.group("registry"), re.sub(r"\s*<!--.*-->\s*$", "", m.group("row"))))
        m = TASTE_ROW_RE.match(line.strip())
        if m:
            accepted_rules.append((m.group("target"), re.sub(r"\s*<!--.*-->\s*$", "", m.group("rule"))))

    # FR-K4: отклонённые предложения — в лог (для настройки шаблонов Канониста)
    proposed_rows = [
        (p.get("registry", ""), p.get("row", ""))
        for p in proposals.get("facts", []) + proposals.get("samovolki", [])
    ]
    rejected = [p for p in proposed_rows if p not in accepted_rows]
    if rejected:
        guard.append_text(
            ws.logs / "canonist_rejected.jsonl",
            "".join(
                json.dumps({"chapter": chapter, "registry": r, "row": row}, ensure_ascii=False) + "\n"
                for r, row in rejected
            ),
        )

    text = ws.draft_path(chapter, draft).read_text(encoding="utf-8")
    with guard.canon_write_session():
        # 1) текст главы в Проза/
        guard.write_text(library / "Проза" / _chapter_prose_name(ws, chapter), text)
        # 2) строки реестров
        inbox: list[str] = []
        for registry, row in accepted_rows:
            glob = REGISTRY_GLOBS.get(registry)
            target = sorted(library.glob(glob)) if glob else []
            if target and row.strip().startswith("|"):
                _append_table_row(target[0], row.strip())
            else:
                inbox.append(f"- РЕЕСТР {registry}: {row}")
        if inbox:
            guard.append_text(
                library / "КОНВЕЙЕР_Входящие.md",
                f"\n## Глава {chapter}\n" + "\n".join(inbox) + "\n",
            )
        # 3) кандидаты в правила вкуса → в конец 02 (разложит автор)
        if accepted_rules:
            p02 = sorted(library.glob("02_*.md"))[0]
            guard.append_text(
                p02,
                f"\n### Кандидаты конвейера (глава {chapter}) — разложить по §6.1/§6.2\n"
                + "\n".join(f"- {t}: {r}" for t, r in accepted_rules)
                + "\n",
            )
        # 4) статус закладок главы: положена
        _update_plants_status(ws, library, chapter)

    # 5) перегенерация выгрузок и корпуса (текст главы попадает в corpus/)
    exporter.run_export(library, ws.exports, ws.logs)
    # 6) запись метрик главы
    _write_metrics(ws, chapter)

    # 7) атомарный git-коммит (5.1) с шаблонным сообщением (FR-K2)
    n_facts = sum(1 for r, _ in accepted_rows)
    n_edits = len(review.load_edits(ws, chapter))
    n_sam = sum(1 for r in review.load_resolutions(ws, chapter) if r.decision == "канонизировать")
    message = (
        f"[глава {chapter}] приёмка: записей в реестры {n_facts}, правок {n_edits}, "
        f"канонизировано самоволок {n_sam} (конвейер, Р-016)"
    )
    if gitops.is_repo(library):
        return gitops.commit_all(library, message, author=cfg.commit_author)
    return "(библиотека не под git — коммит пропущен, настройте git!)"


def _update_plants_status(ws: Workspace, library: Path, chapter: int) -> None:
    """Помечает закладки главы «положена ✓» в реестре 32."""
    brief = exporter.load_brief(ws.exports, chapter)
    plants = [
        p.plant_id
        for p in exporter.load_plants(ws.exports)
        if p.plant_id in brief.plants
        or (p.placed.get("vol") == brief.volume and p.placed.get("ch") == chapter)
    ]
    if not plants:
        return
    files = sorted(library.glob("32_*.md"))
    if not files:
        return
    path = files[0]
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        for pid in plants:
            if line.strip().startswith("|") and pid in line and "✓" not in line:
                cells = line.split("|")
                if len(cells) >= 3:
                    cells[-2] = " положена ✓ "
                    lines[i] = "|".join(cells)
    guard.write_text(path, "\n".join(lines) + "\n")


def _write_metrics(ws: Workspace, chapter: int) -> None:
    """Метрики для дашборда (FR-D1): правки/1000 слов + метрики Э1."""
    verdict_path = ws.chapter_dir(chapter) / "verdict.json"
    metrics: dict = {"chapter": chapter, "ts": datetime.now(timezone.utc).isoformat()}
    if verdict_path.exists():
        verdict = Verdict.model_validate(json.loads(verdict_path.read_text(encoding="utf-8")))
        for c in verdict.checks:
            try:
                metrics[c.check_id] = float(re.split(r"\s", c.actual)[0])
            except ValueError:
                pass
    edits = review.load_edits(ws, chapter)
    words = None
    stem_tokens = _corpus_tokens(ws, chapter)
    if stem_tokens:
        words = len(stem_tokens)
    if words:
        metrics["слов"] = words
        metrics["правок_на_1000"] = round(len(edits) / words * 1000, 2)
    guard.append_text(ws.logs / "metrics.jsonl", json.dumps(metrics, ensure_ascii=False) + "\n")


def _corpus_tokens(ws: Workspace, chapter: int) -> list[str]:
    try:
        volume = exporter.load_brief(ws.exports, chapter).volume
    except FileNotFoundError:
        volume = None
    f = exporter.find_corpus_file(ws.corpus, chapter, volume)
    return f.read_text(encoding="utf-8").split() if f else []
