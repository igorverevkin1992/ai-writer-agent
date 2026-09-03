"""Этап 1 аудита: гарантии ТЗ — FR-C3 (окно без тайн), FR-K2/K3 (git в пределах библиотеки, откат по SHA,
guard для всех потоков), FR-E3 (цикл правок от базы приёмки), защита разметки от flag_id."""

import json
import re
import subprocess
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ugar import compiler, exporter, gitops, guard, realcanon, verifier2
from ugar.cli import app
from ugar.fsm import ChapterState
from ugar.paths import Workspace
from ugar.schemas import Flag, Resolution

REPO = Path(__file__).resolve().parent.parent
LIBRARY = REPO / "УГАР_Библиотека"
real_only = pytest.mark.skipif(not LIBRARY.exists(), reason="реальная библиотека не подключена")


@pytest.fixture
def real(tmp_path):
    (tmp_path / "config.yaml").write_text(f'library_dir: "{LIBRARY}"\n', encoding="utf-8")
    ws = Workspace(tmp_path)
    guard.set_library_dir(LIBRARY)
    exporter.run_export(LIBRARY, ws.exports, ws.logs)
    return ws


# ------------------------------------------------------------------ FR-C3


@real_only
def test_тайны_реестра_разобраны_с_главой_и_знающими(real):
    bans = {b.ban_id: b for b in exporter.load_infobans(real.exports) if b.secret}
    assert bans["Т-06"].until_chapter == 32          # «Часть IV, третья доза» → из матрицы 3.1 (гл.32 / доза №3)
    assert bans["Т-04"].until_chapter == 20          # «улики с гл. 4» — не раскрытие; расчётная разгадка ≈гл.20
    assert bans["Т-10"].until_chapter is None and bans["Т-10"].until_volume == 2
    kb = bans["Т-03"].known_by  # реестр («Степан, куратор; Штерн — с гл. 7; Лемм — с гл. 17») + матрица (Заварзин всегда)
    assert {k: kb[k] for k in ("Степан", "Штерн", "Лемм", "Заварзин")} == {"Степан": 0, "Штерн": 7, "Лемм": 17, "Заварзин": 0}
    assert bans["Т-04"].known_to("Штерн", 4) and bans["Т-06"].known_to("Штерн", 4)  # из матрицы, в реестре не перечислены
    assert bans["Т-05"].known_to("Штерн", 4) and not bans["Т-05"].known_to("Степан", 45)
    assert "сын" in bans["Т-05"].markers


@real_only
def test_частичное_знание_не_раскрывает_факт(real):
    w = compiler.compile_window(real, LIBRARY, 41)[0].read_text(encoding="utf-8")
    assert "фигура холода, без опознания" in w and "присутствовал Мередит" not in w


@real_only
def test_единый_фильтр_запретов_для_э2(real):
    real.chapter_dir(46).mkdir(parents=True, exist_ok=True)
    real.draft_path(46, 1).write_text("Текст.\n", encoding="utf-8")
    _, user = verifier2.build_prompt(real, 46, 1)
    assert "[Т-05]" not in user  # раскрывается в гл. 46 — для Э2 больше не запрет
    assert "[Т-10]" in user      # не раскрывается в томе — запрет действует
    real.draft_path(5, 1).parent.mkdir(parents=True, exist_ok=True)
    real.draft_path(5, 1).write_text("Текст.\n", encoding="utf-8")
    _, user5 = verifier2.build_prompt(real, 5, 1)
    assert "[Т-05]" in user5 and "[Т-03]" not in user5  # Т-03 раскрыта читателю в гл. 2


@real_only
def test_окна_всех_глав_без_тайн_фокала(real):
    """Сканер FR-C3: ни один маркер тайны, неизвестной фокалу, не встречается в секциях
    «персонажи сцены», «что знает фокал», «драматургия» окна; ссылок на будущие тома нет."""
    bans = [b for b in exporter.load_infobans(real.exports) if b.secret]
    briefs = exporter.load_briefs(real.exports)
    leaks: list[str] = []
    for b in briefs:
        w = compiler.compile_window(real, LIBRARY, b.chapter)[0].read_text(encoding="utf-8")
        parts = compiler.SECTION_RE.split(w)
        sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
        scan = "\n".join(sections.get(k, "") for k in ("персонажи сцены", "что знает фокал", "драматургия")).lower()
        for ban in bans:
            if ban.known_to(b.focal, b.chapter):
                continue
            for m in ban.markers:
                if m.lower() in scan:
                    leaks.append(f"гл. {b.chapter} ({b.focal}): {ban.ban_id} «{m}»")
        for fm in re.finditer(r"\bт\.\s*(\d+)|Ф-19\d\d", scan):
            if fm.group(1) is None or int(fm.group(1)) > b.volume:
                leaks.append(f"гл. {b.chapter}: будущий том «{fm.group(0)}»")
    assert not leaks, "\n".join(leaks)


@real_only
def test_досье_в_окне_без_каркаса_и_арок(real):
    w = compiler.compile_window(real, LIBRARY, 5)[0].read_text(encoding="utf-8")
    sec = w.split("## Персонажи сцены")[1].split("<!-- СЕКЦИЯ")[0]
    for bad in ("Призрак", "Ложь героя", "Арка", "Статус:", "Континентал", "завербован сетью", "сын", "т.6", "т.9"):
        assert bad not in sec, bad
    assert "Рожд. ≈1871" in sec and "Речевой паспорт" in sec
    # отношения — только к участникам сцены (Штерна в сцене нет)
    assert "Штерн —" not in sec


# ------------------------------------------------------------- flag_id / XSS


def test_flag_id_только_безопасные_символы():
    with pytest.raises(Exception):
        Flag(flag_id='x" onmouseover="alert(1)', type="т", quote="q", rule="r")
    with pytest.raises(Exception):
        Resolution(flag_id="F-001", decision="канонизировать", target_registry="3.1<script>")
    raw = json.dumps([{"flag_id": 'F"><img src=x onerror=alert(1)>', "type": "т", "quote": "q", "rule": "r",
                       "severity": "важно", "recommendation": "", "kind": "violation"}], ensure_ascii=False)
    flags = verifier2.parse_flags(raw)
    assert flags[0].flag_id == "F-001"


# ------------------------------------------------------------- guard / git


def test_guard_действует_во_всех_потоках(ws, library):
    errors: list[Exception] = []

    def worker():
        try:
            guard.write_text(library / "взлом.md", "x")
        except guard.CanonWriteError as e:
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start(); t.join()
    assert errors and not (library / "взлом.md").exists()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(root: Path) -> None:
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_git_только_в_пределах_библиотеки(ws, library):
    """Библиотека внутри репозитория кода: посторонние файлы не мешают и не попадают в коммит приёмки."""
    _init_repo(ws.root)
    (ws.root / "postoronniy.txt").write_text("вне библиотеки", encoding="utf-8")
    assert not gitops.dirty(library)  # грязь вне библиотеки — не грязь библиотеки
    assert gitops.commit_all(library, "[глава 9] пусто") is None
    (library / "Проза" / "Том1_Глава09.md").write_text("Глава.\n", encoding="utf-8")
    sha = gitops.commit_all(library, "[глава 9] приёмка")
    assert sha and _git(ws.root, "show", "--name-only", "--format=", sha).strip() == "УГАР_Библиотека/Проза/Том1_Глава09.md"
    assert (ws.root / "postoronniy.txt").exists() and "postoronniy" in _git(ws.root, "status", "--porcelain")


def test_откат_не_ревертит_реверт_и_не_трогает_чужие_файлы(ws, library):
    _init_repo(ws.root)
    (library / "Проза" / "Том1_Глава09.md").write_text("Глава.\n", encoding="utf-8")
    sha = gitops.commit_all(library, "[глава 9] приёмка: записей 0")
    gitops.revert(library, sha)
    assert not (library / "Проза" / "Том1_Глава09.md").exists()
    assert gitops.find_chapter_commit(library, 9) == sha  # revert-коммит пропускается
    # коммит, задевающий файл вне библиотеки, откатить нельзя
    (ws.root / "код.py").write_text("x", encoding="utf-8")
    (library / "Проза" / "Том1_Глава09.md").write_text("снова", encoding="utf-8")
    _git(ws.root, "add", "-A"); _git(ws.root, "commit", "-q", "-m", "[глава 9] смешанный")
    mixed = _git(ws.root, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="вне библиотеки"):
        gitops.revert(library, mixed)
    assert (ws.root / "код.py").exists() and not _git(ws.root, "status", "--porcelain")


# ------------------------------------------------------------- FR-E3 база


def test_цикл_правок_стартует_от_базы_приёмки(ws, library, monkeypatch):
    """draft_1 на приёмке → правки дают draft_2 с самоволием → повторный цикл идёт от draft_1, а не от draft_2."""
    monkeypatch.chdir(ws.root)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    runner = CliRunner()
    n = 1
    st = ChapterState(ws, n)
    ws.chapter_dir(n).mkdir(parents=True, exist_ok=True)
    ws.draft_path(n, 1).write_text("Первая фраза. Вторая фраза. Третья фраза.\n", encoding="utf-8")
    for state, cmd in (("собрано", "compile"), ("сгенерировано", "write"), ("верифицировано-1", "verify1"), ("верифицировано-2", "verify2")):
        st.transition(state, cmd)
    st.data["черновик"] = 1; st._save()
    from ugar import verifier1
    ws.chapter_dir(n).joinpath("verdict.json").write_text(json.dumps({"chapter": 1, "draft": 1, "checks": []}), encoding="utf-8")
    ws.chapter_dir(n).joinpath("flags.json").write_text("[]", encoding="utf-8")
    assert runner.invoke(app, ["review", str(n)]).exit_code == 0
    assert ChapterState(ws, n).data["база_приёмки"] == 1
    (ws.chapter_dir(n) / "edits.md").write_text("БЫЛО: Вторая фраза.\nСТАЛО: Другая фраза.\n", encoding="utf-8")
    # «Писатель» вносит правку и добавляет самоволие
    calls: list[int] = []

    def fake_apply(ws_, cfg, chapter, base_k, edits, new_k=None):
        calls.append(base_k)
        text = ws_.draft_path(chapter, base_k).read_text(encoding="utf-8").replace("Вторая фраза.", "Другая фраза.")
        text = text.replace("Третья фраза.", "Третья фраза. Самовольная вставка.")
        from ugar import writer
        writer._save_draft(ws_, chapter, new_k, text, cfg, mode="правки")
        return new_k

    from ugar import writer
    monkeypatch.setattr(writer, "apply_edits", fake_apply)
    assert runner.invoke(app, ["apply-edits", str(n)]).exit_code == 0
    r = runner.invoke(app, ["diff-check", str(n)])
    assert "Самовольные" in r.output
    # второй цикл: автор поправил edits.md; база — по-прежнему draft_1
    assert runner.invoke(app, ["apply-edits", str(n)]).exit_code == 0
    assert calls == [1, 1]
    r = runner.invoke(app, ["diff-check", str(n)])
    assert "Самовольные" in r.output  # самоволие видно и во втором цикле, не «отмыто»
    assert ChapterState(ws, n).draft == 3




def test_откат_зафиксированной_главы_по_sha_из_статуса(ws, library, monkeypatch):
    """canonize --apply пишет SHA в status.yaml; rollback ревертит его; повторный откат невозможен."""
    from ugar import canonist, review
    from ugar.config import Config

    monkeypatch.chdir(ws.root)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _init_repo(library)
    chapter = 1
    compiler.compile_window(ws, library, chapter)
    st = ChapterState(ws, chapter)
    st.transition("собрано", "compile")
    ws.draft_path(chapter, 1).parent.mkdir(parents=True, exist_ok=True)
    ws.draft_path(chapter, 1).write_text("Каширин нашёл записку утром возле хлебницы.", encoding="utf-8")
    st.set_draft(1)
    for state, cmd in (("сгенерировано", "write"), ("верифицировано-1", "verify1"), ("верифицировано-2", "verify2")):
        st.transition(state, cmd)
    verifier2.save_flags(ws, chapter, [])
    review.build_review_pack(ws, chapter, 1)
    st.transition("на-приёмке", "review")
    review.save_edits(ws, chapter, [])
    import shutil
    shutil.copyfile(ws.draft_path(chapter, 1), ws.draft_path(chapter, 2))
    st.set_draft(2)
    st.transition("правки", "apply-edits")
    from ugar import verifier1
    verifier1.diff_check(ws, chapter, 1, 2, [])
    st.transition("дифф-контроль", "diff-check")
    st.transition("принято", "accept")
    canonist.build_batch(ws, Config(), chapter, 2)

    runner = CliRunner()
    r = runner.invoke(app, ["canonize", str(chapter), "--apply", "-y"])
    assert r.exit_code == 0, r.output
    st = ChapterState(ws, chapter)
    sha = st.data["коммит_приёмки"]
    assert st.state == "зафиксировано" and sha == gitops.head(library)
    assert (library / "Проза" / "Том1_Глава01.md").exists()

    r = runner.invoke(app, ["rollback", str(chapter), "-y"])
    assert r.exit_code == 0, r.output
    st = ChapterState(ws, chapter)
    assert st.state == "принято" and "коммит_приёмки" not in st.data
    assert not (library / "Проза" / "Том1_Глава01.md").exists()
    # повторный откат из «принято» — обычный FSM-откат, реверт реверта невозможен
    r = runner.invoke(app, ["rollback", str(chapter), "--to", "собрано", "-y"])
    assert r.exit_code == 0, r.output
    assert not (library / "Проза" / "Том1_Глава01.md").exists()
    assert gitops.find_chapter_commit(library, chapter) == sha
