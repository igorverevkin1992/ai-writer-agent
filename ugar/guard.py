"""Защита записи в канон (FR-K3, критерий приёмки 3).

Ни один компонент не пишет в `УГАР_Библиотека/`, кроме канониста после
подтверждения автора. Все записи файлов в конвейере идут через write_text();
запись внутрь библиотеки возможна только внутри canon_write_session().
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path

_state = threading.local()


class CanonWriteError(PermissionError):
    pass


def set_library_dir(path: Path) -> None:
    _state.library = path.resolve()


def _library() -> Path | None:
    return getattr(_state, "library", None)


def _allowed() -> bool:
    return bool(getattr(_state, "canon_session", False))


@contextlib.contextmanager
def canon_write_session():
    """Открывается ТОЛЬКО канонистом после явного подтверждения автора (FR-K2)."""
    _state.canon_session = True
    try:
        yield
    finally:
        _state.canon_session = False


def check_write_allowed(path: Path) -> None:
    lib = _library()
    if lib is None:
        return
    resolved = Path(path).resolve()
    if resolved == lib or lib in resolved.parents:
        if not _allowed():
            raise CanonWriteError(
                f"Запись в библиотеку канона запрещена: {path}. "
                "В УГАР_Библиотека/ пишет только `ugar canonize` после подтверждения автора (FR-K3)."
            )


def write_text(path: Path, text: str) -> None:
    """Единая точка записи текстовых файлов конвейера (UTF-8, NFR-8)."""
    check_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    check_write_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
