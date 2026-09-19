"""Настройка: init — каркас рабочей области (NFR-1), `demo` — демо-библиотека и золотые тесты."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..paths import Workspace
from .common import colors, echo, secho


def init(demo: bool = False) -> Workspace:
    """Создать каркас рабочей области: config.yaml, .env.example, папки (NFR-1). Возвращает рабочую область."""
    ws = Workspace(Path.cwd())
    if not (ws.root / "config.yaml").exists():
        shutil.copyfile(Path(__file__).parent.parent / "data" / "config.example.yaml", ws.root / "config.yaml")
    for d in (ws.exports, ws.chapters, ws.logs, ws.templates, ws.regression / "golden"):
        d.mkdir(parents=True, exist_ok=True)
    env_example = ws.root / ".env.example"
    if not env_example.exists():
        env_example.write_text("GEMINI_API_KEY=\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    if demo:
        from importlib import resources

        demo_root = Path(str(resources.files("ugar").joinpath("data/демо")))
        if not (ws.root / "УГАР_Библиотека").exists():
            shutil.copytree(demo_root / "УГАР_Библиотека", ws.root / "УГАР_Библиотека")
        for f in (demo_root / "регрессия").glob("*.json"):
            target = ws.regression / "golden" / f.name
            if not target.exists():
                shutil.copyfile(f, target)
        secho(
            "Демо развёрнуто. Попробуйте: `ugar export` → `ugar compile 1` → `ugar status` → `ugar regress`.",
            fg=colors.GREEN,
        )
        echo("Ключи API не обязательны: без них каждый шаг подскажет ручной режим (NFR-3).")
        return ws
    secho("Рабочая область готова. Заполните config.yaml и .env (Д-9), положите УГАР_Библиотека/.", fg=colors.GREEN)
    echo("Хотите пощупать конвейер на примере — `ugar init --демо`. Диагностика: `ugar doctor`.")
    return ws
