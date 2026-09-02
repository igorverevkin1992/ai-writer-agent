"""Реальная библиотека канона «УГАР» (УГАР_Библиотека/ в репозитории): парсер под канон (Д-1).

Проверяет критерий приёмки этапа 1 на живых данных: окно главы 5, собранное
`compile`, семантически эквивалентно эталону v1.1 (Тест_Писателя/ПРОМПТ_Глава5.md);
калибровка счётчиков на реальном макете гл. 4 (10.1).
"""

import re
import shutil
from pathlib import Path

import pytest

from ugar import compiler, exporter, guard, textutils, verifier1
from ugar.paths import Workspace

REPO = Path(__file__).resolve().parent.parent
LIBRARY = REPO / "УГАР_Библиотека"

pytestmark = pytest.mark.skipif(not LIBRARY.exists(), reason="реальная библиотека не подключена")


@pytest.fixture
def real(tmp_path):
    (tmp_path / "config.yaml").write_text(f'library_dir: "{LIBRARY}"\n', encoding="utf-8")
    ws = Workspace(tmp_path)
    guard.set_library_dir(LIBRARY)
    exporter.run_export(LIBRARY, ws.exports, ws.logs)
    return ws


def test_нормы_из_прозы_регламента(real):
    norms = exporter.load_norms(real.exports)
    n = norms["средняя_длина"]
    assert (n.min, n.max, n.brak) == (9, 12, 7) and "Р-015" in n.source
    assert norms["доля_коротких"].min == 0.30 and norms["доля_коротких"].max == 0.45
    assert norms["был_на_250"].max == 1 and norms["ttr_мин"].min == 0.46
    assert norms["усилители_на_1000"].max == 2 and "Р-016" in norms["усилители_на_1000"].source
    assert "ТЗ" in norms["утечка_нграмма"].source  # порог из ТЗ, пока канон не переопределил


def test_поглавник_всего_тома(real):
    briefs = exporter.load_briefs(real.exports)
    assert len(briefs) == 46 and all(b.year == 1926 and b.volume == 1 for b in briefs)
    b5 = exporter.load_brief(real.exports, 5)
    assert b5.focal == "Степан" and "18.04" in b5.date
    assert b5.scenes and "кабинет Лемма" in b5.scenes[0] and "Лемм" in b5.participants
    assert exporter.load_brief(real.exports, 22).focal == "Лемм"  # «Заварзин глазами Лемма»
    assert not any("Читатель узнаёт" in beat for beat in b5.beats)  # мета читателя Писателю не идёт


def test_стоп_листы_и_усилители(real):
    stop = exporter.load_stoplists(real.exports)
    stern = [r for r in stop if r.applies_to.get("focal") == "Штерн"]
    assert stern and set(stern[0].items) == {"отец", "сын", "семья", "папа"}  # без «Разрешено»
    dated = {w: r.applies_to["year"]["before"] for r in stop if "year" in r.applies_to for w in r.items}
    assert dated["пятилетка"] == 1928 and dated["стахановец"] == 1935
    forever = {w for r in stop if r.scope == "0.4" and r.kind == "лексика" and "all" in r.applies_to for w in r.items}
    assert {"стукач", "разборка", "беспредел"} <= forever and not any("любые" in w for w in forever)
    ints = [r for r in stop if r.kind == "усилитель"]
    assert ints and "предельно" in ints[0].items


def test_матрица_закладки_тайны_досье(real):
    matrix = exporter.load_matrix(real.exports)
    stepan_knows = {f.fact_id for f in matrix if f.subject == "Степан" and f.from_chapter is not None and f.from_chapter <= 5}
    assert stepan_knows == {"М-04"}
    lemm = {f.fact_id: f.from_chapter for f in matrix if f.subject == "Лемм"}
    assert lemm["М-01"] == 0 and lemm["М-02"] == 3 and lemm["М-14"] is None

    plants = exporter.load_plants(real.exports)
    zola = next(p for p in plants if "золе" in p.what)
    assert zola.chapters == [6] and {"vol": 6} in zola.fires
    ch4 = {p.what.split(" (")[0] for p in plants if 4 in p.chapters}
    assert ch4 == {"часы", "почтовый канал"}                 # из «Закладки положены» поглавника
    assert not any("картотека" in p.what and p.plant_id.startswith("П-") for p in plants)  # дедуп с §7

    bans = exporter.load_infobans(real.exports)
    assert len(bans) == 10 and all(b.secret for b in bans)
    assert next(b for b in bans if "сын Лемма" in b.text).until_chapter == 46

    names = sorted(d.name for d in exporter.load_dossiers(real.exports))
    assert names == ["Ася", "Бугаев", "Заварзин", "Ковров", "Лемм", "Мередит", "Ольга", "Ремез", "Степан", "Штерн"]
    lemm_d = next(d for d in exporter.load_dossiers(real.exports) if d.name == "Лемм")
    assert "Штерн" in lemm_d.relations and "на «Вы»" in lemm_d.speech


def test_окно_главы_5_эквивалентно_эталону(real):
    """Критерий этапа 1: разделы эталона v1.1 присутствуют, тайны не утекают."""
    path, breakdown = compiler.compile_window(real, LIBRARY, 5)
    w = path.read_text(encoding="utf-8")
    etalon = (LIBRARY / "Тест_Писателя/ПРОМПТ_Глава5.md").read_text(encoding="utf-8")
    # 1. регистр и стиль — из 02 (разделы 1–4, 6.1) и нормы
    assert "Идиоматическая естественность выше образности" in w and "средняя_длина" in w
    # 2. фокализация — общие законы и линия
    assert "Одна сцена — одна голова" in w and "Фокал: Степан" in w
    # 3. персонажи сцены — досье участников
    assert "### Степан" in w and "### Лемм" in w and "### Штерн" not in w
    # 4. что знает фокал — только доступное; содержание тайн не раскрыто (FR-C3)
    assert "М-04" in w and "сын Лемма" not in w and "Подлог 1913" not in w
    # 5. бриф — сцена из поглавника
    assert "обыск стола по приказу куратора" in w
    # 6. формат выдачи и СТРОГО ЗАПРЕЩЕНО
    assert "СТРОГО ЗАПРЕЩЕНО" in w and "Формат выдачи" in w
    # лексика эпохи и усилители из эталона доступны Писателю
    for word in ("пятилетка", "стукач", "разборка", "предельно"):
        assert word in w, word
    assert len(w) < 80_000
    # детерминизм на реальных данных
    assert compiler.compile_window(real, LIBRARY, 5)[0].read_text(encoding="utf-8") == w
    assert "550" in etalon and "700–800 слов" in w  # объём: эталон 550–800, канон Р-019 700–800


def test_калибровка_реального_макета(real):
    """10.1: ожидаемые ТЗ ≈592 слова, средняя ≈7,2 (±0,2), ≤6 ≈51%, «был» 2 — замер на файле макета."""
    raw = (LIBRARY / "Проза/Том1_Глава04_МАКЕТ.md").read_text(encoding="utf-8")
    text = textutils.narrator_text(raw)
    lens = textutils.sentence_lengths(text)
    tokens = textutils.normalize(text)
    avg = sum(lens) / len(lens)
    assert 585 <= len(tokens) <= 620
    assert abs(avg - 7.2) <= 0.2
    assert 0.45 <= sum(1 for x in lens if x <= 6) / len(lens) <= 0.53
    assert sum(1 for t in tokens if t in {"был", "было"}) == 4  # был 1 + было 3 (файл макета v2)
    assert "Статус: на приёмке" not in text  # заголовки-метаданные исключены


def test_э1_по_принятой_главе_5(real):
    """Принятая гл. 5 (Р-018) против норм Р-015: Э1 честно показывает расхождение."""
    (real.chapter_dir(5)).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LIBRARY / "Проза/Том1_Глава05.md", real.draft_path(5, 1))
    compiler.compile_window(real, LIBRARY, 5)
    verdict = verifier1.run_verify1(real, 5, 1)
    by_id = {c.check_id: c for c in verdict.checks}
    assert by_id["V1.2a_средняя_длина"].status == "BRAK"       # 5,8 < 7 — телеграф по Р-015
    assert by_id["V1.4_усилители"].status == "FLAG"            # «предельно ясно» и др.
    assert by_id["V1.5_стоп_лексика"].status == "PASS"
    assert by_id["V1.6_утечка_окна"].status == "PASS"
    assert by_id["V1.2e_объём"].status == "PASS"               # 752 слова в коридоре 700–800 (Р-019)
    assert "700" in by_id["V1.2e_объём"].threshold
