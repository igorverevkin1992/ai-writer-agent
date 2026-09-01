"""Git-операции над библиотекой канона (через subprocess, Д-8, сценарии Б/Г)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
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


def commit_all(repo: Path, message: str, author: str | None = None) -> str:
    """Атомарный коммит всех изменений (5.1). Авторство — автор (Д-8)."""
    _git(repo, "add", "-A")
    if not dirty(repo):
        return head(repo)  # нечего коммитить — не считаем ошибкой
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
        if re.search(rf"\[глава {chapter}\]", subject):
            return sha
    return None


def revert(repo: Path, commit: str) -> str:
    _git(repo, "revert", "--no-edit", commit)
    return head(repo)


def remotes(repo: Path) -> list[str]:
    out = _git(repo, "remote", check=False)
    return [r for r in out.splitlines() if r.strip()]


def dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain", check=False))


def last_commit_age_days(repo: Path) -> float | None:
    out = _git(repo, "log", "-1", "--format=%ct", check=False)
    if not out:
        return None
    import time

    return (time.time() - int(out)) / 86400
