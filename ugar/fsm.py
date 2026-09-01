"""Конечный автомат главы (модель данных 5.4). Состояние — chapters/N/status.yaml (Д-5)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import guard
from .paths import Workspace

STATES = [
    "не-начато",
    "собрано",
    "сгенерировано",
    "верифицировано-1",
    "верифицировано-2",
    "на-приёмке",
    "правки",
    "дифф-контроль",
    "принято",
    "зафиксировано",
]

TRANSITIONS: dict[str, set[str]] = {
    "не-начато": {"собрано"},
    "собрано": {"сгенерировано", "собрано"},
    "сгенерировано": {"верифицировано-1", "сгенерировано"},
    # брак метрик → назад в «сгенерировано» (авто-повтор, §5.4)
    "верифицировано-1": {"верифицировано-2", "сгенерировано"},
    "верифицировано-2": {"на-приёмке"},
    "на-приёмке": {"правки"},
    "правки": {"дифф-контроль"},
    # самовольные изменения → назад в «правки» (§5.4)
    "дифф-контроль": {"принято", "правки"},
    "принято": {"зафиксировано"},
    "зафиксировано": set(),  # терминальное; изменения только через git-revert
}


class TransitionError(RuntimeError):
    pass


class ChapterState:
    def __init__(self, ws: Workspace, chapter: int):
        self.ws = ws
        self.chapter = chapter
        self.path: Path = ws.status_path(chapter)
        if self.path.exists():
            self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        else:
            self.data = {"глава": chapter, "состояние": "не-начато", "черновик": 0, "авто_повторов": 0, "итераций_правок": 0, "история": []}

    @property
    def state(self) -> str:
        return self.data["состояние"]

    @property
    def draft(self) -> int:
        return int(self.data.get("черновик", 0))

    def _save(self) -> None:
        guard.write_text(self.path, yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False))

    def transition(self, to: str, cmd: str = "") -> None:
        if to not in STATES:
            raise TransitionError(f"Неизвестное состояние: {to}")
        if to not in TRANSITIONS.get(self.state, set()):
            raise TransitionError(
                f"Глава {self.chapter}: переход «{self.state}» → «{to}» недопустим (§5.4)."
            )
        self._move(to, cmd)

    def rollback(self, to: str, cmd: str = "rollback") -> None:
        """Откат в любое ПРЕДЫДУЩЕЕ состояние (сценарий Г). «зафиксировано» — только git-revert."""
        if self.state == "зафиксировано":
            raise TransitionError(
                "Состояние «зафиксировано» терминально: откат только git-revert'ом коммита приёмки (`ugar rollback N --to принято` выполнит revert)."
            )
        if to not in STATES:
            raise TransitionError(f"Неизвестное состояние: {to}")
        if STATES.index(to) >= STATES.index(self.state):
            raise TransitionError(
                f"Откат возможен только назад: «{self.state}» → «{to}» не является откатом."
            )
        self._move(to, cmd)

    def _move(self, to: str, cmd: str) -> None:
        self.data["история"].append(
            {"из": self.state, "в": to, "время": datetime.now(timezone.utc).isoformat(), "команда": cmd}
        )
        self.data["состояние"] = to
        self._save()

    def set_draft(self, k: int) -> None:
        self.data["черновик"] = k
        self._save()

    def bump_retries(self) -> int:
        self.data["авто_повторов"] = int(self.data.get("авто_повторов", 0)) + 1
        self._save()
        return self.data["авто_повторов"]

    def bump_edit_iterations(self) -> int:
        self.data["итераций_правок"] = int(self.data.get("итераций_правок", 0)) + 1
        self._save()
        return self.data["итераций_правок"]

    def require(self, *states: str) -> None:
        if self.state not in states:
            raise TransitionError(
                f"Глава {self.chapter} в состоянии «{self.state}», команда требует: {', '.join(states)}."
            )


def all_states(ws: Workspace) -> list[ChapterState]:
    result = []
    if ws.chapters.exists():
        for d in sorted(ws.chapters.iterdir()):
            if d.is_dir() and d.name.isdigit():
                result.append(ChapterState(ws, int(d.name)))
    return result
