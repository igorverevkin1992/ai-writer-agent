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


@app.command("export")
@_friendly
def cmd_export() -> None:
    """Перегенерировать все выгрузки из MD-библиотеки (FR-X1…FR-X3)."""
    ws, cfg, lib = _ctx()
    try:
        hashes = exporter.run_export(lib, ws.exports, ws.logs)
    except MarkupError as e:
        _fail(f"структура MD расходится с соглашениями Д-1 → {e}")
    typer.secho(f"Выгрузки обновлены: {len(hashes)} файлов в {ws.exports}/", fg=typer.colors.GREEN)


@app.command("compile")
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


@app.command("write")
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
    st.transition("сгенерировано", "write")
    typer.secho(f"Черновик получен: {ws.draft_path(chapter, k)}", fg=typer.colors.GREEN)


def _print_verdict(verdict) -> None:
    for c in verdict.checks:
        color = {"PASS": typer.colors.GREEN, "FLAG": typer.colors.YELLOW, "BRAK": typer.colors.RED}[c.status]
        typer.secho(f"  [{c.status}] {c.check_id}: {c.actual} (порог: {c.threshold})", fg=color)


@app.command("verify1")
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


@app.command("verify2")
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


@app.command("review")
@_friendly
def cmd_review(chapter: int) -> None:
    """Пакет приёмки автора: review.md + edits.md + resolutions.json (FR-E1)."""
    ws, cfg, lib = _ctx()
    st = ChapterState(ws, chapter)
    st.require("верифицировано-2")
    path = review_mod.build_review_pack(ws, chapter, st.draft)
    st.transition("на-приёмке", "review")
    typer.secho(f"Пакет приёмки: {path}", fg=typer.colors.GREEN)
    typer.echo(
        "Дальше: правки — в edits.md; решения по самоволкам — в resolutions.json "
        "(«вычеркнуть»|«канонизировать»); затем `ugar apply-edits N`."
    )


@app.command("apply-edits")
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
    st.bump_edit_iterations()
    st.data["база_правок"] = st.draft
    if manual:
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
    st.set_draft(new_k)
    st.transition("правки", "apply-edits")
    typer.secho(f"Правки внесены ({len(edits)} шт.) → draft_{new_k}.md. Далее: `ugar diff-check {chapter}`.", fg=typer.colors.GREEN)


@app.command("diff-check")
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
    st.require("правки")
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
    if report.unauthorized:
        typer.secho(f"Самовольные изменения ({len(report.unauthorized)}):", fg=typer.colors.RED)
        for u in report.unauthorized[:10]:
            typer.echo(f"  > {u[:200]}")
        typer.echo(f"Цикл повторяется: поправьте edits.md и выполните `ugar apply-edits {chapter}` (≤{cfg.edit_cycle_max_iterations} итераций).")
    elif report.not_applied:
        typer.secho("Часть правок не внесена — повторите цикл.", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"Дифф-контроль чист. Далее: `ugar accept {chapter}`.", fg=typer.colors.GREEN)


@app.command("accept")
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


@app.command("canonize")
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


@app.command("status")
@_friendly
def cmd_status() -> None:
    """Таблица глав и состояний FSM (FR-D2)."""
    ws, cfg, lib = _ctx()
    states = all_states(ws)
    if not states:
        typer.echo("Глав в работе нет.")
        return
    typer.echo(f"{'Глава':>6} | {'Состояние':<18} | {'Черновик':>8} | Авто-повт. | Итер. правок")
    typer.echo("-" * 66)
    for st in states:
        typer.echo(
            f"{st.chapter:>6} | {st.state:<18} | {st.draft:>8} | "
            f"{st.data.get('авто_повторов', 0):>10} | {st.data.get('итераций_правок', 0)}"
        )


@app.command("rollback")
@_friendly
def cmd_rollback(
    chapter: int,
    to: str = typer.Option(..., "--to", help="Целевое состояние (из §5.4)."),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Откат главы в предыдущее состояние (сценарий Г)."""
    ws, cfg, lib = _ctx()
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


@app.command("regress")
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


@app.command("add-golden")
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


@app.command("dashboard")
@_friendly
def cmd_dashboard() -> None:
    """Собрать dashboard.html (FR-D1)."""
    ws, cfg, lib = _ctx()
    path = dashboard_mod.build_dashboard(ws)
    typer.secho(f"Дашборд: {path}", fg=typer.colors.GREEN)


@app.command("run")
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


@app.command("retest")
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


@app.command("canon-commit")
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


@app.command("backup")
@_friendly
def cmd_backup() -> None:
    """Напоминание/проверка свежести бэкапа (NFR-6): минимум два удалённых места."""
    ws, cfg, lib = _ctx()
    if not gitops.is_repo(lib):
        _fail("библиотека не под git — инициализируйте репозиторий.")
    remotes = gitops.remotes(lib)
    typer.echo(f"Удалённых мест: {len(remotes)} ({', '.join(remotes) or 'нет'}); требуется ≥{cfg.backup_remotes_min}.")
    if len(remotes) < cfg.backup_remotes_min:
        typer.secho("⚠ Добавьте удалённые репозитории/внешние копии (NFR-6).", fg=typer.colors.YELLOW)
    if gitops.dirty(lib):
        typer.secho("⚠ В библиотеке незакоммиченные изменения.", fg=typer.colors.YELLOW)
    age = gitops.last_commit_age_days(lib)
    if age is not None:
        typer.echo(f"Последний коммит: {age:.1f} дн. назад.")


@app.command("init")
@_friendly
def cmd_init() -> None:
    """Создать каркас рабочей области: config.yaml, .env.example, папки (NFR-1)."""
    ws = Workspace(Path.cwd())
    if not (ws.root / "config.yaml").exists():
        shutil.copyfile(Path(__file__).parent / "data" / "config.example.yaml", ws.root / "config.yaml")
    for d in (ws.exports, ws.chapters, ws.logs, ws.templates, ws.regression / "golden"):
        d.mkdir(parents=True, exist_ok=True)
    env_example = ws.root / ".env.example"
    if not env_example.exists():
        env_example.write_text("GEMINI_API_KEY=\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    typer.secho("Рабочая область готова. Заполните config.yaml и .env (Д-9), положите УГАР_Библиотека/.", fg=typer.colors.GREEN)


def main() -> None:  # точка входа для python -m ugar.cli
    app()


if __name__ == "__main__":
    main()
