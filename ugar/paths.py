"""Раскладка рабочей области конвейера (NFR-4: артефакты такта — в chapters/N/).

Тома (аудит 2, п. 27): рабочая область ведёт ОДИН текущий том (`config.yaml: volume`).
Главы тома 1 лежат в `chapters/001` (как и раньше — без миграции), главы тома N ≥ 2 —
в `chapters/ТN/001`. Все пути глав берут том из `Workspace.volume`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    """Пути рабочей области. Корень — папка проекта автора (где лежит config.yaml).
    `volume` — текущий том (из config.yaml, выставляется в `cli._ctx()`); по умолчанию 1."""

    root: Path
    volume: int = 1

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

    @property
    def manuscript(self) -> Path:
        return self.root / "manuscript"

    @property
    def snapshots(self) -> Path:
        return self.root / "snapshots"

    def for_volume(self, volume: int) -> "Workspace":
        """Та же рабочая область, но с другим текущим томом (`ugar volume close N`, снапшот тома)."""
        return dataclasses.replace(self, volume=int(volume))

    def chapters_root(self, volume: int | None = None) -> Path:
        """Папка глав тома: том 1 — `chapters/` (совместимость), том N ≥ 2 — `chapters/ТN/`."""
        v = self.volume if volume is None else int(volume)
        return self.chapters if v == 1 else self.chapters / f"Т{v}"

    def chapter_dirs(self, volume: int | None = None) -> list[tuple[int, Path]]:
        """Папки глав текущего (или указанного) тома по возрастанию номера: [(N, путь)]."""
        root = self.chapters_root(volume)
        if not root.exists():
            return []
        out = []
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name.isdigit():
                out.append((int(d.name), d))
        return out

    def chapter_dir(self, n: int, volume: int | None = None) -> Path:
        return self.chapters_root(volume) / f"{n:03d}"

    def chapter_rel(self, n: int) -> str:
        """Относительный путь папки главы для сообщений: `chapters/005` или `chapters/Т2/005`."""
        return self.chapter_dir(n).relative_to(self.root).as_posix()

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
