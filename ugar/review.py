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
                    "Формат пары (разделитель `→` на отдельной строке между «было» и «стало»):",
                    "",
                    "```",
                    "БЫЛО: точная цитата из текста",
                    "СТАЛО: новая формулировка",
                    "```",
                    "",
                    "Свободные указания — строками, начинающимися с `УКАЗАНИЕ:`.",
                    "",
                ]
            )
            + "\n",
        )

    # форма решений по самоволкам (FR-V2.5)
    resolutions = [Resolution(flag_id=f.flag_id).model_dump() for f in samovolki]
    res_path = chdir / "resolutions.json"
    if not res_path.exists() or samovolki:
        existing: dict[str, dict] = {}
        if res_path.exists():
            existing = {r["flag_id"]: r for r in json.loads(res_path.read_text(encoding="utf-8"))}
        merged = [existing.get(r["flag_id"], r) for r in resolutions]
        guard.write_text(res_path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    return chdir / "review.md"


# «СТАЛО» может занимать несколько строк — до пустой строки, следующего «БЫЛО:» или конца файла
_PAIR_RE = re.compile(
    r"БЫЛО:\s*(?P<before>.+?)\s*\nСТАЛО:\s*(?P<after>.+?)(?=\n\s*\n|\nБЫЛО:|\Z)", re.DOTALL
)
_FREE_RE = re.compile(r"^УКАЗАНИЕ:\s*(.+)$", re.MULTILINE)


def parse_edits_md(ws: Workspace, chapter: int) -> list[Edit]:
    """FR-E2: edits.md (пары «было → стало» и/или свободные указания) → edits.jsonl."""
    path = ws.chapter_dir(chapter) / "edits.md"
    if not path.exists():
        raise FileNotFoundError(f"Нет файла правок {path}. Сначала `ugar review {chapter}`.")
    text = path.read_text(encoding="utf-8")
    # примеры формата в ограждённых код-блоках — не правки
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    edits: list[Edit] = []
    seq = 1
    for m in _PAIR_RE.finditer(text):
        edits.append(Edit(chapter=chapter, seq=seq, before=m.group("before").strip(), after=m.group("after").strip()))
        seq += 1
    for m in _FREE_RE.finditer(text):
        edits.append(Edit(chapter=chapter, seq=seq, before="", after=m.group(1).strip(), note="свободное указание"))
        seq += 1
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


def load_resolutions(ws: Workspace, chapter: int) -> list[Resolution]:
    path = ws.chapter_dir(chapter) / "resolutions.json"
    if not path.exists():
        return []
    return [Resolution.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def unresolved_samovolki(ws: Workspace, chapter: int) -> list[str]:
    return [r.flag_id for r in load_resolutions(ws, chapter) if r.decision is None]
