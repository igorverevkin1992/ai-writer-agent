"""Раскладка рабочей области конвейера (NFR-4: артефакты такта — в chapters/N/)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    """Пути рабочей области. Корень — папка проекта автора (где лежит config.yaml)."""

    root: Path

    @property
    def library(self) -> Path:
        # Может быть переопределён конфигом; см. config.load_config().
        return self.root / "УГАР_Библиотека"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def chapters(self) -> Path:
        return self.root / "chapters"

    @property
    def corpus(self) -> Path:
        return self.root / "exports" / "corpus"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def regression(self) -> Path:
        return self.root / "regression"

    def chapter_dir(self, n: int) -> Path:
        return self.chapters / f"{n:03d}"

    def draft_path(self, n: int, k: int) -> Path:
        return self.chapter_dir(n) / f"draft_{k}.md"

    def window_path(self, n: int) -> Path:
        return self.chapter_dir(n) / "window.md"

    def status_path(self, n: int) -> Path:
        return self.chapter_dir(n) / "status.yaml"


def find_workspace(start: Path | None = None) -> Workspace:
    """Ищет config.yaml вверх от текущей папки; иначе корень = текущая папка."""
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / "config.yaml").exists():
            return Workspace(p)
    return Workspace(cur)
