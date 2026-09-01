"""Регрессионный корпус золотых тестов (FR-R1…FR-R4).

Пропуск любого ожидаемого флага блокирует смену конфигурации (FR-R3):
предупреждение при `accept`, запрет при фиксации `retest`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import exporter, guard, verifier1
from .paths import Workspace
from .schemas import Brief, GoldenTest


def golden_dir(ws: Workspace) -> Path:
    return ws.regression / "golden"


def load_tests(ws: Workspace) -> list[GoldenTest]:
    tests = []
    for path in sorted(golden_dir(ws).glob("*.json")):
        tests.append(GoldenTest.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    return tests


def add_test(ws: Workspace, test: GoldenTest) -> Path:
    """FR-R1: пополнение корпуса из ошибки, пропущенной эшелонами и пойманной автором."""
    path = golden_dir(ws) / f"{test.test_id}.json"
    guard.write_text(path, json.dumps(test.model_dump(), ensure_ascii=False, indent=2) + "\n")
    return path


def _brief_from_context(ctx: dict) -> Brief:
    return Brief(
        chapter=int(ctx.get("chapter", 1)),
        volume=int(ctx.get("volume", 1)),
        year=ctx.get("year"),
        focal=ctx.get("focal", ""),
        volume_words=ctx.get("volume_words"),
        not_knows=ctx.get("not_knows", []),
    )


def run_e1_test(ws: Workspace, test: GoldenTest) -> tuple[list[str], list[str], list[str]]:
    """Прогон Э1 по фрагменту: (поймано, пропущено, лишние flag-и по check_id)."""
    norms = exporter.load_norms(ws.exports)
    stoplists = exporter.load_stoplists(ws.exports)
    checks = verifier1.analyze(
        test.fragment,
        test.context_slice.get("window", ""),
        _brief_from_context(test.context_slice),
        norms,
        stoplists,
        corpus_dir=ws.corpus if test.context_slice.get("use_corpus") else None,
    )
    raised = {c.check_id for c in checks if c.status != "PASS"}
    expected = set(test.expected_flags)
    caught = sorted(raised & expected)
    missed = sorted(expected - raised)
    extra = sorted(raised - expected)
    return caught, missed, extra


def run_regression(ws: Workspace, llm: bool = False) -> dict:
    """FR-R2: Э1 всегда; Э2 (--llm) — по золотым тестам echelon=Э2 (полуручной прогон)."""
    tests = load_tests(ws)
    results = []
    for test in tests:
        if test.echelon == "Э2" and not llm:
            results.append({"test_id": test.test_id, "skipped": "Э2 (запустите с --llm)"})
            continue
        if test.echelon == "Э2":
            results.append({"test_id": test.test_id, "skipped": "Э2: прогон через verify2 вручную (Д-10)"})
            continue
        caught, missed, extra = run_e1_test(ws, test)
        results.append(
            {"test_id": test.test_id, "поймано": caught, "пропущено": missed, "лишние": extra}
        )
    missed_total = [r["test_id"] for r in results if r.get("пропущено")]
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "всего": len(tests),
        "зелёная": not missed_total,
        "провалено": missed_total,
        "результаты": results,
    }
    guard.write_text(
        ws.regression / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def is_green(ws: Workspace) -> bool | None:
    """None — регрессия ещё не запускалась."""
    path = ws.regression / "report.json"
    if not path.exists():
        return None
    return bool(json.loads(path.read_text(encoding="utf-8")).get("зелёная"))
