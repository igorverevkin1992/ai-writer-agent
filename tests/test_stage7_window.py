"""Этап 2 второго аудита: «Что было раньше (глазами фокала)», калибровка стиля в окне, хвост прозы вне V1.6."""

from pathlib import Path

import pytest

from ugar import compiler, exporter, guard, verifier1
from ugar.paths import Workspace

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


def _window(ws: Workspace, library: Path, chapter: int) -> str:
    path, _ = compiler.compile_window(ws, library, chapter)
    return path.read_text(encoding="utf-8")


def _section(window: str, start: str, end: str) -> str:
    return window[window.index(start):window.index(end)]


def test_демо_секция_было_раньше(ws, library):
    w1 = _window(ws, library, 1)
    sec = _section(w1, "<!-- СЕКЦИЯ: что было раньше -->", "<!-- СЕКЦИЯ: драматургия -->")
    assert "первая глава фокала" in sec and "ХВОСТ ПРОЗЫ" not in sec
    w5 = _window(ws, library, 5)
    sec = _section(w5, "<!-- СЕКЦИЯ: что было раньше -->", "<!-- СЕКЦИЯ: драматургия -->")
    assert "гл. 1 (" in sec  # событие первой главы того же фокала


@real_only
def test_реальная_библиотека_память_фокала_и_присутствие(real):
    """Лемм в гл. 6 помнит кабинет из гл. 5 (был там); Штерн в гл. 7 не знает о золе в печи Лемма (гл. 6, Лемм один)."""
    w6 = _section(_window(real, LIBRARY, 6), "<!-- СЕКЦИЯ: что было раньше -->", "<!-- СЕКЦИЯ: драматургия -->")
    assert "гл. 1 (" in w6 and "гл. 3 (" in w6 and "гл. 5 (" in w6 and "глазами: Степан" in w6
    assert "зелёным стеклянным абажуром" in w6  # континуити 3.3 из гл. 5 — Лемм присутствовал
    w7 = _section(_window(real, LIBRARY, 7), "<!-- СЕКЦИЯ: что было раньше -->", "<!-- СЕКЦИЯ: драматургия -->")
    assert "золе" not in w7 and "печи" not in w7  # гл. 6: Штерна там не было
    assert "почерк мелкий" in w7  # собственная внешность/манера — видна
    assert "гл. 5 (" not in w7  # в гл. 5 Штерна не было
    # хвост предыдущей главы того же фокала: гл. 4 (макет), без служебных строк
    assert "Как звучал финал предыдущей главы фокала (гл. 4)" in w7
    assert "Конец макета" not in w7 and "---" not in _section(w7, compiler.TAIL_BEGIN, compiler.TAIL_END)
    w8 = _section(_window(real, LIBRARY, 8), "<!-- СЕКЦИЯ: что было раньше -->", "<!-- СЕКЦИЯ: драматургия -->")
    assert "(гл. 5)" in w8 and "Степан опустил глаза" in w8  # принятая гл. 5 — тот же фокал


@real_only
def test_калибровка_стиля_в_окне(real):
    w = _window(real, LIBRARY, 6)
    style = _section(w, "<!-- СЕКЦИЯ: регистр и стиль -->", "<!-- СЕКЦИЯ: фокализация -->")
    assert "Числовые ориентиры для Писателя" in style  # 02 §5 (Р-015)
    assert "6.2." in style and "6.3." in style          # анти-эталоны и эталоны голоса
    assert "постройте круги" not in w                   # инструкции инструменту Писателю не показываются
    assert len(w) < 40_000


@real_only
def test_хвост_прозы_не_считается_утечкой_окна(real):
    """Писатель, повторивший финал предыдущей главы, не получает ложный FLAG V1.6 (окно ≠ промпт в этой части);
    а дословную копию фразы окна вне хвоста V1.6 по-прежнему ловит."""
    w = _window(real, LIBRARY, 8)
    tail = _section(w, compiler.TAIL_BEGIN, compiler.TAIL_END).replace(compiler.TAIL_BEGIN, "").strip()
    brief = exporter.load_brief(real.exports, 8)
    norms = exporter.load_norms(real.exports)
    stops = exporter.load_stoplists(real.exports)
    text = "Утром Степан шёл по Сретенке и думал о вчерашнем. " * 20 + tail
    checks = {c.check_id: c for c in verifier1.analyze(text, w, brief, norms, stops)}
    assert checks["V1.6_утечка_окна"].status == "PASS"
    leak = "Это память фокала, не пересказ для читателя: в прозе всплывает только то, что может всплыть"
    checks = {c.check_id: c for c in verifier1.analyze(text + " " + leak, w, brief, norms, stops)}
    assert checks["V1.6_утечка_окна"].status == "FLAG"
