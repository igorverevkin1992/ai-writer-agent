"""CLI конвейера «УГАР» (интерфейсы из реестра модулей 4.2; язык — русский, NFR-2).

Каждый шаг такта исполним отдельной командой (FR-O2): отказ любого компонента
не блокирует такт — артефакты человекочитаемы, ручной режим всегда возможен (NFR-3).
"""

from __future__ import annotations

import functools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import (
    adapters,
    canonist,
    compiler,
    dashboard as dashboard_mod,
    exporter,
    gitops,
    guard,
    regression as regression_mod,
    review as review_mod,
    verifier1,
    verifier2,
    writer,
)
from .config import Config, library_dir, load_config
from .fsm import ChapterState, TransitionError, all_states
from .mdparse import MarkupError
from .paths import Workspace, find_workspace
from .schemas import GoldenTest

app = typer.Typer(
    name="ugar",
    help="КОНВЕЙЕР УГАР — производственный такт главы (ТЗ v1.0).",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _ctx() -> tuple[Workspace, Config, Path]:
    ws = find_workspace()
    cfg = load_config(ws)
    lib = library_dir(ws, cfg)
    guard.set_library_dir(lib)
    return ws, cfg, lib


def _fail(message: str) -> None:
    typer.secho(f"ОШИБКА: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _manual(e: adapters.ManualModeNeeded) -> None:
    typer.secho(f"⚠ {e.reason}", fg=typer.colors.YELLOW)
    typer.echo(f"Ручной режим (NFR-3): {e.hint}")
    raise typer.Exit(code=2)


def _friendly(fn):
    """Ожидаемые ошибки (нет файла, структура MD, недопустимый переход FSM) —
    читаемое сообщение вместо трейсбека."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise  # собственные коды выхода — не ошибка
        except adapters.ManualModeNeeded as e:
            _manual(e)
        except (FileNotFoundError, MarkupError, TransitionError, RuntimeError, ValueError) as e:
            _fail(str(e))

    return wrapper


# ------------------------------------------------------------------ этап 1


@app.command("export", rich_help_panel="Такт главы")
@_friendly
def cmd_export() -> None:
    """Перегенерировать все выгрузки из MD-библиотеки (FR-X1…FR-X3)."""
    ws, cfg, lib = _ctx()
    try:
        hashes = exporter.run_export(lib, ws.exports, ws.logs)
    except MarkupError as e:
        _fail(f"структура MD расходится с соглашениями Д-1 → {e}")
    typer.secho(f"Выгрузки обновлены: {len(hashes)} файлов в {ws.exports}/", fg=typer.colors.GREEN)


@app.command("compile", rich_help_panel="Такт главы")
@_friendly
def cmd_compile(chapter: int) -> None:
    """Собрать окно контекста главы N (FR-C1…FR-C6). Экспорт выполняется автоматически (риск R-5)."""
    ws, cfg, lib = _ctx()
    try:
        exporter.run_export(lib, ws.exports, ws.logs)
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
    if (ws.chapter_dir(chapter) / "window_size_флаг.md").exists() and size > cfg.window_soft_limit_chars:
        typer.secho(
            f"⚠ Превышен мягкий лимит окна {cfg.window_soft_limit_chars} символов (Д-12) — "
            f"раскладка в chapters/{chapter:03d}/window_size_флаг.md",
            fg=typer.colors.YELLOW,
        )


@app.command("write", rich_help_panel="Такт главы")
@_friendly
def cmd_write(chapter: int) -> None:
    """Отправить окно Писателю, сохранить draft_k.md (FR-W1)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("собрано", "сгенерировано")
    k = st.draft + 1
    try:
        writer.write_chapter(ws, cfg, chapter, k)
    except adapters.ManualModeNeeded as e:
        _manual(e)
    st.set_draft(k)
    st.reset_retries()  # свежая генерация — бюджет авто-повторов §5.4 заново
    st.transition("сгенерировано", "write")
    typer.secho(f"Черновик получен: {ws.draft_path(chapter, k)}", fg=typer.colors.GREEN)


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
) -> None:
    """Смысловые проверки Э2 (FR-V2.*)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
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
    """Внесение правок Писателем (FR-W2, FR-E3)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("на-приёмке", "дифф-контроль")
    if not manual and st.data.get("итераций_правок", 0) >= cfg.edit_cycle_max_iterations:
        _fail(
            f"итераций правок уже {st.data['итераций_правок']} (лимит FR-E3) — внесите правки вручную: "
            f"сохраните исправленный текст как draft_{st.draft + 1}.md, выполните "
            f"`ugar apply-edits {chapter} --manual`, затем `ugar diff-check {chapter} --авторская-правка`."
        )
    edits = review_mod.parse_edits_md(ws, chapter)
    st.data["база_правок"] = st.draft
    if manual:
        # завершение сорвавшейся автоматической итерации либо ручная правка автора —
        # бюджет итераций FR-E3 (для циклов Писателя) не расходуется
        new_k = st.draft + 1
        if not ws.draft_path(chapter, new_k).exists():
            _fail(f"нет файла {ws.draft_path(chapter, new_k)} (ручной режим).")
    elif not edits:
        # правок нет — черновик переходит дальше без вызова Писателя
        new_k = st.draft + 1
        shutil.copyfile(ws.draft_path(chapter, st.draft), ws.draft_path(chapter, new_k))
    else:
        try:
            new_k = writer.apply_edits(ws, cfg, chapter, st.draft, edits)
        except adapters.ManualModeNeeded as e:
            typer.echo(
                f"Промпт правок сохранён: chapters/{chapter:03d}/apply_edits_prompt.md — прогоните вручную, "
                f"сохраните ответ как draft_{st.draft + 1}.md и выполните `ugar apply-edits {chapter} --manual`."
            )
            _manual(e)
        st.bump_edit_iterations()  # итерация Писателя состоялась
    st.set_draft(new_k)
    st.transition("правки", "apply-edits")
    typer.secho(f"Правки внесены ({len(edits)} шт.) → draft_{new_k}.md. Далее: `ugar diff-check {chapter}`.", fg=typer.colors.GREEN)


@app.command("diff-check", rich_help_panel="Такт главы")
@_friendly
def cmd_diff_check(
    chapter: int,
    author_fix: bool = typer.Option(
        False, "--авторская-правка", "--author-fix", help="Текущий черновик правил сам автор — расхождения не самоволия."
    ),
) -> None:
    """Дифф-контроль до/после правок (FR-V1.10, FR-E3)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("правки", "дифф-контроль")  # повторный прогон/подтверждение разрешён
    edits = review_mod.load_edits(ws, chapter)
    base = int(st.data.get("база_правок", st.draft - 1))
    report = verifier1.diff_check(ws, chapter, base, st.draft, edits)
    if author_fix and report.unauthorized:
        report.unauthorized = []
        guard.write_text(
            ws.chapter_dir(chapter) / "diff_report.json",
            json.dumps({**report.model_dump(), "примечание": "ручная правка автора"}, ensure_ascii=False, indent=2) + "\n",
        )
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
) -> None:
    """Канонист: пакет записей в канон (FR-K1); применение — только после подписи (FR-K2)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("принято")
    if not apply:
        try:
            path = canonist.build_batch(ws, cfg, chapter, st.draft)
        except RuntimeError as e:
            _fail(str(e))
        typer.secho(f"Пакет на подпись: {path}", fg=typer.colors.GREEN)
        typer.echo(f"Проверьте/поправьте пакет и примените: `ugar canonize {chapter} --apply`.")
        return
    if not (ws.chapter_dir(chapter) / "canon_batch.md").exists():
        _fail(f"нет пакета canon_batch.md — сначала `ugar canonize {chapter}`.")
    if not yes and not typer.confirm(
        f"Применить пакет главы {chapter} к УГАР_Библиотека/ и закоммитить? (Д-8) (y)"
    ):
        raise typer.Exit()
    commit = canonist.apply_batch(ws, cfg, lib, chapter, st.draft)
    st.transition("зафиксировано", "canonize --apply")
    typer.secho(f"Глава {chapter} зафиксирована. Коммит: {commit}", fg=typer.colors.GREEN)


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
) -> None:
    """Состояния глав и следующий шаг (FR-D2); `ugar status N` — карточка главы."""
    ws, cfg, lib = _ctx()
    if chapter is not None:
        _status_detail(ws, chapter)
        return
    states = all_states(ws)
    if not states:
        typer.echo("Глав в работе нет. Начните: `ugar compile N`.")
        return
    typer.echo(f"{'Глава':>6} | {'Состояние':<18} | {'Чернов.':>7} | {'Э1':<16} | {'Э2':<22} | Дальше")
    typer.echo("-" * 110)
    for st in states:
        e1, e2 = _chapter_flags_summary(ws, st.chapter)
        hint = NEXT_STEP.get(st.state, "").format(n=st.chapter)
        typer.echo(f"{st.chapter:>6} | {st.state:<18} | {st.draft:>7} | {e1:<16} | {e2:<22} | {hint}")


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

    if chapter is not None:
        brief = exporter.load_brief(ws.exports, chapter)
        window_path = ws.window_path(chapter)
        window = window_path.read_text(encoding="utf-8") if window_path.exists() else ""
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
        extra_abbr=ws.root / "сокращения.txt",
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
    srv = server_mod.serve(ws, cfg, lib, port)
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


@app.command("snapshot", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_snapshot(volume: int = typer.Argument(1, help="Номер тома.")) -> None:
    """Черновик снапшота тома (реестр 3.5): кто что знает, закладки, хронология."""
    from . import snapshot as snapshot_mod

    ws, cfg, lib = _ctx()
    exporter.run_export(lib, ws.exports, ws.logs)
    path = snapshot_mod.build_snapshot(ws, volume)
    typer.secho(f"Срез тома {volume}: {path}", fg=typer.colors.GREEN)
    typer.echo("Внесите его в библиотеку правкой канона и `ugar canon-commit` (FR-K3 соблюдён).")


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
        item(gitops.is_repo(lib), "библиотека под git", "git init внутри библиотеки (версионирование канона, §5.1)")
        if gitops.is_repo(lib):
            item(gitops.has_identity(lib) or bool(cfg.commit_author), "авторство git настроено",
                 "git config user.email/user.name или commit_author в config.yaml (Д-8)")
            n_remotes = len(gitops.remotes(lib))
            item(n_remotes >= cfg.backup_remotes_min, f"удалённых копий: {n_remotes} (нужно ≥{cfg.backup_remotes_min})",
                 "добавьте git remote (NFR-6)")
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
    green = regression_mod.is_green(ws)
    item(green, "регрессия зелёная" if green is not None else "регрессия ещё не запускалась",
         "`ugar regress`" if green is None else "пропущенные флаги блокируют смену конфигурации (FR-R3)")
    n_tests = len(regression_mod.load_tests(ws)) if ws.regression.exists() else 0
    item(n_tests > 0, f"золотых тестов: {n_tests}", "пополните корпус: `ugar add-golden` (FR-R1)")


@app.command("rollback", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_rollback(
    chapter: int,
    to: str | None = typer.Option(None, "--to", help="Целевое состояние (§5.4); без него — на один шаг назад."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Откат главы в предыдущее состояние (сценарий Г); без --to — на шаг назад по истории."""
    ws, cfg, lib = _ctx()
    if to is None:
        history = ChapterState(ws, chapter).data.get("история", [])
        prev = next((h["из"] for h in reversed(history) if h["из"] != h["в"]), None)
        if prev is None:
            _fail("история главы пуста — укажите цель отката явно: --to <состояние>.")
        to = prev
        typer.echo(f"Откат на шаг назад: → «{to}».")
    st = ChapterState(ws, chapter)
    if st.state == "зафиксировано":
        # только git-revert коммита приёмки с пересчётом выгрузок и корпуса
        sha = gitops.find_chapter_commit(lib, chapter)
        if not sha:
            _fail(f"не найден коммит приёмки главы {chapter} в библиотеке.")
        if not yes and not typer.confirm(f"git revert {sha[:10]} (приёмка главы {chapter}) и пересчёт выгрузок? (y)"):
            raise typer.Exit()
        gitops.revert(lib, sha)
        exporter.run_export(lib, ws.exports, ws.logs)
        st.data["состояние"] = "принято"
        st.data["история"].append(
            {"из": "зафиксировано", "в": "принято", "время": datetime.now(timezone.utc).isoformat(), "команда": "rollback (git revert)"}
        )
        st._save()
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
        typer.secho(f"Регрессия КРАСНАЯ: {report['провалено']} (FR-R3: смена конфигурации заблокирована).", fg=typer.colors.RED)
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
        if state == "не-начато":
            cmd_compile(chapter)
        elif state == "собрано":
            cmd_write(chapter)
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
        if regression_mod.is_green(ws) is not True:
            _fail("фиксация retest запрещена: регрессия не зелёная (FR-R3). Сначала `ugar regress`.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        guard.write_text(
            ws.root / "retest" / stamp / "журнал_запись.md",
            f"# Запись в журнал 3.6 (внесите в библиотеку через правку канона)\n\n"
            f"- Дата: {stamp}\n- Событие: пере-тест моделей, результаты приняты автором.\n"
            f"- Конфигурация: писатель {cfg.writer.model}, верификатор {cfg.verifier2.model}.\n",
        )
        typer.secho(f"Черновик записи журнала: retest/{stamp}/журнал_запись.md — внесите в 3.6 (сценарий Б).", fg=typer.colors.GREEN)
        return
    exporter.run_export(lib, ws.exports, ws.logs)
    _, _ = compiler.compile_window(ws, lib, chapter, cfg.window_soft_limit_chars)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = ws.root / "retest" / stamp
    shutil.copyfile(ws.window_path(chapter), _ensure_dir(dest / "ПРОМПТ_раунд1.md"))
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
    try:
        hashes = exporter.run_export(lib, ws.exports, ws.logs)  # валидация Д-1 + выгрузки
    except MarkupError as e:
        _fail(f"структура MD расходится с соглашениями Д-1 → {e}")
    if (
        old_norms_hash is not None
        and hashes["norms.json"] != old_norms_hash
        and not gitops.check_norm_change_message(message)
    ):
        typer.secho(
            "⚠ Изменены нормы (02 §5), но в сообщении коммита нет ссылки Р-№ на запись "
            "в 36_Журнал — предупреждение, не блокировка (сценарий Б).",
            fg=typer.colors.YELLOW,
        )
    if not gitops.dirty(lib):
        typer.echo("В библиотеке нет изменений — коммитить нечего.")
        return
    if not yes and not typer.confirm(f"Закоммитить изменения библиотеки: «{message}»? (Д-8) (y)"):
        raise typer.Exit()
    commit = gitops.commit_all(lib, message, author=cfg.commit_author)
    typer.secho(f"Канон закоммичен: {commit}", fg=typer.colors.GREEN)


@app.command("backup", rich_help_panel="Канон и бэкап")
@_friendly
def cmd_backup(
    push: bool = typer.Option(False, "--push", help="Отправить библиотеку во все удалённые места (после y)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Проверка свежести бэкапа (NFR-6); --push — отправить во все remotes."""
    ws, cfg, lib = _ctx()
    if not gitops.is_repo(lib):
        _fail("библиотека не под git — инициализируйте репозиторий.")
    remotes = gitops.remotes(lib)
    typer.echo(f"Удалённых мест: {len(remotes)} ({', '.join(remotes) or 'нет'}); требуется ≥{cfg.backup_remotes_min}.")
    if len(remotes) < cfg.backup_remotes_min:
        typer.secho("⚠ Добавьте удалённые репозитории/внешние копии (NFR-6).", fg=typer.colors.YELLOW)
    if gitops.dirty(lib):
        typer.secho("⚠ В библиотеке незакоммиченные изменения (`ugar canon-commit`).", fg=typer.colors.YELLOW)
    age = gitops.last_commit_age_days(lib)
    if age is not None:
        typer.echo(f"Последний коммит: {age:.1f} дн. назад.")
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
