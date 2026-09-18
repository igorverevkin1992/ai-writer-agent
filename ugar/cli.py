"""CLI конвейера «УГАР» (интерфейсы из реестра модулей 4.2; язык — русский, NFR-2).

Каждый шаг такта исполним отдельной командой (FR-O2): отказ любого компонента
не блокирует такт — артефакты человекочитаемы, ручной режим всегда возможен (NFR-3).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import (
    adapters,
    apilog,
    backup as backup_mod,
    cancel,
    canonchange,
    canonist,
    compiler,
    dashboard as dashboard_mod,
    exporter,
    gitops,
    guard,
    regression as regression_mod,
    review as review_mod,
    timing,
    verifier1,
    verifier2,
    volume as volume_mod,
    writer,
)
from .config import Config, library_dir, load_config, set_volume
from .fsm import STATES, ChapterState, TransitionError, all_states
from .mdparse import MarkupError
from .paths import Workspace, find_workspace
from .schemas import GoldenTest

app = typer.Typer(
    name="ugar",
    help="КОНВЕЙЕР УГАР — производственный такт главы (ТЗ v1.0).",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def version_string() -> str:
    """Версия конвейера: из метаданных установленного пакета, иначе из ugar/__init__.py."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("ugar-pipeline")
    except PackageNotFoundError:
        from . import __version__

        return __version__


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ugar {version_string()}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", "-V", help="Версия конвейера.", callback=_version_callback, is_eager=True),
) -> None:
    """КОНВЕЙЕР УГАР — производственный такт главы (ТЗ v1.0)."""


def _ctx() -> tuple[Workspace, Config, Path]:
    """Рабочая область ТЕКУЩЕГО тома (`config.yaml: volume`; аудит 2, п. 27): пути глав, выгрузки,
    документы канона и журнал API привязаны к нему."""
    ws = find_workspace()
    cfg = load_config(ws)
    ws = ws.for_volume(cfg.volume)
    lib = library_dir(ws, cfg)
    guard.set_library_dir(lib)
    apilog.current_volume = ws.volume
    return ws, cfg, lib


def _fail(message: str) -> None:
    typer.secho(f"ОШИБКА: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _manual(e: adapters.ManualModeNeeded) -> None:
    typer.secho(f"⚠ {e.reason}", fg=typer.colors.YELLOW)
    typer.echo(f"Ручной режим (NFR-3): {e.hint}")
    raise typer.Exit(code=2)


def _opt(value, default):
    """Прямой вызов команды из кода (панель, `run`) без аргумента оставляет typer.OptionInfo —
    он истинен; такие значения считаем неуказанными."""
    return default if isinstance(value, typer.models.OptionInfo) else value


_NOT_A_JOB = {"cmd_panel"}


def _friendly(fn):
    """Ожидаемые ошибки (нет файла, структура MD, недопустимый переход FSM) —
    читаемое сообщение вместо трейсбека. UGAR_DEBUG=1 — полный трейсбек (для разбора
    программных ошибок, 2.11).

    Внешняя команда — одна задача для учёта времени такта (`timing.job`): переходы FSM внутри
    неё помечаются её идентификатором, интервалы между ними считаются машинными; вложенные
    команды (`run` → `write` → …) наследуют задачу. Остановка автором (`cancel.Cancelled`) —
    сообщение без трейсбека, код выхода 2 (как ручной режим: глава на последнем завершённом шаге)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        outermost = timing.current_job is None
        if outermost:
            cancel.clear()  # запрос отмены прошлой задачи не должен останавливать новую
        # сервер панели живёт часами — сам он не задача: задачи заводят команды, которые он вызывает
        job_ctx = contextlib.nullcontext() if fn.__name__ in _NOT_A_JOB else timing.job(fn.__name__.removeprefix("cmd_"))
        with job_ctx:
            try:
                return fn(*args, **kwargs)
            except (typer.Exit, typer.Abort):
                raise  # собственные коды выхода — не ошибка
            except adapters.ManualModeNeeded as e:
                if os.environ.get("UGAR_DEBUG") == "1":
                    raise
                _manual(e)
            except cancel.Cancelled as e:
                if not outermost:
                    raise  # до внешней команды: она печатает и завершает
                typer.secho(f"⏹ {e}", fg=typer.colors.YELLOW)
                raise typer.Exit(code=2)
            except (FileNotFoundError, MarkupError, TransitionError, RuntimeError, ValueError) as e:
                if os.environ.get("UGAR_DEBUG") == "1":
                    raise
                _fail(str(e))

    return wrapper


# ------------------------------------------------------------------ этап 1


@app.command("export", rich_help_panel="Такт главы")
@_friendly
def cmd_export() -> None:
    """Перегенерировать все выгрузки из MD-библиотеки (FR-X1…FR-X3)."""
    ws, cfg, lib = _ctx()
    try:
        hashes = exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
    except MarkupError as e:
        _fail(f"структура MD расходится с соглашениями Д-1 → {e}")
    typer.secho(f"Выгрузки обновлены (том {ws.volume}): {len(hashes)} файлов в {ws.exports}/", fg=typer.colors.GREEN)


@app.command("compile", rich_help_panel="Такт главы")
@_friendly
def cmd_compile(chapter: int) -> None:
    """Собрать окно контекста главы N (FR-C1…FR-C6). Экспорт выполняется автоматически (риск R-5)."""
    ws, cfg, lib = _ctx()
    try:
        exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
        path, breakdown = compiler.compile_window(ws, lib, chapter, cfg.window_soft_limit_chars)
    except MarkupError as e:
        _fail(str(e))
    except FileNotFoundError as e:
        _fail(str(e))
    size = sum(breakdown.values())
    st = ChapterState(ws, chapter)
    if st.state == "не-начато":
        st.transition("собрано", "compile")
    elif st.state == "собрано":
        st.transition("собрано", "compile (пересборка)")
    else:
        typer.secho(
            f"⚠ Глава в состоянии «{st.state}»: окно пересобрано, но текущий черновик "
            f"генерировался по старому окну — при необходимости `ugar rollback {chapter} --to собрано`.",
            fg=typer.colors.YELLOW,
        )
    typer.secho(f"Окно собрано: {path} (~{size} символов)", fg=typer.colors.GREEN)
    if breakdown.get("драматургия", 0) and "в канон ещё не внесён" in path.read_text(encoding="utf-8"):
        typer.secho(
            f"⚠ Каркас драматургии главы {chapter} в канон не внесён (Р-020): `ugar circles` → "
            "`ugar circles --в-канон`, затем пересоберите окно.",
            fg=typer.colors.YELLOW,
        )
    if (ws.chapter_dir(chapter) / "window_size_флаг.md").exists() and size > cfg.window_soft_limit_chars:
        typer.secho(
            f"⚠ Превышен мягкий лимит окна {cfg.window_soft_limit_chars} символов (Д-12) — "
            f"раскладка в chapters/{chapter:03d}/window_size_флаг.md",
            fg=typer.colors.YELLOW,
        )


@app.command("write", rich_help_panel="Такт главы")
@_friendly
def cmd_write(
    chapter: int,
    manual: bool = typer.Option(
        False, "--manual", help="Зарегистрировать черновик, сохранённый вручную как draft_{k+1}.md (NFR-3)."
    ),
    variants: int = typer.Option(
        1, "--варианты", "--variants", min=1, max=4,
        help="A/B: столько вызовов Писателя по одному окну → draft_k.md, draft_k.alt1.md …; метрики Э1 рядом (варианты.json).",
    ),
    choose: str | None = typer.Option(
        None, "--выбрать", "--choose", help="Сделать вариант (alt1, alt0 — прежний основной) текущим draft_k.md; состояние не меняется.",
    ),
) -> None:
    """Отправить окно Писателю, сохранить draft_k.md (FR-W1). `--варианты 2` — A/B, `--выбрать alt1` — выбор варианта."""
    ws, cfg, lib = _ctx()
    variants = int(_opt(variants, 1))
    choose = _opt(choose, None)
    manual = _opt(manual, False)
    st = ChapterState(ws, chapter)
    if choose:
        st.require("сгенерировано")
        writer.choose_variant(ws, chapter, st.draft, choose)
        typer.secho(f"Вариант «{choose}» → draft_{st.draft}.md (прежний основной — alt0). Далее: `ugar verify1 {chapter}`.",
                    fg=typer.colors.GREEN)
        return
    st.require("собрано", "сгенерировано")
    k = st.draft + 1
    labels = writer.variant_labels(variants)
    if manual:
        missing = [writer.variant_path(ws, chapter, k, lb).name for lb in labels if not writer.variant_path(ws, chapter, k, lb).exists()]
        if missing:
            _fail(
                f"нет файла chapters/{chapter:03d}/{missing[0]} — скопируйте окно в чат модели, "
                f"сохраните ответ этим файлом и повторите (ручной режим)."
            )
    elif variants > 1:
        try:
            writer.write_variants(ws, cfg, chapter, k, variants)
        except adapters.ManualModeNeeded as e:
            typer.echo(
                f"Окно для всех вариантов одно: chapters/{chapter:03d}/window.md — прогоните его {variants} раз(а), "
                f"сохраните ответы как {', '.join(writer.variant_path(ws, chapter, k, lb).name for lb in labels)} "
                f"и выполните `ugar write {chapter} --manual --варианты {variants}`."
            )
            _manual(e)
    else:
        try:
            writer.write_chapter(ws, cfg, chapter, k)
        except adapters.ManualModeNeeded as e:
            _manual(e)
    st.set_draft(k)
    st.reset_retries()  # свежая генерация — бюджет авто-повторов §5.4 заново
    st.transition("сгенерировано", "write" + (" (manual)" if manual else "") + (f" (варианты: {variants})" if variants > 1 else ""))
    typer.secho(f"Черновик {'принят' if manual else 'получен'}: {ws.draft_path(chapter, k)}", fg=typer.colors.GREEN)
    if variants > 1:
        summary = verifier1.variants_summary(ws, chapter, k, labels)
        _print_variants(summary)
        typer.echo(f"Основной — draft_{k}.md; выбрать другой: `ugar write {chapter} --выбрать alt1`.")


def _print_variants(summary: dict) -> None:
    """Таблица метрик Э1 по вариантам: строки — проверки, столбцы — варианты."""
    rows = summary.get("варианты", [])
    if not rows:
        return
    typer.echo("Метрики Э1 по вариантам (chapters/N/варианты.json):")
    typer.echo(f"  {'проверка':<28}" + "".join(f"{r['вариант']:>16}" for r in rows))
    typer.echo(f"  {'слов':<28}" + "".join(f"{r['слов']:>16}" for r in rows))
    typer.echo(f"  {'брак / флагов':<28}" + "".join(f"{str(r['брак']) + ' / ' + str(r['флагов']):>16}" for r in rows))
    ids: list[str] = []
    for r in rows:
        ids += [i for i in r["метрики"] if i not in ids]
    for check_id in ids:
        cells = []
        for r in rows:
            m = r["метрики"].get(check_id)
            cells.append(f"{(m['actual'] + ' ' + m['status']) if m else '—':>16}")
        typer.echo(f"  {check_id[:28]:<28}" + "".join(cells))


def _print_verdict(verdict) -> None:
    for c in verdict.checks:
        color = {"PASS": typer.colors.GREEN, "FLAG": typer.colors.YELLOW, "BRAK": typer.colors.RED}[c.status]
        typer.secho(f"  [{c.status}] {c.check_id}: {c.actual} (порог: {c.threshold})", fg=color)


@app.command("verify1", rich_help_panel="Такт главы")
@_friendly
def cmd_verify1(chapter: int) -> None:
    """Формальные проверки Э1 (FR-V1.*). Брак метрик → авто-повтор генерации (≤2, §5.4)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("сгенерировано")
    while True:
        verdict = verifier1.run_verify1(ws, chapter, st.draft)
        typer.echo(f"Вердикт Э1 (глава {chapter}, черновик {st.draft}):")
        _print_verdict(verdict)
        if not verdict.has_brak:
            st.transition("верифицировано-1", "verify1")
            typer.secho("Э1 пройден.", fg=typer.colors.GREEN)
            return
        retries = st.bump_retries()
        if retries > cfg.auto_retries_verify1:
            typer.secho(
                f"БРАК метрик после {cfg.auto_retries_verify1} авто-повторов — стоп, вердикт автору "
                f"(chapters/{chapter:03d}/verdict.json).",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        typer.secho(f"БРАК метрик — авто-повтор генерации №{retries} (§5.4)…", fg=typer.colors.YELLOW)
        cancel.check(f"авто-повтор Э1 №{retries}")
        k = st.draft + 1
        try:
            writer.write_chapter(ws, cfg, chapter, k)
        except adapters.ManualModeNeeded as e:
            _manual(e)
        st.set_draft(k)


@app.command("verify2", rich_help_panel="Такт главы")
@_friendly
def cmd_verify2(
    chapter: int,
    manual: bool = typer.Option(False, "--manual", help="Принять flags.json, заполненный вручную (NFR-3)."),
    taste: bool = typer.Option(False, "--вкус", "--taste", help="Дополнительно: советы по вкусу автора (02 §6.1) — не блокируют приёмку."),
    again: bool = typer.Option(
        False, "--повторно", "--после-правок", "--again",
        help="Повторный Э2 по текущему черновику после правок (из «правки»/«дифф-контроль»): совещательно — "
             "flags_повторно.json и раздел в review.md; FSM, flags.json и решения не меняются.",
    ),
) -> None:
    """Смысловые проверки Э2 (FR-V2.*). `--повторно` — второй прогон после правок (advisory)."""
    ws, cfg, lib = _ctx()
    manual, taste, again = _opt(manual, False), _opt(taste, False), _opt(again, False)
    st = ChapterState(ws, chapter)
    if again:
        _verify2_again(ws, cfg, st, manual)
        return
    st.require("верифицировано-1")
    if manual:
        if not (ws.chapter_dir(chapter) / "flags.json").exists():
            _fail(
                f"нет файла chapters/{chapter:03d}/flags.json — сохраните в него JSON-ответ модели "
                f"(промпт: verify2_prompt.md), затем повторите `ugar verify2 {chapter} --manual`."
            )
        flags = verifier2.load_flags(ws, chapter)
        typer.echo(f"Принят ручной flags.json: {len(flags)} флагов.")
    else:
        try:
            flags = verifier2.run_verify2(ws, cfg, chapter, st.draft)
        except adapters.ManualModeNeeded as e:
            typer.echo(
                f"Промпт сохранён: chapters/{chapter:03d}/verify2_prompt.md — прогоните вручную, "
                f"сохраните JSON в chapters/{chapter:03d}/flags.json и выполните `ugar verify2 {chapter} --manual`."
            )
            _manual(e)
        except ValueError as e:
            _fail(str(e))
    st.transition("верифицировано-2", "verify2")
    sam = sum(1 for f in flags if f.kind == "samovolka")
    typer.secho(f"Э2 завершён: {len(flags)} флагов, из них самоволок: {sam}.", fg=typer.colors.GREEN)
    if taste:
        try:
            advice = verifier2.run_taste(ws, cfg, chapter, st.draft)
            typer.echo(f"Вкус (совещательно, 02 §6.1): замечаний {len(advice)} → chapters/{chapter:03d}/taste.json")
        except adapters.ManualModeNeeded:
            typer.echo(f"Промпт вкуса сохранён: chapters/{chapter:03d}/taste_prompt.md (ответ — в taste.json).")
        except ValueError as e:
            typer.secho(f"⚠ Вкус: {e}", fg=typer.colors.YELLOW)


def _verify2_again(ws: Workspace, cfg: Config, st: ChapterState, manual: bool) -> None:
    """Повторный Э2 после правок (аудит 2, п. 24а): по текущему черновику, без смены состояния."""
    chapter = st.chapter
    st.require("правки", "дифф-контроль")
    if manual:
        if not (ws.chapter_dir(chapter) / verifier2.AGAIN_FLAGS).exists():
            _fail(
                f"нет файла chapters/{chapter:03d}/{verifier2.AGAIN_FLAGS} — сохраните в него JSON-ответ модели "
                f"(промпт: {verifier2.AGAIN_PROMPT}), затем повторите `ugar verify2 {chapter} --повторно --manual`."
            )
        draft_k, flags = verifier2.load_flags_again(ws, chapter)
        if draft_k is None:
            verifier2.save_flags_again(ws, chapter, flags, st.draft)
        typer.echo(f"Принят ручной {verifier2.AGAIN_FLAGS}: {len(flags)} флагов.")
    else:
        try:
            flags = verifier2.run_verify2_again(ws, cfg, chapter, st.draft)
        except adapters.ManualModeNeeded as e:
            typer.echo(
                f"Промпт сохранён: chapters/{chapter:03d}/{verifier2.AGAIN_PROMPT} — прогоните вручную, "
                f"сохраните JSON в chapters/{chapter:03d}/{verifier2.AGAIN_FLAGS} и выполните "
                f"`ugar verify2 {chapter} --повторно --manual`."
            )
            _manual(e)
    review_mod.append_second_pass(ws, chapter, st.draft, flags)
    sam = sum(1 for f in flags if f.kind == "samovolka")
    typer.secho(
        f"Повторный Э2 (черновик {st.draft}, совещательно): {len(flags)} флагов, из них самоволок: {sam} → "
        f"chapters/{chapter:03d}/{verifier2.AGAIN_FLAGS}; состояние «{st.state}» не изменено.",
        fg=typer.colors.GREEN,
    )
    for f in flags[:12]:
        typer.echo(f"  - [{f.kind}/{f.severity}] {f.flag_id} · {f.type}: {f.rule}")


@app.command("review", rich_help_panel="Такт главы")
@_friendly
def cmd_review(chapter: int) -> None:
    """Пакет приёмки автора: review.md + edits.md + resolutions.json (FR-E1)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("верифицировано-2")
    path = review_mod.build_review_pack(ws, chapter, st.draft)
    from . import htmlreview

    html_path = htmlreview.build_review_html(ws, chapter, st.draft)
    st.data["база_приёмки"] = st.draft  # FR-E3: каждый цикл правок стартует от текста, принятого на приёмке
    st.transition("на-приёмке", "review")
    typer.secho(f"Пакет приёмки: {path}", fg=typer.colors.GREEN)
    typer.secho(f"Чтение с флагами (браузер): {html_path}", fg=typer.colors.GREEN)
    typer.echo(
        f"Дальше: правки — в edits.md (`ugar edits {chapter}` — предпросмотр); "
        f"решения по самоволкам — `ugar resolve {chapter}`; затем `ugar apply-edits {chapter}`."
    )


@app.command("apply-edits", rich_help_panel="Такт главы")
@_friendly
def cmd_apply_edits(
    chapter: int,
    manual: bool = typer.Option(False, "--manual", help="Черновик с правками сохранён вручную как draft_{k+1}.md."),
) -> None:
    """Внесение правок: дословные БЫЛО/СТАЛО — кодом (Р-023), свободные указания — Писателем (FR-W2, FR-E3)."""
    ws, cfg, lib = _ctx()
    manual = _opt(manual, False)
    st = ChapterState(ws, chapter)
    st.require("на-приёмке", "дифф-контроль")
    edits = review_mod.parse_edits_md(ws, chapter)
    # база правок — черновик приёмки (FR-E3): повторный цикл не наследует самоволия прошлой итерации
    base = int(st.data.get("база_приёмки", st.draft))
    new_k = st.draft + 1
    base_path = ws.draft_path(chapter, base)
    local = None
    if not manual and base_path.exists():
        local = writer.apply_edits_text(base_path.read_text(encoding="utf-8"), edits)
    over = st.data.get("итераций_правок", 0) >= cfg.edit_cycle_max_iterations
    if not manual and over and (local is None or local.needs_model):
        _fail(
            f"итераций правок уже {st.data['итераций_правок']} (лимит FR-E3) — внесите правки вручную: "
            f"сохраните исправленный текст как draft_{st.draft + 1}.md, выполните "
            f"`ugar apply-edits {chapter} --manual`, затем `ugar diff-check {chapter} --авторская-правка`."
        )
    st.data["база_правок"] = base
    n_local = n_model = 0
    if manual:
        # завершение сорвавшейся автоматической итерации либо ручная правка автора —
        # бюджет итераций FR-E3 (для циклов Писателя) не расходуется
        if not ws.draft_path(chapter, new_k).exists():
            _fail(f"нет файла {ws.draft_path(chapter, new_k)} (ручной режим).")
    elif not edits:
        # правок нет — черновик приёмки переходит дальше без вызова Писателя
        shutil.copyfile(base_path, ws.draft_path(chapter, new_k))
    elif local is None:
        _fail(f"нет базового черновика {base_path} (FR-E3: правки идут от черновика приёмки).")
    elif not local.needs_model:
        # Р-023: все пары найдены дословно ровно один раз — модель не нужна, бюджет итераций не расходуется
        new_k, local = writer.apply_edits_locally(ws, cfg, chapter, base, edits, new_k=new_k)
        n_local = len(local.applied)
    else:
        n_local, n_model = len(local.applied), len(local.remaining)
        for e in local.remaining:
            typer.echo(f"  Писателю: правка {e.seq} — {local.reasons.get(e.seq, '')}")
        try:
            new_k = writer.apply_edits(
                ws, cfg, chapter, base, local.remaining, new_k=new_k,
                base_text=local.text, applied_locally=[e.seq for e in local.applied],
            )
        except adapters.ManualModeNeeded as e:
            typer.echo(
                f"Правок кодом: {n_local} (уже в тексте промпта), Писателю: {n_model}. "
                f"Промпт правок сохранён: chapters/{chapter:03d}/apply_edits_prompt.md — прогоните вручную, "
                f"сохраните ответ как draft_{st.draft + 1}.md и выполните `ugar apply-edits {chapter} --manual`."
            )
            _manual(e)
        st.bump_edit_iterations()  # итерация Писателя состоялась
    st.set_draft(new_k)
    st.transition("правки", "apply-edits" + (" (manual)" if manual else "") + (" (код)" if n_local and not n_model else ""))
    how = f"применено кодом {n_local}, Писателю {n_model}" if not manual else "ручной режим"
    typer.secho(f"Правки внесены ({len(edits)} шт.: {how}) → draft_{new_k}.md. Далее: `ugar diff-check {chapter}`.",
                fg=typer.colors.GREEN)


@app.command("diff-check", rich_help_panel="Такт главы")
@_friendly
def cmd_diff_check(
    chapter: int,
    author_fix: bool = typer.Option(
        False, "--авторская-правка", "--author-fix", help="Текущий черновик правил сам автор — расхождения не самоволия."
    ),
    fragments: list[str] | None = typer.Option(
        None, "--фрагмент", "--fragment",
        help="С --авторская-правка: снять только эти самоволия (номер в списке или подстрока текста); можно несколько раз.",
    ),
) -> None:
    """Дифф-контроль до/после правок (FR-V1.10, FR-E3)."""
    ws, cfg, lib = _ctx()
    if not isinstance(fragments, list):  # прямой вызов из панели без аргумента (typer.OptionInfo)
        fragments = []
    st = ChapterState(ws, chapter)
    st.require("правки", "дифф-контроль")  # повторный прогон/подтверждение разрешён
    edits = review_mod.load_edits(ws, chapter)
    base = int(st.data.get("база_правок", st.draft - 1))
    report = verifier1.diff_check(ws, chapter, base, st.draft, edits)
    if author_fix and report.unauthorized:
        # 2.5: снятые самоволия фиксируются в diff_report.json; с --фрагмент — только перечисленные
        waived, missing = verifier1.waive_unauthorized(ws, chapter, report, fragments)
        typer.secho(f"Авторская правка: снято самоволий {len(waived)}.", fg=typer.colors.YELLOW)
        if missing:
            typer.secho(f"⚠ Не найдены среди самоволий: {missing}", fg=typer.colors.YELLOW)
    elif fragments and not author_fix:
        typer.secho("⚠ --фрагмент действует только вместе с --авторская-правка.", fg=typer.colors.YELLOW)
    st.transition("дифф-контроль", "diff-check")
    typer.echo(f"Внесено правок: {report.applied_share:.0%}; не внесено: {report.not_applied or '—'}")
    if report.unverifiable:
        typer.secho(
            f"Свободные указания {report.unverifiable}: механически не проверяются — "
            "оцените их результат глазами (приёмку не блокируют).",
            fg=typer.colors.YELLOW,
        )
    if report.unauthorized:
        typer.secho(f"Самовольные изменения ({len(report.unauthorized)}):", fg=typer.colors.RED)
        for u in report.unauthorized[:10]:
            typer.echo(f"  > {u[:200]}")
        if report.unverifiable:
            typer.echo(
                "Часть изменений может быть следствием свободных указаний — если это так, "
                f"подтвердите `ugar diff-check {chapter} --авторская-правка`."
            )
        typer.echo(f"Цикл повторяется: поправьте edits.md и выполните `ugar apply-edits {chapter}` (≤{cfg.edit_cycle_max_iterations} итераций).")
    elif report.not_applied:
        typer.secho("Часть правок не внесена — повторите цикл.", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"Дифф-контроль чист. Далее: `ugar accept {chapter}`.", fg=typer.colors.GREEN)


@app.command("accept", rich_help_panel="Такт главы")
@_friendly
def cmd_accept(chapter: int, yes: bool = typer.Option(False, "--yes", "-y", help="Подтверждение без вопроса.")) -> None:
    """Приёмка главы автором (FR-E4): только из «дифф-контроль: чисто», с явным подтверждением."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("дифф-контроль")
    report_path = ws.chapter_dir(chapter) / "diff_report.json"
    data = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    if data.get("not_applied") or data.get("unauthorized"):
        _fail("дифф-контроль не чист — приёмка недоступна (FR-E4).")
    unresolved = review_mod.unresolved_samovolki(ws, chapter)
    if unresolved:
        _fail(f"не решены самоволки: {', '.join(unresolved)} (resolutions.json).")
    green = regression_mod.is_green(ws)
    if green is False:
        typer.secho("⚠ Регрессия КРАСНАЯ (FR-R3) — смена конфигурации запрещена, приёмка под вашу ответственность.", fg=typer.colors.YELLOW)
    if not yes and not typer.confirm(f"Принять главу {chapter}? (y)"):
        raise typer.Exit()
    st.transition("принято", "accept")
    typer.secho(f"Глава {chapter} принята. Далее: `ugar canonize {chapter}`.", fg=typer.colors.GREEN)


@app.command("canonize", rich_help_panel="Такт главы")
@_friendly
def cmd_canonize(
    chapter: int,
    apply: bool = typer.Option(False, "--apply", help="Применить подписанный пакет (правки MD + export + git-коммит)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
    redo: bool = typer.Option(False, "--заново", "--redo", help="Пересобрать пакет, даже если автор его уже правил (правки пропадут)."),
) -> None:
    """Канонист: пакет записей в канон (FR-K1); применение — только после подписи (FR-K2)."""
    ws, cfg, lib = _ctx()
    if not isinstance(redo, bool):  # прямой вызов из панели без аргумента (typer.OptionInfo)
        redo = False
    st = ChapterState(ws, chapter)
    st.require("принято")
    batch_path = ws.chapter_dir(chapter) / "canon_batch.md"
    if not apply:
        if batch_path.exists() and not redo:
            # 2.11: отредактированный автором пакет не перезаписывается (и вызов LLM не тратится)
            current = _sha256(batch_path)
            if st.data.get("пакет_хэш") != current:
                _fail(
                    f"пакет chapters/{chapter:03d}/canon_batch.md уже правился автором — "
                    f"примените его (`ugar canonize {chapter} --apply`) или пересоберите явно "
                    f"(`ugar canonize {chapter} --заново`, правки пропадут)."
                )
        try:
            path = canonist.build_batch(ws, cfg, chapter, st.draft)
        except RuntimeError as e:
            _fail(str(e))
        st.data["пакет_хэш"] = _sha256(path)
        st._save()
        typer.secho(f"Пакет на подпись: {path}", fg=typer.colors.GREEN)
        typer.echo(f"Проверьте/поправьте пакет и примените: `ugar canonize {chapter} --apply`.")
        return
    if not batch_path.exists():
        _fail(f"нет пакета canon_batch.md — сначала `ugar canonize {chapter}`.")
    if not gitops.is_repo(lib):
        # 2.6: без git нет коммита приёмки и отката — отказ ДО записи и без перевода FSM
        _fail(
            "библиотека не под git — применение пакета невозможно (FR-K2: откат только git-revert'ом). "
            "Инициализируйте репозиторий в библиотеке (git init; git add -A; git commit), затем повторите."
        )
    # Идемпотентность (4.1): если приёмка уже закоммичена, а состояние не успело смениться
    # (сбой между коммитом и записью status.yaml), повтор НЕ применяет пакет второй раз —
    # он восстанавливает состояние по действующему коммиту «[глава N]».
    existing = gitops.find_chapter_commit(lib, chapter)
    if existing:
        st.data["коммит_приёмки"] = existing
        st.transition("зафиксировано", "canonize --apply (восстановление по коммиту)")
        _after_canonize(ws, cfg, lib, chapter, existing)
        typer.secho(
            f"Пакет главы {chapter} уже применён коммитом {existing[:10]} — повторное применение "
            f"продублировало бы записи. Состояние восстановлено: «зафиксировано».",
            fg=typer.colors.YELLOW,
        )
        return
    if not yes and not typer.confirm(
        f"Применить пакет главы {chapter} к УГАР_Библиотека/ и закоммитить? (Д-8) (y)"
    ):
        raise typer.Exit()
    commit = canonist.apply_batch(ws, cfg, lib, chapter, st.draft)
    st.data["коммит_приёмки"] = commit  # откат зафиксированной главы — строго по этому SHA
    st.transition("зафиксировано", "canonize --apply")
    typer.secho(f"Глава {chapter} зафиксирована. Коммит: {commit}", fg=typer.colors.GREEN)
    _after_canonize(ws, cfg, lib, chapter, commit)


def _after_canonize(ws: Workspace, cfg: Config, lib: Path, chapter: int, commit: str) -> None:
    """После приёмки (аудит 2, п. 28–29): тег версии канона `глава-N` (повторная приёмка после отката —
    `глава-N-2`) и архив рабочей области, если в config.yaml задан backup_dir. Ни то, ни другое не может
    сорвать приёмку: она уже закоммичена и состояние сменено; сбой — предупреждение."""
    name = gitops.tag_chapter(lib, chapter, commit)
    if name:
        typer.echo(f"Тег канона: {name}")
    else:
        typer.secho("⚠ Тег главы не поставлен (git tag не удался) — приёмка при этом закоммичена.", fg=typer.colors.YELLOW)
    if cfg.backup_dir:
        try:
            path, removed = backup_mod.make_archive(ws, cfg)
            typer.echo(f"Архив рабочей области: {path}" + (f" (удалено старых: {len(removed)})" if removed else ""))
        except OSError as e:
            typer.secho(f"⚠ Архив рабочей области не создан: {e}", fg=typer.colors.YELLOW)


# ------------------------------------------------------------- сервисные


# подсказка «что дальше» по состоянию FSM
NEXT_STEP = {
    "не-начато": "ugar compile {n}",
    "собрано": "ugar write {n}",
    "сгенерировано": "ugar verify1 {n}",
    "верифицировано-1": "ugar verify2 {n}",
    "верифицировано-2": "ugar review {n}",
    "на-приёмке": "заполните edits.md и resolutions.json → ugar apply-edits {n}",
    "правки": "ugar diff-check {n}",
    "дифф-контроль": "ugar accept {n} (если чисто)",
    "принято": "ugar canonize {n} → ugar canonize {n} --apply",
    "зафиксировано": "готово ✓",
}


def _chapter_flags_summary(ws: Workspace, chapter: int) -> tuple[str, str]:
    """(сводка Э1, сводка Э2) по артефактам главы."""
    e1 = "—"
    verdict_path = ws.chapter_dir(chapter) / "verdict.json"
    if verdict_path.exists():
        checks = json.loads(verdict_path.read_text(encoding="utf-8"))["checks"]
        brak = sum(1 for c in checks if c["status"] == "BRAK")
        flag = sum(1 for c in checks if c["status"] == "FLAG")
        e1 = (f"брак {brak}, " if brak else "") + f"флагов {flag}"
    e2 = "—"
    flags = verifier2.load_flags(ws, chapter)
    if (ws.chapter_dir(chapter) / "flags.json").exists():
        sam = sum(1 for f in flags if f.kind == "samovolka")
        e2 = f"флагов {len(flags) - sam}, самоволок {sam}"
    return e1, e2


@app.command("status", rich_help_panel="Обзор")
@_friendly
def cmd_status(
    chapter: int | None = typer.Argument(None, help="Номер главы — подробная карточка."),
    volume: int | None = typer.Option(None, "--том", "--volume", help="Том (по умолчанию — текущий из config.yaml)."),
) -> None:
    """Состояния глав и следующий шаг (FR-D2); `ugar status N` — карточка главы; `--том N` — главы тома N."""
    ws, cfg, lib = _ctx()
    volume = _opt(volume, None)
    if volume is not None and volume != ws.volume:
        ws = ws.for_volume(volume)
    if chapter is not None:
        _status_detail(ws, chapter)
        return
    states = all_states(ws)
    if not states:
        typer.echo(f"Глав тома {ws.volume} в работе нет. Начните: `ugar compile N`.")
        return
    typer.echo(f"Том {ws.volume} · главы в {ws.chapters_root().relative_to(ws.root).as_posix()}/")
    typer.echo(f"{'Глава':>6} | {'Состояние':<18} | {'Чернов.':>7} | {'Э1':<16} | {'Э2':<22} | Дальше")
    typer.echo("-" * 110)
    for st in states:
        e1, e2 = _chapter_flags_summary(ws, st.chapter)
        hint = NEXT_STEP.get(st.state, "").format(n=st.chapter)
        typer.echo(f"{st.chapter:>6} | {st.state:<18} | {st.draft:>7} | {e1:<16} | {e2:<22} | {hint}")
    typer.echo(f"Сегодня: {timing.today_author_minutes(ws):g} мин автора (ожидание действий автора по всем главам).")


def _status_detail(ws: Workspace, chapter: int) -> None:
    """Карточка главы: метрики вердикта, флаги, самоволки, следующий шаг."""
    from . import timing

    st = ChapterState(ws, chapter)
    typer.secho(f"Глава {chapter} · состояние «{st.state}» · черновик {st.draft}", bold=True)
    typer.echo(
        f"Авто-повторов Э1: {st.data.get('авто_повторов', 0)}; итераций правок: {st.data.get('итераций_правок', 0)}"
    )
    machine_s, author_s = timing.chapter_times(st.data.get("история", []))
    if machine_s or author_s:
        over = " ⚠ цель ≤40 мин" if author_s > 40 * 60 else ""
        typer.echo(
            f"Время такта: автора {timing.fmt_minutes(author_s)}{over} · машинное {timing.fmt_minutes(machine_s)}"
        )
    verdict_path = ws.chapter_dir(chapter) / "verdict.json"
    if verdict_path.exists():
        from .schemas import Verdict

        verdict = Verdict.model_validate(json.loads(verdict_path.read_text(encoding="utf-8")))
        typer.echo(f"\nВердикт Э1 (черновик {verdict.draft}):")
        _print_verdict(verdict)
    flags = verifier2.load_flags(ws, chapter)
    if flags:
        typer.echo("\nФлаги Э2:")
        for f in flags:
            mark = "самоволка" if f.kind == "samovolka" else f.severity
            typer.echo(f"  [{mark}] {f.flag_id} · {f.type}: {f.quote[:80]}")
    unresolved = review_mod.unresolved_samovolki(ws, chapter)
    if unresolved:
        typer.secho(
            f"\nБез решения автора: {', '.join(unresolved)} — `ugar resolve {chapter} <флаг> <решение>`",
            fg=typer.colors.YELLOW,
        )
    hint = NEXT_STEP.get(st.state, "").format(n=chapter)
    typer.secho(f"\nДальше: {hint}", fg=typer.colors.GREEN)


@app.command("resolve", rich_help_panel="Правки и решения")
@_friendly
def cmd_resolve(
    chapter: int,
    flag_id: str | None = typer.Argument(None, help="ID самоволки (например F-001)."),
    decision: str | None = typer.Argument(None, help="«вычеркнуть» или «канонизировать»."),
    registry: str | None = typer.Option(None, "--реестр", "--registry", help="Целевой реестр (3.1/3.2/3.3/1.2)."),
) -> None:
    """Решения по самоволкам без ручной правки JSON (FR-V2.5).

    Без аргументов — список; с флагом и решением — записывает решение.
    """
    ws, cfg, lib = _ctx()
    resolutions = review_mod.load_resolutions(ws, chapter)
    if flag_id is None:
        if not resolutions:
            typer.echo("Самоволок нет.")
            return
        flags = {f.flag_id: f for f in verifier2.load_flags(ws, chapter)}
        for r in resolutions:
            quote = flags[r.flag_id].quote[:70] if r.flag_id in flags else ""
            state = r.decision or "БЕЗ РЕШЕНИЯ"
            target = f" → {r.target_registry}" if r.target_registry else ""
            typer.echo(f"  {r.flag_id}: {state}{target}  «{quote}»")
        return
    if decision not in ("вычеркнуть", "канонизировать"):
        _fail("решение должно быть «вычеркнуть» или «канонизировать».")
    for r in resolutions:
        if r.flag_id == flag_id:
            r.decision = decision  # type: ignore[assignment]
            r.target_registry = registry if decision == "канонизировать" else None
            review_mod.save_resolutions(ws, chapter, resolutions)
            left = review_mod.unresolved_samovolki(ws, chapter)
            typer.secho(f"{flag_id}: {decision}{' → ' + registry if registry else ''}.", fg=typer.colors.GREEN)
            if left:
                typer.echo(f"Осталось без решения: {', '.join(left)}")
            return
    _fail(f"самоволка {flag_id} не найдена (см. `ugar resolve {chapter}`).")


@app.command("edits", rich_help_panel="Правки и решения")
@_friendly
def cmd_edits(chapter: int) -> None:
    """Предпросмотр правок: как парсер понял edits.md (без вызова Писателя)."""
    ws, cfg, lib = _ctx()
    edits = review_mod.parse_edits_md(ws, chapter)
    if not edits:
        typer.echo("Правок не распознано (пары «БЫЛО:/СТАЛО:» и строки «УКАЗАНИЕ:»).")
        return
    draft = ws.draft_path(chapter, ChapterState(ws, chapter).draft)
    text = draft.read_text(encoding="utf-8") if draft.exists() else ""
    for e in edits:
        if e.before:
            found = "✓ найдено в черновике" if e.before in text else "✗ НЕ найдено в черновике дословно"
            typer.echo(f"  {e.seq}. БЫЛО: {e.before[:70]}")
            typer.echo(f"     СТАЛО: {e.after[:70]}   [{found}]")
        else:
            typer.echo(f"  {e.seq}. УКАЗАНИЕ: {e.after[:70]}")
    bad = [e.seq for e in edits if e.before and e.before not in text]
    if bad:
        typer.secho(
            f"⚠ Правки {bad}: «было» не найдено дословно — Писатель может их не внести. "
            "Скопируйте цитату из черновика точно.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(f"Распознано {len(edits)} правок. Далее: `ugar apply-edits {chapter}`.", fg=typer.colors.GREEN)


@app.command("check", rich_help_panel="Качество и регрессия")
@_friendly
def cmd_check(
    file: Path = typer.Argument(..., help="Файл с текстом для проверки Э1."),
    chapter: int | None = typer.Option(None, "--глава", "--chapter", help="Взять контекст (фокал/год/объём) из брифа главы."),
    focal: str = typer.Option("", "--фокал", "--focal"),
    year: int | None = typer.Option(None, "--год", "--year"),
    volume_words: int | None = typer.Option(None, "--объём", "--volume"),
) -> None:
    """Прогнать проверки Э1 по произвольному файлу — вне такта и FSM (ручной режим, NFR-3)."""
    ws, cfg, lib = _ctx()
    from .schemas import Brief

    own = None
    part_range = None
    if chapter is not None:
        brief = exporter.load_brief(ws.exports, chapter)
        window_path = ws.window_path(chapter)
        window = window_path.read_text(encoding="utf-8") if window_path.exists() else ""
        # принятая глава уже лежит в корпусе — не сравнивать текст с самим собой (аудит 3.4)
        own = exporter.find_corpus_file(ws.corpus, chapter, brief.volume)
        part_range = verifier1.part_range_for(ws.exports, chapter)
    else:
        brief = Brief(chapter=0, focal=focal, year=year, volume_words=volume_words)
        window = ""
    checks = verifier1.analyze(
        file.read_text(encoding="utf-8"),
        window,
        brief,
        exporter.load_norms(ws.exports),
        exporter.load_stoplists(ws.exports),
        corpus_dir=ws.corpus,
        own_stem=own.stem if own else None,
        extra_abbr=ws.root / "сокращения.txt",
        part_range=part_range,
    )
    from .schemas import Verdict

    _print_verdict(Verdict(chapter=brief.chapter, draft=0, checks=checks))
    worst = "BRAK" if any(c.status == "BRAK" for c in checks) else (
        "FLAG" if any(c.status == "FLAG" for c in checks) else "PASS"
    )
    color = {"PASS": typer.colors.GREEN, "FLAG": typer.colors.YELLOW, "BRAK": typer.colors.RED}[worst]
    typer.secho(f"Итог: {worst}", fg=color)


@app.command("diff", rich_help_panel="Правки и решения")
@_friendly
def cmd_diff(
    chapter: int,
    k1: int | None = typer.Argument(None, help="Номер первого черновика (по умолчанию предпоследний)."),
    k2: int | None = typer.Argument(None, help="Номер второго (по умолчанию текущий)."),
) -> None:
    """Дифф черновиков главы (по умолчанию — два последних)."""
    import difflib

    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    if k2 is None:
        k2 = st.draft
    if k1 is None:
        k1 = int(st.data.get("база_правок", k2 - 1))
    a = ws.draft_path(chapter, k1).read_text(encoding="utf-8").splitlines()
    b = ws.draft_path(chapter, k2).read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(a, b, f"draft_{k1}", f"draft_{k2}", lineterm="", n=1))
    if not diff:
        typer.echo(f"draft_{k1} и draft_{k2} идентичны.")
        return
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            typer.secho(line, fg=typer.colors.GREEN)
        elif line.startswith("-") and not line.startswith("---"):
            typer.secho(line, fg=typer.colors.RED)
        else:
            typer.echo(line)


@app.command("log", rich_help_panel="Обзор")
@_friendly
def cmd_log(n: int = typer.Option(15, "-n", help="Сколько последних вызовов показать.")) -> None:
    """Последние API-вызовы: роль, модель, токены, стоимость (журнал §6.3)."""
    from .apilog import read_log

    ws, cfg, lib = _ctx()
    rows = read_log(ws.logs)[-n:]
    if not rows:
        typer.echo("Журнал API пуст.")
        return
    total_cost = 0.0
    for r in rows:
        cost = r.get("cost_est")
        total_cost += cost or 0
        status = f"ОШИБКА: {r['error'][:40]}" if r.get("error") else (
            f"in {r.get('tokens_in') or '?'} / out {r.get('tokens_out') or '?'}"
            + (f" · ${cost:.4f}" if cost else "")
        )
        typer.echo(
            f"  {r['ts'][:19]} · {r.get('role', '?'):<22} · {r.get('model', ''):<20} "
            f"· гл. {r.get('chapter') or '—'} · {r.get('duration') or '?'} с · {status}"
        )
    if total_cost:
        typer.echo(f"Стоимость показанных вызовов: ${total_cost:.4f}")


@app.command("panel", rich_help_panel="Обзор")
@_friendly
def cmd_panel(
    port: int = typer.Option(8765, "--port", help="Порт локального сервера."),
    open_browser: bool = typer.Option(True, "--открыть/--не-открывать", "--open/--no-open"),
) -> None:
    """Панель (этап 3): такт целиком в браузере — очередь, чтение с флагами,
    правки, решения, дифф, приёмка, дашборд, журнал. Только 127.0.0.1, без облака."""
    from . import server as server_mod

    ws, cfg, lib = _ctx()
    try:
        srv = server_mod.serve(ws, cfg, lib, port)
    except OSError as e:
        _fail(f"порт {port} занят или недоступен ({e}) — укажите другой: `ugar panel --port 8766`.")
    url = f"http://127.0.0.1:{port}/"
    typer.secho(f"Панель запущена: {url} (остановка — Ctrl+C)", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nПанель остановлена.")
    finally:
        srv.server_close()


@app.command("find", rich_help_panel="Обзор")
@_friendly
def cmd_find(query: str) -> None:
    """Поиск по канону и выгрузкам: факты, закладки, правила, брифы, досье, проза."""
    from . import search

    ws, cfg, lib = _ctx()
    groups = search.grouped(search.find(ws.exports, lib, query))
    if not groups:
        typer.echo(f"«{query}»: ничего не найдено.")
        return
    for kind, hits in groups.items():
        typer.secho(f"{kind} ({len(hits)}):", bold=True)
        for h in hits:
            typer.echo(f"  [{h.ref}] {h.text}")


@app.command("circles", rich_help_panel="Качество и регрессия")
@_friendly
def cmd_circles(
    scope: str = typer.Argument("всё", help="книга | акты | главы | всё"),
    chapter: int | None = typer.Option(None, "--глава", "--chapter", help="Только одна глава (для охвата «главы»)."),
    redo: bool = typer.Option(False, "--заново", "--redo", help="Пересчитать уже существующие круги."),
    to_canon: bool = typer.Option(
        False, "--в-канон", "--to-canon", help="Внести черновики кругов в документ 2.1 библиотеки и закоммитить (Д-8)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Круги истории (8 шагов) — каркас драматургии (Р-020): книга → четыре акта → главы; черновики в круги_истории/."""
    from . import circles as circles_mod

    ws, cfg, lib = _ctx()
    exporter.run_export(lib, ws.exports, ws.logs)
    if to_canon:
        n = len(circles_mod.drafts(ws))
        if not n:
            _fail("черновиков кругов нет — сначала `ugar circles`.")
        if not yes and not typer.confirm(
            f"Внести {n} круг(ов) в {circles_mod.canon_doc_name(ws.volume)} библиотеки и закоммитить? (Д-8) (y)"
        ):
            raise typer.Exit()
        try:
            path, commit = circles_mod.commit_to_canon(ws, cfg, lib)
        except RuntimeError as e:
            _fail(str(e))
        typer.secho(f"Круги внесены в канон: {path}. Коммит: {commit}", fg=typer.colors.GREEN)
        typer.echo("Окна глав теперь содержат секцию «Драматургия»; пересоберите начатые главы (`ugar compile N`).")
        return
    result = circles_mod.run(ws, cfg, scope, chapter, only_missing=not redo)
    for path in result["готово"]:
        typer.secho(f"  ✓ {path}", fg=typer.colors.GREEN)
    if result["ручной_режим"]:
        typer.secho(f"⚠ {result['ручной_режим']}", fg=typer.colors.YELLOW)
        typer.echo(f"Промпты для ручного прогона ({len(result['промпты'])}): круги_истории/промпты/ — "
                   "ответ модели вставьте в панели («Круги истории») или сохраните JSON рядом.")
        raise typer.Exit(code=2)
    if not result["готово"]:
        typer.echo("Все круги уже есть — `--заново` для пересчёта.")


@app.command("lint", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_lint(
    llm: bool = typer.Option(False, "--llm", help="Дополнительно: смысловые противоречия моделью (по вызову на документ)."),
    files: list[str] = typer.Option([], "--файл", "--file", help="Только эти документы для модельного слоя (путь внутри библиотеки)."),
    watch: bool = typer.Option(False, "--watch", "--следить", help="Следить за библиотекой и перепроверять при каждом изменении."),
    max_calls: int = typer.Option(40, "--лимит", "--max-calls", help="Предел оплачиваемых вызовов модели за прогон (--llm)."),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="Код возврата 1 при ошибках канона (для скриптов); панель вызывает --no-strict."),
) -> None:
    """Проверка канона на противоречия и ошибки логики повествования (машинный слой; --llm — модель)."""
    from . import lint as lint_mod

    ws, cfg, lib = _ctx()
    if not isinstance(files, list):
        files = []
    if not isinstance(max_calls, int):
        max_calls = 40
    if not isinstance(strict, bool):
        strict = True
    try:
        llm_docs = lint_mod.resolve_library_files(lib, files) if llm else []
    except ValueError as e:
        _fail(str(e))

    def once() -> int:
        try:
            report = lint_mod.run_lint(lib, ws.exports, ws.logs, volume=ws.volume)
        except Exception as e:  # noqa: BLE001 — сбой линтера виден как находка, не как трейсбек
            report = lint_mod.error_report(e, ws.logs)
        if llm:
            if report.errors:
                typer.secho(
                    f"⚠ Модельный слой пропущен: сначала устраните {report.errors} ошиб. машинного слоя "
                    "(выгрузки при ошибках разметки неполны — модель проверяла бы не тот канон).",
                    fg=typer.colors.YELLOW,
                )
            else:
                est = lint_mod.estimate_llm_cost(cfg, len(llm_docs))
                typer.echo(f"Модельный слой: документов {len(llm_docs)}, вызовов ≤ {len(llm_docs)}"
                           + (f", ≈ ${est:.2f}" if est is not None else ""))
                try:
                    extra, prompts = lint_mod.run_lint_llm(ws, cfg, lib, llm_docs, max_calls=max_calls)
                except ValueError as e:
                    _fail(str(e))
                report = lint_mod.merge_llm(report, extra, ws.logs)
                if prompts:
                    typer.secho(f"⚠ API недоступен: промпты модельного слоя сохранены ({len(prompts)}) в logs/линтер_промпты/", fg=typer.colors.YELLOW)
        for f in report.findings:
            color = {"ошибка": typer.colors.RED, "предупреждение": typer.colors.YELLOW, "заметка": typer.colors.BLUE}[f.severity]
            where = f"{f.file}:{f.line}" if f.line else f.file
            typer.secho(f"  [{f.severity}] {f.code} {where} — {f.message}", fg=color)
            if f.fix:
                typer.echo(f"      исправление: «{f.fix.old}» → «{f.fix.new}»")
        typer.secho(
            f"Канон: документов {report.files_checked}, ошибок {report.errors}, предупреждений {report.warnings}, "
            f"заметок {report.notes} → logs/lint.md",
            fg=typer.colors.RED if report.errors else typer.colors.GREEN,
        )
        return report.errors

    if not watch:
        errors = once()
        if errors and strict:
            raise typer.Exit(code=1)
        return
    from . import canonwatch

    once()
    typer.echo("Слежу за библиотекой (Ctrl+C — стоп)…")

    def on_change(changed: list[str]) -> None:
        typer.echo(f"\nИзменено: {', '.join(changed)}")
        try:
            once()
        except Exception as e:  # noqa: BLE001 — наблюдение продолжается, причина видна
            typer.secho(f"⚠ Проверка не выполнена: {e}", fg=typer.colors.RED)

    watcher = canonwatch.CanonWatcher(lib, on_change)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        typer.echo("Остановлено.")


@app.command("snapshot", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_snapshot(volume: int | None = typer.Argument(None, help="Номер тома (по умолчанию — текущий).")) -> None:
    """Черновик снапшота тома (реестр 3.5): кто что знает, закладки, хронология.
    В канон снапшот вносит `ugar volume close N`."""
    from . import snapshot as snapshot_mod

    ws, cfg, lib = _ctx()
    volume = _opt(volume, None) or ws.volume
    if volume != ws.volume:
        _fail(f"выгрузки — тома {ws.volume}; для среза тома {volume} переключитесь: `ugar volume open {volume}`.")
    exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
    path = snapshot_mod.build_snapshot(ws, volume)
    typer.secho(f"Срез тома {volume}: {path}", fg=typer.colors.GREEN)
    typer.echo("Внесите его в библиотеку правкой канона и `ugar canon-commit` (FR-K3 соблюдён).")


volume_app = typer.Typer(
    help="Тома (аудит 2, п. 27): сводка тома, закрытие тома (снапшот 3.5, тег, рукопись, статистика), переключение текущего тома.",
    no_args_is_help=True,
)
app.add_typer(volume_app, name="volume", rich_help_panel="Канон и бэкап")


@volume_app.command("status")
@_friendly
def cmd_volume_status(
    volume: int | None = typer.Argument(None, help="Номер тома (по умолчанию — текущий)."),
) -> None:
    """Сводка тома: главы по состояниям, слова принятых глав, метрики Э1 по актам, стоимость по logs/api.jsonl."""
    ws, cfg, lib = _ctx()
    volume = _opt(volume, None) or ws.volume
    if volume == ws.volume:
        try:
            exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
        except MarkupError as e:
            typer.secho(f"⚠ выгрузки не пересобраны: {e}", fg=typer.colors.YELLOW)
    stats = volume_mod.volume_stats(ws, lib, volume)
    typer.secho(f"Том {volume}" + (" (текущий)" if volume == ws.volume else ""), bold=True)
    typer.echo(f"Главы в {ws.chapters_root(volume).relative_to(ws.root).as_posix()}/; глав в поглавнике: {stats.chapters_total}")
    typer.echo(f"Зафиксировано: {len(stats.fixed)}" + (f" ({', '.join(map(str, stats.fixed))})" if stats.fixed else ""))
    typer.echo(f"В работе: {len(stats.in_work)}" + (" — " + "; ".join(f"гл. {n}: {st}" for n, st in stats.in_work.items()) if stats.in_work else ""))
    typer.echo(f"Слов в принятых главах: {stats.words_total}")
    if stats.total_metrics:
        typer.echo("Метрики Э1 (средние): " + "; ".join(f"{k}: {v:g}" for k, v in stats.total_metrics.items()))
    for a in stats.acts:
        m = stats.act_metrics.get(a.act)
        if m:
            typer.echo(f"  акт {a.act} «{a.title}» (гл. {a.from_chapter}–{a.to_chapter}): " + "; ".join(f"{k}: {v:g}" for k, v in m.items()))
    typer.echo(f"Вызовов моделей: {stats.calls}; оценка стоимости: ${stats.cost:.2f}")
    if stats.missing_docs:
        typer.secho("В библиотеке нет документов тома: " + "; ".join(stats.missing_docs), fg=typer.colors.YELLOW)


@volume_app.command("close")
@_friendly
def cmd_volume_close(
    volume: int | None = typer.Argument(None, help="Номер тома (по умолчанию — текущий)."),
    again: bool = typer.Option(False, "--заново", "--again", help="Переписать уже существующий снапшот 35_Снапшот_ТомN.md и тег."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Подтверждение без вопросов (снапшот в канон; переключение тома — только явным ответом)."),
    next_volume: bool | None = typer.Option(None, "--следующий/--без-переключения", help="Переключить config.volume на N+1 без вопроса / не переключать."),
) -> None:
    """Закрыть том: все главы «зафиксировано» → снапшот 3.5 в библиотеку (35_Снапшот_ТомN.md, коммит) →
    тег `том-N` → рукопись manuscript/ТомN.md (+ .docx при python-docx) → статистика → переход к тому N+1."""
    ws, cfg, lib = _ctx()
    volume = _opt(volume, None) or ws.volume
    again = _opt(again, False)
    yes = _opt(yes, False)
    next_volume = _opt(next_volume, None)
    pending = volume_mod.unfixed_chapters(ws, volume) if volume == ws.volume else []
    if pending:
        _fail(f"том {volume} нельзя закрыть: не зафиксированы {', '.join(pending)}.")
    if not yes and not typer.confirm(
        f"Закрыть том {volume}: внести снапшот 3.5 в библиотеку и закоммитить, поставить тег том-{volume}, собрать рукопись? (Д-8)"
    ):
        raise typer.Abort()
    res = volume_mod.close_volume(ws, cfg, lib, volume, again=again, author_confirmed=True)
    typer.secho(f"Том {volume} закрыт.", fg=typer.colors.GREEN)
    typer.echo(f"  снапшот 3.5: {res.snapshot_doc.name} — {'; '.join(res.messages)}")
    typer.echo(f"  тег: {res.tag or '—'}")
    typer.echo(f"  рукопись: {res.manuscript_md.relative_to(ws.root).as_posix()}"
               + (f", {res.manuscript_docx.relative_to(ws.root).as_posix()}" if res.manuscript_docx else ""))
    if res.docx_hint:
        typer.secho(f"  {res.docx_hint}", fg=typer.colors.YELLOW)
    typer.echo(f"  статистика: {res.stats_path.relative_to(ws.root).as_posix()}")
    nxt = volume + 1
    missing = volume_mod.open_volume(ws, lib, nxt)
    if missing:
        typer.secho(
            f"Том {nxt} не открыт: в библиотеке нет его документов — заведите " + "; ".join(missing)
            + f", затем `ugar volume open {nxt}`.", fg=typer.colors.YELLOW,
        )
        return
    if next_volume is None:
        next_volume = typer.confirm(f"Переключить рабочую область на том {nxt} (config.yaml: volume)?", default=False)
    if next_volume:
        set_volume(ws, nxt)
        exporter.run_export(lib, ws.exports, ws.logs, nxt)
        typer.secho(f"Текущий том: {nxt} (главы — {ws.chapters_root(nxt).relative_to(ws.root).as_posix()}/, выгрузки пересобраны).",
                    fg=typer.colors.GREEN)
    else:
        typer.echo(f"Текущий том остался {ws.volume}; переключить позже — `ugar volume open {nxt}`.")


@volume_app.command("open")
@_friendly
def cmd_volume_open(volume: int = typer.Argument(..., help="Номер тома, над которым идёт работа.")) -> None:
    """Переключить текущий том рабочей области (config.yaml: volume) — с проверкой, что документы тома есть."""
    ws, cfg, lib = _ctx()
    missing = volume_mod.open_volume(ws, lib, volume)
    if missing:
        _fail(f"в библиотеке нет документов тома {volume} — заведите: " + "; ".join(missing))
    if volume == ws.volume:
        typer.echo(f"Том {volume} уже текущий.")
        return
    set_volume(ws, volume)
    try:
        exporter.run_export(lib, ws.exports, ws.logs, volume)
    except MarkupError as e:
        _fail(f"том {volume} переключён, но выгрузки не собрались: {e}")
    typer.secho(f"Текущий том: {volume}. Главы — {ws.chapters_root(volume).relative_to(ws.root).as_posix()}/; выгрузки пересобраны.",
                fg=typer.colors.GREEN)


@app.command("doctor", rich_help_panel="Обзор")
@_friendly
def cmd_doctor() -> None:
    """Диагностика установки и готовности конвейера (NFR-1)."""
    import importlib.util
    import os

    ws, cfg, lib = _ctx()

    def item(ok: bool | None, label: str, hint: str = "") -> None:
        mark, color = {True: ("✓", typer.colors.GREEN), False: ("✗", typer.colors.RED), None: ("~", typer.colors.YELLOW)}[ok]
        typer.secho(f" {mark} {label}", fg=color)
        if hint and ok is not True:
            typer.echo(f"   → {hint}")

    typer.secho(f"Рабочая область: {ws.root}", bold=True)
    item((ws.root / "config.yaml").exists(), "config.yaml", "создайте: `ugar init`")
    item(lib.exists(), f"библиотека канона: {lib}", "положите УГАР_Библиотека/ или поправьте library_dir в config.yaml")
    if lib.exists():
        lay = backup_mod.layout(lib, ws.root)
        item(lay.kind != "no-git", "библиотека под git", "git init внутри библиотеки (версионирование канона, §5.1)")
        if lay.kind != "no-git":
            item(lay.ok, lay.label, lay.hint)  # три раскладки (п. 28): своя / внутри репозитория кода / не под git
        if gitops.is_repo(lib):
            item(gitops.has_identity(lib) or bool(cfg.commit_author), "авторство git настроено",
                 "git config user.email/user.name или commit_author в config.yaml (Д-8)")
            item(gitops.in_progress(lib) is None, "нет незавершённых операций git в библиотеке",
                 f"завершите или отмените: git {gitops.in_progress(lib) or ''} --abort (в документах могут быть маркеры конфликта)")
            n_remotes = len(gitops.remotes(lib))
            item(n_remotes >= cfg.backup_remotes_min, f"удалённых копий: {n_remotes} (нужно ≥{cfg.backup_remotes_min})",
                 "`ugar backup --добавить-remote <имя> <url|папка>` — папка на внешнем диске подходит (NFR-6, §1.3)")
    arch_dir = backup_mod.archive_dir(ws, cfg)
    arch_age = backup_mod.archive_age_days(arch_dir)
    if arch_age is None:
        item(None if cfg.backup_dir is None else False, f"архив рабочей области: ещё не делался ({arch_dir})",
             "`ugar backup --архив`; backup_dir в config.yaml — архив после каждой приёмки главы (п. 29)")
    else:
        item(arch_age <= 7, f"архив рабочей области: {arch_age:.1f} дн. назад ({backup_mod.latest_archive(arch_dir)})",
             "`ugar backup --архив`")
    manifest = ws.exports / "manifest.json"
    item(manifest.exists(), "выгрузки exports/", "выполните `ugar export`")
    item(bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
         "GEMINI_API_KEY (Писатель)", "задайте в .env — иначе ручной режим (NFR-3)")
    item(bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY (Верификатор-2/Канонист)",
         "задайте в .env — иначе ручной режим (NFR-3)")
    def has_module(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:  # нет пакета-родителя (google.*)
            return False

    item(has_module("google.genai"), "SDK google-genai", "pip install 'ugar-pipeline[llm]'")
    item(has_module("anthropic"), "SDK anthropic", "pip install 'ugar-pipeline[llm]'")
    # пины моделей против API (п. 31): только чтение метаданных, ни одной генерации
    seen: set[tuple[str, str]] = set()
    for role, mc in (("Писатель", cfg.writer), ("Верификатор-2", cfg.verifier2), ("Канонист", cfg.canonist)):
        if (mc.provider, mc.model) in seen:
            continue
        seen.add((mc.provider, mc.model))
        ok, note = adapters.probe_model(mc)
        roles = "/".join(r for r, m in (("Писатель", cfg.writer), ("Верификатор-2", cfg.verifier2), ("Канонист", cfg.canonist))
                         if (m.provider, m.model) == (mc.provider, mc.model))
        label = f"модель {mc.model} ({roles}): " + (f"есть в API ({note})" if ok else note)
        item(ok, label, "смените пин в config.yaml через пере-тест (`ugar retest`, сценарий В, Д-11)" if ok is False else "")
    green = regression_mod.is_green(ws)
    if green is None:
        label = (
            "отчёт регрессии устарел (изменились config.yaml, шаблоны или нормы)"
            if regression_mod.is_stale(ws) else "регрессия ещё не запускалась"
        )
    else:
        label = "регрессия зелёная" if green else "регрессия КРАСНАЯ"
    item(green, label, "`ugar regress`" if green is None else "пропущенные флаги блокируют смену конфигурации (FR-R3)")
    n_tests = len(regression_mod.load_tests(ws)) if ws.regression.exists() else 0
    item(n_tests > 0, f"золотых тестов: {n_tests}", "корпус пуст — регрессия не может быть зелёной; пополните: `ugar add-golden` (FR-R1)")


@app.command("rollback", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_rollback(
    chapter: int,
    to: str | None = typer.Option(None, "--to", help="Целевое состояние (§5.4); без него — на один шаг назад."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Откат главы в предыдущее состояние (сценарий Г); без --to — на шаг назад по цепочке состояний §5.4."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    if to is None:
        # 2.11: «предыдущее» — по цепочке STATES, а не по истории (после отката история
        # указывала бы вперёд, а не назад)
        idx = STATES.index(st.state)
        if idx == 0:
            _fail(f"глава {chapter} ещё не начата — откатывать некуда.")
        to = STATES[idx - 1]
        typer.echo(f"Откат на шаг назад: «{st.state}» → «{to}».")
    # Проверка цели ДО любых побочных эффектов (4.2): опечатка в --to не должна стоить git revert'а
    if to not in STATES:
        _fail(f"неизвестное состояние «{to}»; допустимые: {', '.join(STATES)}.")
    if STATES.index(to) >= STATES.index(st.state):
        _fail(f"откат возможен только назад: «{st.state}» → «{to}» не является откатом.")
    if st.state == "зафиксировано":
        # только git-revert коммита приёмки с пересчётом выгрузок и корпуса
        sha = st.data.get("коммит_приёмки") or gitops.find_chapter_commit(lib, chapter)
        if not sha:
            _fail(f"не найден коммит приёмки главы {chapter} в библиотеке.")
        if not yes and not typer.confirm(f"git revert {sha[:10]} (приёмка главы {chapter}) и пересчёт выгрузок? (y)"):
            raise typer.Exit()
        try:
            gitops.revert(lib, sha, author=cfg.commit_author)
        except RuntimeError as e:
            _fail(f"откат не выполнен, библиотека не тронута: {e}")
        # состояние — сразу после успешного реверта, чтобы повторный откат не «ревертил реверт»
        st.data["состояние"] = "принято"
        st.data.pop("коммит_приёмки", None)
        st.data.setdefault("история", []).append(
            {"из": "зафиксировано", "в": "принято", "время": datetime.now(timezone.utc).isoformat(), "команда": "rollback (git revert)"}
        )
        st._save()
        try:
            exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
        except MarkupError as e:
            typer.secho(f"⚠ Откат выполнен, но выгрузки не пересчитаны: {e}. Поправьте канон и `ugar export`.", fg=typer.colors.YELLOW)
        if to != "принято":
            st.rollback(to)
        typer.secho(f"Откат выполнен: глава {chapter} → «{st.state}», выгрузки и корпус пересчитаны.", fg=typer.colors.GREEN)
        return
    try:
        st.rollback(to)
    except TransitionError as e:
        _fail(str(e))
    typer.secho(f"Глава {chapter} → «{to}».", fg=typer.colors.GREEN)


@app.command("regress", rich_help_panel="Качество и регрессия")
@_friendly
def cmd_regress(llm: bool = typer.Option(False, "--llm", help="Включить тесты Э2.")) -> None:
    """Прогон регрессионного корпуса золотых тестов (FR-R2)."""
    ws, cfg, lib = _ctx()
    report = regression_mod.run_regression(ws, llm=llm, cfg=cfg)
    if not report["всего"]:
        typer.secho(
            "⚠ Корпус золотых тестов ПУСТ (regression/golden/) — регрессия ничего не проверила и зелёной "
            "считаться не может (FR-R3). Пополните корпус: `ugar add-golden` (FR-R1).",
            fg=typer.colors.YELLOW,
        )
    elif not report.get("выполнено"):
        typer.secho(
            "⚠ Ни один тест не выполнен (все Э2 пропущены: нужен --llm и ключ API) — регрессия не зелёная.",
            fg=typer.colors.YELLOW,
        )
    for r in report["результаты"]:
        if r.get("skipped"):
            typer.echo(f"  ~ {r['test_id']}: пропущен ({r['skipped']})")
        elif r.get("пропущено"):
            typer.secho(f"  ✗ {r['test_id']}: пропущено {r['пропущено']}", fg=typer.colors.RED)
        else:
            extra = f", лишние: {r['лишние']}" if r.get("лишние") else ""
            typer.secho(f"  ✓ {r['test_id']}: поймано {r['поймано']}{extra}", fg=typer.colors.GREEN)
    if report["зелёная"]:
        typer.secho("Регрессия ЗЕЛЁНАЯ.", fg=typer.colors.GREEN)
    else:
        why = report.get("причина") or "пропущены ожидаемые флаги"
        typer.secho(
            f"Регрессия КРАСНАЯ: {why}{' ' + str(report['провалено']) if report['провалено'] else ''} "
            "(FR-R3: смена конфигурации заблокирована).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


@app.command("add-golden", rich_help_panel="Качество и регрессия")
@_friendly
def cmd_add_golden(
    test_id: str,
    fragment_file: Path,
    expect: list[str] = typer.Option([], "--expect", help="Ожидаемый флаг (check_id), можно несколько раз."),
    focal: str = typer.Option("", "--focal"),
    year: int | None = typer.Option(None, "--year"),
    echelon: str = typer.Option("Э1", "--echelon"),
) -> None:
    """Добавить золотой тест из пойманной автором ошибки (FR-R1)."""
    ws, cfg, lib = _ctx()
    test = GoldenTest(
        test_id=test_id,
        fragment=fragment_file.read_text(encoding="utf-8"),
        context_slice={"focal": focal, "year": year},
        expected_flags=expect,
        echelon=echelon,  # type: ignore[arg-type]
    )
    path = regression_mod.add_test(ws, test)
    typer.secho(f"Золотой тест добавлен: {path}", fg=typer.colors.GREEN)


@app.command("dashboard", rich_help_panel="Обзор")
@_friendly
def cmd_dashboard(
    open_browser: bool = typer.Option(False, "--открыть", "--open", help="Открыть в браузере."),
) -> None:
    """Собрать dashboard.html (FR-D1)."""
    ws, cfg, lib = _ctx()
    path = dashboard_mod.build_dashboard(ws)
    typer.secho(f"Дашборд: {path}", fg=typer.colors.GREEN)
    if open_browser:
        import webbrowser

        webbrowser.open(path.as_uri())


@app.command("run", rich_help_panel="Такт главы")
@_friendly
def cmd_run(chapter: int) -> None:
    """Такт целиком с паузами на шагах автора (FR-O1): review, accept, canonize."""
    ws, cfg, lib = _ctx()
    while True:
        st = ChapterState(ws, chapter)
        state = st.state
        cancel.check(f"такт, состояние «{state}»")  # между шагами: глава остаётся на завершённом шаге
        if state == "не-начато":
            cmd_compile(chapter)
        elif state == "собрано":
            cmd_write(chapter, manual=False)
        elif state == "сгенерировано":
            cmd_verify1(chapter)
        elif state == "верифицировано-1":
            cmd_verify2(chapter, manual=False)
        elif state == "верифицировано-2":
            cmd_review(chapter)
            typer.echo("⏸ Пауза такта: заполните edits.md и resolutions.json, затем снова `ugar run N`.")
            return
        elif state == "на-приёмке":
            cmd_apply_edits(chapter, manual=False)
        elif state == "правки":
            cmd_diff_check(chapter, author_fix=False)
            st = ChapterState(ws, chapter)
            data = json.loads((ws.chapter_dir(chapter) / "diff_report.json").read_text(encoding="utf-8"))
            if data.get("not_applied") or data.get("unauthorized"):
                typer.echo("⏸ Пауза такта: дифф-контроль не чист — решите и продолжите `ugar run N`.")
                return
        elif state == "дифф-контроль":
            typer.echo(f"⏸ Пауза такта: приёмка автора — `ugar accept {chapter}`, затем `ugar run {chapter}`.")
            return
        elif state == "принято":
            if not (ws.chapter_dir(chapter) / "canon_batch.md").exists():
                cmd_canonize(chapter, apply=False, yes=False)
            typer.echo(f"⏸ Пауза такта: подпишите пакет — `ugar canonize {chapter} --apply`.")
            return
        elif state == "зафиксировано":
            typer.secho(f"Глава {chapter} зафиксирована — такт завершён.", fg=typer.colors.GREEN)
            return


@app.command("retest", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_retest(
    chapter: int = typer.Option(1, "--chapter", help="Глава для свежего брифа пакета."),
    fix: bool = typer.Option(False, "--зафиксировать", "--fix", help="Зафиксировать результаты (требует зелёной регрессии, FR-R3)."),
) -> None:
    """Пере-тест моделей (сценарий В, Д-10): пакет раунда 1 протокола отбора; прогон полуручной."""
    ws, cfg, lib = _ctx()
    if fix:
        green = regression_mod.is_green(ws)
        if green is not True:
            why = (
                "регрессия КРАСНАЯ" if green is False
                else "отчёт регрессии устарел (изменились config.yaml, шаблоны или нормы)"
                if regression_mod.is_stale(ws) else "регрессия не запускалась"
            )
            _fail(f"фиксация retest запрещена: {why} (FR-R3). Сначала `ugar regress` с непустым корпусом.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        guard.write_text(
            ws.root / "retest" / stamp / "журнал_запись.md",
            f"# Запись в журнал 3.6 (внесите в библиотеку через правку канона)\n\n"
            f"- Дата: {stamp}\n- Событие: пере-тест моделей, результаты приняты автором.\n"
            f"- Конфигурация: писатель {cfg.writer.model}, верификатор {cfg.verifier2.model}.\n",
        )
        typer.secho(f"Черновик записи журнала: retest/{stamp}/журнал_запись.md — внесите в 3.6 (сценарий Б).", fg=typer.colors.GREEN)
        return
    exporter.run_export(lib, ws.exports, ws.logs, ws.volume)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = ws.root / "retest" / stamp
    # 2.10: окно собирается во временную рабочую область — window.md главы в работе не трогается
    _compile_window_to(ws, cfg, lib, chapter, _ensure_dir(dest / "ПРОМПТ_раунд1.md"))
    proto = sorted(lib.glob("Тест_Писателя/ПРОТОКОЛ_ОТБОРА.md"))
    if proto:
        shutil.copyfile(proto[0], dest / "ПРОТОКОЛ_ОТБОРА.md")
    guard.write_text(
        dest / "РЕЗУЛЬТАТЫ.md",
        "# Результаты раунда 1\n\nПоложите ответы моделей файлами `ответ_<модель>.md` в эту папку;\n"
        "решение — записью в журнал 3.6 (`ugar retest --зафиксировать`).\n",
    )
    typer.secho(f"Пакет пере-теста готов: {dest}/ (прогон по сторонним моделям — полуручной, Д-10).", fg=typer.colors.GREEN)


def _ensure_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compile_window_to(ws: Workspace, cfg: Config, lib: Path, chapter: int, target: Path) -> Path:
    """Собирает окно главы во временную рабочую область (копия выгрузок и шаблонов) и кладёт
    результат в target: chapters/N/window.md главы в работе остаётся нетронутым (2.10)."""
    tmp_root = target.parent / "_сборка_окна"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    (tmp_root / "exports").mkdir(parents=True)
    for f in ws.exports.glob("*.json"):
        shutil.copyfile(f, tmp_root / "exports" / f.name)
    if ws.templates.exists():
        shutil.copytree(ws.templates, tmp_root / "templates")
    try:
        path, _ = compiler.compile_window(Workspace(tmp_root), lib, chapter, cfg.window_soft_limit_chars)
        shutil.copyfile(path, target)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return target


@app.command("canon-commit", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_canon_commit(
    message: str = typer.Option(..., "-m", "--message", help="Сообщение коммита (изменение норм — со ссылкой Р-№)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Правка канона автором (сценарий Б): валидация структуры, перегенерация выгрузок, коммит."""
    ws, cfg, lib = _ctx()
    if not gitops.is_repo(lib):
        _fail("библиотека не под git — инициализируйте репозиторий.")
    manifest = ws.exports / "manifest.json"
    old_norms_hash = None
    if manifest.exists():
        old_norms_hash = json.loads(manifest.read_text(encoding="utf-8"))["files"].get("norms.json")

    def ask(result: canonchange.ChangeResult) -> bool:
        """Между линтом и коммитом: предупреждения автору и вопрос (Д-8)."""
        if (
            old_norms_hash is not None
            and result.export_hashes.get("norms.json") != old_norms_hash
            and not gitops.check_norm_change_message(message)
        ):
            typer.secho(
                "⚠ Изменены нормы (02 §5), но в сообщении коммита нет ссылки Р-№ на запись "
                "в 36_Журнал — предупреждение, не блокировка (сценарий Б).",
                fg=typer.colors.YELLOW,
            )
        if not gitops.dirty(lib):
            return False
        if result.lint and (result.lint.errors or result.lint.warnings):
            typer.secho(
                f"⚠ Проверка канона: ошибок {result.lint.errors}, предупреждений {result.lint.warnings} (logs/lint.md) — "
                "коммит не блокируется, решение за автором.",
                fg=typer.colors.YELLOW,
            )
        if not yes and not typer.confirm(f"Закоммитить изменения библиотеки: «{message}»? (Д-8) (y)"):
            raise typer.Exit()
        return True

    # единый конвейер изменения канона: правки автор уже сделал на диске (writer пуст) →
    # валидация Д-1 + выгрузки → линт → коммит; незавершённый revert блокирует до любой записи
    try:
        result = canonchange.canon_change(
            ws, cfg, lib, lambda: None, message, commit=True, author_confirmed=True,
            require_clean=False, action="коммит канона", confirm=ask,
        )
    except MarkupError as e:
        _fail(f"структура MD расходится с соглашениями Д-1 → {e}")
    if result.commit is None:
        typer.echo("В библиотеке нет изменений — коммитить нечего.")
        return
    typer.secho(f"Канон закоммичен: {result.commit}", fg=typer.colors.GREEN)


@app.command("library-split", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_library_split(
    target: str | None = typer.Option(None, "--в", "--to", help="Куда перенести (по умолчанию ../УГАР_Библиотека рядом с рабочей областью)."),
    show: bool = typer.Option(False, "--показать", "--dry-run", help="Только план, ничего не менять."),
    with_history: bool = typer.Option(False, "--с-историей", "--with-history",
                                      help="Перенести историю папки в новый репозиторий (git subtree split)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Вынести библиотеку канона в отдельный git-репозиторий рядом с рабочей областью (аудит 2, п. 28):
    перенос папки, git init + первый коммит, library_dir в config.yaml, .gitignore в прежнем репозитории."""
    ws, cfg, lib = _ctx()
    target, show, with_history = _opt(target, None), _opt(show, False), _opt(with_history, False)
    try:
        plan = backup_mod.plan_split(ws, cfg, lib, Path(target) if target else None, with_history=with_history)
    except backup_mod.SplitError as e:
        _fail(str(e))
    typer.secho(f"Сейчас: {plan.layout.label}.", bold=True)
    typer.echo("План переезда:")
    for line in plan.lines():
        typer.echo(f"  {line}")
    if show:
        typer.echo("Ничего не изменено (--показать). Выполнить: `ugar library-split`" + (" --с-историей" if with_history else "") + ".")
        return
    if not yes and not typer.confirm("Выполнить переезд? (y)"):
        raise typer.Exit()
    for note in backup_mod.split_library(ws, cfg, plan):
        typer.secho(f" ✓ {note}", fg=typer.colors.GREEN)
    typer.echo("Что дальше:")
    for line in backup_mod.after_split_advice(plan):
        typer.echo(f"  • {line}")


def _is_git_url(value: str) -> bool:
    """URL удалённого репозитория (https://, ssh://, git@host:path) — в отличие от локальной папки."""
    return "://" in value or bool(re.match(r"^[\w.-]+@[\w.-]+:", value))


@app.command("backup", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_backup(
    folder: str | None = typer.Argument(None, help="Папка архива для --архив (по умолчанию backup_dir из config.yaml, иначе ../УГАР_бэкап)."),
    push: bool = typer.Option(False, "--push", help="Отправить библиотеку во все удалённые места (после y)."),
    archive: bool = typer.Option(False, "--архив", "--archive", help="Zip рабочей области (chapters/, logs/, круги, снапшоты, корпус, config.yaml)."),
    add_remote: tuple[str, str] | None = typer.Option(
        None, "--добавить-remote", "--add-remote", metavar="ИМЯ URL|ПАПКА",
        help="Добавить удалённое место библиотеки: URL или локальная папка (внешний диск; создаётся как bare-репозиторий)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Сохранность (NFR-6): состояние копий; --push — во все remotes; --архив — zip рабочей области;
    --добавить-remote — второе место хранения (папка на внешнем диске = без облака, §1.3 ТЗ)."""
    ws, cfg, lib = _ctx()
    folder = _opt(folder, None)
    archive, add_remote = _opt(archive, False), _opt(add_remote, None)
    if not gitops.is_repo(lib):
        _fail("библиотека не под git — инициализируйте репозиторий (`ugar library-split` — как отдельный).")
    if add_remote:
        name, url = add_remote
        if name in gitops.remotes(lib):
            _fail(f"удалённое место «{name}» уже есть: {gitops.remote_url(lib, name)}")
        if not _is_git_url(url):
            target = Path(url).expanduser()
            target = target if target.is_absolute() else (Path.cwd() / target)
            if target.exists() and not gitops.is_bare_repo(target):
                _fail(f"папка {target} существует, но это не bare-репозиторий git — укажите пустой путь.")
            if not target.exists():
                gitops.init_bare(target)
                typer.echo(f"Создан bare-репозиторий: {target}")
            url = str(target)
        gitops.add_remote(lib, name, url)
        typer.secho(f"Удалённое место «{name}» добавлено: {url}. Отправка — `ugar backup --push`.", fg=typer.colors.GREEN)
    remotes = gitops.remotes(lib)
    typer.echo(f"Удалённых мест: {len(remotes)} ({', '.join(remotes) or 'нет'}); требуется ≥{cfg.backup_remotes_min}.")
    if len(remotes) < cfg.backup_remotes_min:
        typer.secho("⚠ Добавьте удалённые репозитории/внешние копии (NFR-6): `ugar backup --добавить-remote <имя> <url|папка>`.",
                    fg=typer.colors.YELLOW)
    if gitops.dirty(lib):
        typer.secho("⚠ В библиотеке незакоммиченные изменения (`ugar canon-commit`).", fg=typer.colors.YELLOW)
    age = gitops.last_commit_age_days(lib)
    if age is not None:
        typer.echo(f"Последний коммит: {age:.1f} дн. назад.")
    arch_dir = backup_mod.archive_dir(ws, cfg, folder)
    if archive:
        path, removed = backup_mod.make_archive(ws, cfg, arch_dir)
        typer.secho(f"Архив рабочей области: {path}", fg=typer.colors.GREEN)
        if removed:
            typer.echo(f"Удалено старых архивов: {len(removed)} (хранится последних {cfg.backup_keep}, backup_keep).")
    else:
        arch_age = backup_mod.archive_age_days(arch_dir)
        typer.echo(
            f"Архив рабочей области: {arch_age:.1f} дн. назад ({backup_mod.latest_archive(arch_dir)})." if arch_age is not None
            else f"Архив рабочей области ещё не делался ({arch_dir}): `ugar backup --архив`."
        )
    if push:
        if not remotes:
            _fail("нет удалённых репозиториев — добавьте git remote.")
        if not yes and not typer.confirm(f"Отправить в {len(remotes)} удалённых мест? (y)"):
            raise typer.Exit()
        for remote in remotes:
            try:
                gitops.push(lib, remote)
                typer.secho(f" ✓ {remote}", fg=typer.colors.GREEN)
            except RuntimeError as e:
                typer.secho(f" ✗ {remote}: {e}", fg=typer.colors.RED)


@app.command("init", rich_help_panel="Настройка")
@_friendly
def cmd_init(
    demo: bool = typer.Option(False, "--демо", "--demo", help="Развернуть демо-библиотеку и золотые тесты — играбельный пример."),
) -> None:
    """Создать каркас рабочей области: config.yaml, .env.example, папки (NFR-1)."""
    ws = Workspace(Path.cwd())
    if not (ws.root / "config.yaml").exists():
        shutil.copyfile(Path(__file__).parent / "data" / "config.example.yaml", ws.root / "config.yaml")
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
        typer.secho(
            "Демо развёрнуто. Попробуйте: `ugar export` → `ugar compile 1` → `ugar status` → `ugar regress`.",
            fg=typer.colors.GREEN,
        )
        typer.echo("Ключи API не обязательны: без них каждый шаг подскажет ручной режим (NFR-3).")
        return
    typer.secho("Рабочая область готова. Заполните config.yaml и .env (Д-9), положите УГАР_Библиотека/.", fg=typer.colors.GREEN)
    typer.echo("Хотите пощупать конвейер на примере — `ugar init --демо`. Диагностика: `ugar doctor`.")


def main() -> None:  # точка входа для python -m ugar.cli
    app()


if __name__ == "__main__":
    main()
