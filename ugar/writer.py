"""Writer-adapter: вызовы Писателя (FR-W1, FR-W2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources

from jinja2 import Environment, StrictUndefined

from . import adapters, guard
from .config import Config
from .paths import Workspace
from .schemas import Edit


def _save_draft(ws: Workspace, chapter: int, k: int, text: str, cfg: Config, mode: str) -> None:
    guard.write_text(ws.draft_path(chapter, k), text)
    meta = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": cfg.writer.model,
        "params": cfg.writer.params,  # Д-6: параметры пинуются конфигом
        "mode": mode,
    }
    guard.write_text(
        ws.chapter_dir(chapter) / f"draft_{k}.meta.json",
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    )


def write_chapter(ws: Workspace, cfg: Config, chapter: int, k: int) -> None:
    """FR-W1: отправляет окно, сохраняет ответ как draft_k.md. Контекст — только окно."""
    window = ws.window_path(chapter).read_text(encoding="utf-8")
    text = adapters.call_gemini(window, cfg.writer, cfg.api, ws.logs, chapter=chapter)
    _save_draft(ws, chapter, k, text, cfg, mode="генерация")


def edit_prompt(ws: Workspace, chapter: int, draft_k: int, edits: list[Edit]) -> str:
    """FR-W2: принятый черновик + правки + инструкция «внести точно» (шаблон в templates/)."""
    override = ws.templates / "правки.md.j2"
    if override.exists():
        tpl = override.read_text(encoding="utf-8")
    else:
        tpl = resources.files("ugar").joinpath("templates/правки.md.j2").read_text(encoding="utf-8")
    draft = ws.draft_path(chapter, draft_k).read_text(encoding="utf-8")
    env = Environment(undefined=StrictUndefined)
    return env.from_string(tpl).render(edits=edits, draft=draft)


def apply_edits(ws: Workspace, cfg: Config, chapter: int, draft_k: int, edits: list[Edit]) -> int:
    """Вызов Писателя в режиме правок; возвращает номер нового черновика."""
    prompt = edit_prompt(ws, chapter, draft_k, edits)
    guard.write_text(ws.chapter_dir(chapter) / "apply_edits_prompt.md", prompt)
    text = adapters.call_gemini(prompt, cfg.writer, cfg.api, ws.logs, chapter=chapter)
    new_k = draft_k + 1
    _save_draft(ws, chapter, new_k, text, cfg, mode="правки")
    return new_k
