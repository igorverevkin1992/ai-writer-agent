"""Git-операции над библиотекой канона (через subprocess, Д-8, сценарии Б/Г)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=off", "-C", str(repo), *args], capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",  # Windows: вывод git всегда UTF-8, не ANSI-страница
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def is_repo(repo: Path) -> bool:
    try:
        return _git(repo, "rev-parse", "--is-inside-work-tree", check=False) == "true"
    except FileNotFoundError:
        return False


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def prefix(repo: Path) -> str:
    """Путь папки внутри репозитория («УГАР_Библиотека/»); пусто, если папка — корень репозитория."""
    return _git(repo, "rev-parse", "--show-prefix", check=False)


def commit_all(repo: Path, message: str, author: str | None = None) -> str | None:
    """Атомарный коммит изменений ТОЛЬКО внутри папки библиотеки (5.1, FR-K2). Авторство — автор (Д-8).
    Возвращает SHA коммита; None — если коммитить было нечего."""
    _git(repo, "add", "-A", "--", ".")
    if not dirty(repo):
        return None
    args = ["commit", "-m", message]
    if author:
        args += ["--author", author]
    _git(repo, *args)
    return head(repo)


def check_norm_change_message(message: str) -> bool:
    """Сценарий Б: изменение норм — только со ссылкой Р-№ в сообщении (предупреждение)."""
    return bool(re.search(r"Р-\d+", message))


def find_chapter_commit(repo: Path, chapter: int) -> str | None:
    """Ищет коммит приёмки главы по шаблонному сообщению (FR-K2)."""
    out = _git(repo, "log", "--format=%H %s", check=False)
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if subject.startswith("Revert "):
            continue  # откат приёмки — не приёмка
        if re.match(rf"\[глава {chapter}\]", subject):
            return sha
    return None


def revert(repo: Path, commit: str) -> str:
    """Откат коммита приёмки; затрагивать можно только файлы библиотеки (иначе — отмена, ошибка)."""
    _git(repo, "revert", "--no-edit", "--no-commit", commit)
    touched = [p for p in _git(repo, "diff", "--cached", "--name-only", check=False).splitlines() if p]
    pfx = prefix(repo)
    outside = [p for p in touched if pfx and not p.startswith(pfx)]
    if outside:
        _git(repo, "revert", "--abort", check=False)
        raise RuntimeError(
            f"коммит {commit[:10]} затрагивает файлы вне библиотеки ({', '.join(outside[:5])}) — "
            "откат отменён; разберите его вручную в git."
        )
    _git(repo, "commit", "--no-edit", "-m", f'Revert "{_git(repo, "log", "-1", "--format=%s", commit, check=False)}"')
    return head(repo)


def has_identity(repo: Path) -> bool:
    """Есть ли у git настроенное авторство (иначе коммит сорвётся)."""
    return bool(_git(repo, "config", "user.email", check=False).strip())


def push(repo: Path, remote: str) -> None:
    """Отправка текущей ветки в удалённое место (NFR-6, `ugar backup --push`)."""
    _git(repo, "push", remote, "HEAD")


def remotes(repo: Path) -> list[str]:
    out = _git(repo, "remote", check=False)
    return [r for r in out.splitlines() if r.strip()]


def dirty(repo: Path) -> bool:
    """Есть ли незакоммиченные изменения в папке библиотеки (остальной репозиторий не учитывается)."""
    return bool(_git(repo, "status", "--porcelain", "--", ".", check=False))


def last_commit_age_days(repo: Path) -> float | None:
    out = _git(repo, "log", "-1", "--format=%ct", check=False)
    if not out:
        return None
    import time

    return (time.time() - int(out)) / 86400
