"""Review: пакет приёмки автора и разбор правок (FR-E1, FR-E2, FR-V2.5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import guard, verifier2
from .paths import Workspace
from .schemas import CheckResult, Edit, Flag, Resolution, Verdict


def _anchor(text: str, quote: str, marker: str) -> str:
    """Якорь флага в тексте (FR-E1): маркер после первого вхождения цитаты."""
    quote = quote.strip()
    if quote and quote in text and marker not in text:
        return text.replace(quote, quote + marker, 1)
    return text


def build_review_pack(ws: Workspace, chapter: int, draft: int) -> Path:
    """FR-E1: текст с якорями флагов Э1/Э2 + форма правок + форма решений по самоволкам."""
    chdir = ws.chapter_dir(chapter)
    text = ws.draft_path(chapter, draft).read_text(encoding="utf-8")

    verdict_path = chdir / "verdict.json"
    checks: list[CheckResult] = []
    if verdict_path.exists():
        checks = Verdict.model_validate(json.loads(verdict_path.read_text(encoding="utf-8"))).flags
    flags = verifier2.load_flags(ws, chapter)

    # якоря в тексте: 【check_id】 для Э1, 【flag_id】 для Э2
    for c in checks:
        for q in c.quotes[:3]:
            text = _anchor(text, q, f"【{c.check_id}】")
    for f in flags:
        text = _anchor(text, f.quote, f"【{f.flag_id}】")

    lines = [f"# Приёмка · Глава {chapter} · черновик {draft}", ""]
    lines += ["## Флаги Э1 (формальные)", ""]
    if checks:
        for c in checks:
            lines.append(f"- **[{c.status}] {c.check_id}** — порог: {c.threshold}; факт: {c.actual} ({c.rule_source})")
            for q in c.quotes[:5]:
                lines.append(f"  > {q}")
    else:
        lines.append("- нет")
    lines += ["", "## Флаги Э2 (смысловые)", ""]
    violations = [f for f in flags if f.kind == "violation"]
    samovolki = [f for f in flags if f.kind == "samovolka"]
    if violations:
        for f in violations:
            lines.append(f"- **[{f.severity}] {f.flag_id} · {f.type}** — {f.rule}; рекомендация: {f.recommendation}")
            lines.append(f"  > {f.quote}")
    else:
        lines.append("- нет")
    lines += ["", "## Самоволки (требуют решения автора: «вычеркнуть» или «канонизировать»)", ""]
    if samovolki:
        for f in samovolki:
            lines.append(f"- **{f.flag_id}** — {f.rule}")
            lines.append(f"  > {f.quote}")
    else:
        lines.append("- нет")
    lines += ["", "---", "", "## ТЕКСТ", "", text]
    guard.write_text(chdir / "review.md", "\n".join(lines) + "\n")

    # форма правок
    if not (chdir / "edits.md").exists():
        guard.write_text(
            chdir / "edits.md",
            "\n".join(
                [
                    f"# Правки автора · Глава {chapter}",
                    "",
                    "Формат пары — две строки, маркеры в начале строки (значение может занимать несколько строк):",
                    "",
                    "```",
                    "БЫЛО: точная цитата из текста",
                    "СТАЛО: новая формулировка",
                    "```",
                    "",
                    "Пустое `СТАЛО:` — удалить цитату. Свободные указания — строками, начинающимися с `УКАЗАНИЕ:`.",
                    "Правки разделяйте пустой строкой.",
                    "",
                ]
            )
            + "\n",
        )

    # форма решений по самоволкам (FR-V2.5): пересобирается по ТЕКУЩЕМУ flags.json при каждом
    # review (2.9) — решения по флагам, которые остались, сохраняются; исчезнувшие флаги
    # («фантомные самоволки» прошлого прогона Э2) не блокируют приёмку
    rebuild_resolutions(ws, chapter, samovolki)
    return chdir / "review.md"


def rebuild_resolutions(ws: Workspace, chapter: int, samovolki: list[Flag]) -> list[Resolution]:
    res_path = ws.chapter_dir(chapter) / "resolutions.json"
    existing: dict[str, Resolution] = {}
    if res_path.exists():
        existing = {r.flag_id: r for r in load_resolutions(ws, chapter)}
    merged = [existing.get(f.flag_id, Resolution(flag_id=f.flag_id)) for f in samovolki]
    save_resolutions(ws, chapter, merged)
    return merged


# ------------------------------------------------------------ разбор edits.md


class EditsFormatError(ValueError):
    """Ошибка формата edits.md с номером строки (FR-E2)."""

    def __init__(self, path: Path, line: int, message: str):
        super().__init__(f"{path.name}:{line}: {message}")
        self.path = path
        self.line = line


_MARKER_RE = re.compile(r"^\s*(?P<kind>БЫЛО|СТАЛО|УКАЗАНИЕ)\s*:\s?(?P<rest>.*)$")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def parse_edits_text(text: str, chapter: int, path: Path | None = None) -> list[Edit]:
    """Построчный автомат (2.4): маркеры `БЫЛО:` / `СТАЛО:` / `УКАЗАНИЕ:` в начале строки;
    значение — до следующего маркера или пустой строки (многострочные цитаты допустимы);
    пустое «СТАЛО» = удаление цитаты; «БЫЛО» без «СТАЛО» — ошибка с номером строки;
    «УКАЗАНИЕ» сразу после пары — отдельная правка, а не хвост «СТАЛО».
    """
    src = path or Path("edits.md")
    # примеры формата в ограждённых код-блоках — не правки; номера строк сохраняем
    text = _FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    edits: list[Edit] = []
    state = "idle"  # idle | before | before_done | after | note
    before_lines: list[str] = []
    value: list[str] = []
    before_line = 0

    def emit_pair() -> None:
        edits.append(Edit(chapter=chapter, seq=len(edits) + 1, before="\n".join(before_lines).strip(),
                          after="\n".join(value).strip()))

    def emit_note() -> None:
        note = "\n".join(value).strip()
        if note:
            edits.append(Edit(chapter=chapter, seq=len(edits) + 1, before="", after=note, note="свободное указание"))

    def flush() -> None:
        nonlocal state
        if state == "after":
            emit_pair()
        elif state == "note":
            emit_note()
        state = "idle"

    def require_after(n: int, what: str) -> None:
        if state in ("before", "before_done"):
            raise EditsFormatError(src, n, f"{what}: у «БЫЛО:» (строка {before_line}) нет своего «СТАЛО:»")

    for n, line in enumerate(text.splitlines(), start=1):
        m = _MARKER_RE.match(line)
        if m:
            kind, rest = m.group("kind"), m.group("rest")
            if kind == "БЫЛО":
                require_after(n, f"строка {n}: новое «БЫЛО:»")
                flush()
                if not rest.strip():
                    raise EditsFormatError(src, n, "«БЫЛО:» пустое — нужна точная цитата из черновика")
                before_lines, before_line, state = [rest], n, "before"
            elif kind == "СТАЛО":
                if state not in ("before", "before_done"):
                    raise EditsFormatError(src, n, "«СТАЛО:» без предшествующего «БЫЛО:»")
                value, state = [rest], "after"
            else:  # УКАЗАНИЕ
                require_after(n, f"строка {n}: «УКАЗАНИЕ:»")
                flush()
                value, state = [rest], "note"
            continue
        if not line.strip():
            if state == "before":
                state = "before_done"
            elif state in ("after", "note"):
                flush()
            continue
        if state == "before":
            before_lines.append(line)
        elif state in ("after", "note"):
            value.append(line)
        elif state == "before_done":
            raise EditsFormatError(src, n, f"у «БЫЛО:» (строка {before_line}) нет своего «СТАЛО:»")
        # idle: свободный текст (заголовки, пояснения) — не правка
    if state in ("before", "before_done"):
        raise EditsFormatError(src, before_line, "у «БЫЛО:» нет своего «СТАЛО:» до конца файла")
    flush()
    return edits


def parse_edits_md(ws: Workspace, chapter: int) -> list[Edit]:
    """FR-E2: edits.md (пары «было → стало» и/или свободные указания) → edits.jsonl."""
    path = ws.chapter_dir(chapter) / "edits.md"
    if not path.exists():
        raise FileNotFoundError(f"Нет файла правок {path}. Сначала `ugar review {chapter}`.")
    edits = parse_edits_text(path.read_text(encoding="utf-8"), chapter, path)
    save_edits(ws, chapter, edits)
    return edits


def save_edits(ws: Workspace, chapter: int, edits: list[Edit]) -> None:
    guard.write_text(
        ws.chapter_dir(chapter) / "edits.jsonl",
        "".join(json.dumps(e.model_dump(by_alias=True), ensure_ascii=False) + "\n" for e in edits),
    )


def load_edits(ws: Workspace, chapter: int) -> list[Edit]:
    path = ws.chapter_dir(chapter) / "edits.jsonl"
    if not path.exists():
        return []
    return [
        Edit.model_validate(json.loads(ln))
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def save_resolutions(ws: Workspace, chapter: int, resolutions: list[Resolution]) -> None:
    guard.write_text(
        ws.chapter_dir(chapter) / "resolutions.json",
        json.dumps([r.model_dump() for r in resolutions], ensure_ascii=False, indent=2) + "\n",
    )


def load_resolutions(ws: Workspace, chapter: int) -> list[Resolution]:
    path = ws.chapter_dir(chapter) / "resolutions.json"
    if not path.exists():
        return []
    return [Resolution.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def unresolved_samovolki(ws: Workspace, chapter: int) -> list[str]:
    return [r.flag_id for r in load_resolutions(ws, chapter) if r.decision is None]
