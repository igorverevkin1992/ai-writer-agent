"""Разбор фактической структуры библиотеки «УГАР» (Д-1: парсер пишется под канон).

Реальный канон хранит нормы и правила в прозе и смешанных форматах:
- 02: числовые ориентиры — абзацем в §5 (уточнены Р-015);
- 03: лексические стоп-листы линий — в «Персональных запретах линий»;
- 04: анахронизмы — раздел Е, элементы через « · » с годами в скобках;
- 36: словарь наречий-усилителей — внутри решения Р-016(г);
- реестр информрежима: постраничная сетка (поглавник тома), реестр тайн,
  §7 — реестр дальних закладок;
- 31: широкая матрица (колонки — субъекты);
- 33: континуити — буллеты «факт · т.X гл.Y · статус»;
- досье: несколько карточек «# Досье 1.3: ИМЯ» в одном файле.

Табличные форматы демо-библиотеки остаются поддержанными в exporter;
сюда вынесены ветки реального формата.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import mdparse
from .mdparse import MarkupError, cell
from .schemas import Act, Brief, CircleStep, ContinuityEvent, Dossier, InfoBan, MatrixFact, Norm, Plant, StopRule, StoryCircle

CH_RE = re.compile(r"[Гг]л\.?\s*(\d+)")
VOL_RE = re.compile(r"[Тт]ом\w*\s*(\d+)|т\.?\s*(\d+)")


# ------------------------------------------------------------------ нормы 02


def parse_norms_prose(path: Path) -> dict[str, Norm] | None:
    """Числовые ориентиры из прозы §5 стилевого регламента (Р-015)."""
    text = path.read_text(encoding="utf-8")
    if "Числовые ориентиры" not in text:
        return None
    src = f"{path.name} §5 (Р-015)"
    norms: dict[str, Norm] = {}

    m = re.search(r"средняя фраза\s*(\d+)\s*[–-]\s*(\d+)\s*слов", text)
    b = re.search(r"средняя ниже\s*(\d+)\s*[—-]+\s*брак", text)
    if not m:
        raise MarkupError(path, 1, "в «Числовых ориентирах» не найден коридор средней фразы")
    norms["средняя_длина"] = Norm(
        min=float(m.group(1)), max=float(m.group(2)),
        brak=float(b.group(1)) if b else None, unit="слов", source=src,
    )

    m = re.search(r"короткие\s*\(≤\s*(\d+)\)\s*[—-]+\s*(\d+)\s*[–-]\s*(\d+)\s*%", text)
    if not m:
        raise MarkupError(path, 1, "не найдена доля коротких фраз")
    norms["короткая_фраза_порог"] = Norm(min=float(m.group(1)), max=float(m.group(1)), unit="слов", source=src)
    norms["доля_коротких"] = Norm(min=int(m.group(2)) / 100, max=int(m.group(3)) / 100, unit="доля", source=src)

    m = re.search(r"длинные\s*\(≥\s*(\d+)\)\s*[—-]+\s*до\s*(\d+)\s*%", text)
    if not m:
        raise MarkupError(path, 1, "не найдена доля длинных фраз")
    norms["длинная_фраза_порог"] = Norm(min=float(m.group(1)), max=float(m.group(1)), unit="слов", source=src)
    norms["доля_длинных"] = Norm(max=int(m.group(2)) / 100, unit="доля", source=src)

    m = re.search(r"«был/было»\s*[—-]+\s*не чаще\s*(\d+)\s*на\s*(\d+)\s*слов", text)
    if not m:
        raise MarkupError(path, 1, "не найдена норма «был/было»")
    norms["был_на_250"] = Norm(max=float(m.group(1)) * 250 / float(m.group(2)), unit="шт/250 слов", source=src)

    m = re.search(r"TTR\s*≥\s*([\d.,]+)\s*на окне\s*(\d+)\s*тыс", text)
    if not m:
        raise MarkupError(path, 1, "не найдена норма TTR")
    norms["ttr_мин"] = Norm(min=float(m.group(1).replace(",", ".")), unit="доля", source=src)
    norms["ttr_окно_слов"] = Norm(min=float(m.group(2)) * 1000, max=float(m.group(2)) * 1000, unit="слов", source=src)

    m = re.search(r"объём главы\s*[—-]+\s*(\d+)\s*[–-]\s*(\d+)\s*слов", text)
    if m:  # необязательная норма (Р-019)
        norms["объём_главы"] = Norm(min=float(m.group(1)), max=float(m.group(2)), unit="слов", source=src)
    return norms


def parse_intensifier_norm(journal: Path) -> tuple[list[str], Norm] | None:
    """Р-016(г): словарь наречий-усилителей и порог «>N на тысячу слов»."""
    if not journal.exists():
        return None
    text = journal.read_text(encoding="utf-8")
    m = re.search(r"усилителей\s*\(([^)]*)\)", text)
    if not m:
        return None
    words = re.findall(r"«([^»]+)»", m.group(1))
    thr = re.search(r">\s*(\d+)\s*на тысячу", m.group(1))
    if not words or not thr:
        return None
    return words, Norm(max=float(thr.group(1)), unit="шт/1000 слов", source=f"{journal.name} Р-016(г)")


# --------------------------------------------------------- стоп-листы 03/04


def focal_names(path: Path) -> set[str]:
    """Имена линий из 03: заголовки «**Имя…**» персональных запретов и таблица фокалов."""
    names: set[str] = set()
    sections = mdparse.parse_sections(path)
    sec = mdparse.find_section(sections, r"[Пп]ерсональные запреты")
    if sec:
        for line in sec.body.splitlines():
            m = re.match(r"\*\*([А-ЯЁ][а-яё]+)", line.strip())
            if m:
                names.add(m.group(1))
    for table in mdparse.parse_tables(path):
        if any("Фокальные" in h for h in table.headers):
            for row in table.rows:
                for cell_text in row.values():
                    names.update(re.findall(r"\b([А-ЯЁ][а-яё]{2,})\b", cell_text))
    return names - {"Тома", "Без", "Открывается"}


def parse_focal_stoplists(path: Path) -> list[StopRule]:
    """«Персональные запреты линий»: строки со «стоп-лист» → слова в «кавычках»."""
    sec = mdparse.find_section(mdparse.parse_sections(path), r"[Пп]ерсональные запреты")
    if sec is None:
        return []
    rules: list[StopRule] = []
    focal = ""
    for line in sec.body.splitlines():
        header = re.match(r"\*\*([А-ЯЁ][а-яё]+)", line.strip())
        if header:
            focal = header.group(1)
        if "стоп-лист" in line.lower() and focal:
            forbidden_part = re.split(r"[Рр]азрешен", line)[0]  # после «Разрешено:» — не запреты
            words = re.findall(r"«([^»]+)»", forbidden_part)
            if words:
                rules.append(
                    StopRule(
                        scope="0.3", rule_id=f"0.3-{focal}", items=words,
                        applies_to={"focal": focal}, action="запрет",
                    )
                )
    return rules


def _clean_item(item: str) -> list[str]:
    """Элемент стоп-листа: убрать пояснения/маркеры, разбить перечисления."""
    item = re.sub(r"\(.*?\)", "", item)               # скобочные пояснения
    item = re.sub(r"[✓⚠🔧].*$", "", item)             # статусные маркеры и хвосты
    item = re.split(r"\s+как\s+", item)[0]            # «вредитель как штамп»
    words = []
    for piece in re.split(r"[,/]", item):
        piece = piece.strip(" .;:—-").strip()
        # описательные обороты («любые кальки телепроцедурала») — не лексические единицы
        if piece and not piece.startswith("«") and len(piece) > 1 and len(piece.split()) <= 3 \
                and not piece.lower().startswith("любые"):
            words.append(piece.strip("«»"))
    return words


def parse_anachronisms(path: Path) -> list[StopRule]:
    """Раздел Е языкового канона: «Запрещено до года» и «Запрещено навсегда»."""
    sec = mdparse.find_section(mdparse.parse_sections(path), r"[Сс]топ-лист анахронизмов")
    if sec is None:
        return []
    rules: list[StopRule] = []
    for line in sec.body.splitlines():
        line = line.strip()
        forever = line.startswith("**Запрещено навсегда")
        dated = line.startswith("**Запрещено до")
        if not (forever or dated):
            continue
        payload = line.split(":**", 1)[-1]
        for i, raw_item in enumerate(payload.split("·")):
            year_m = re.search(r"до\s+(\d{4})", raw_item)
            words = _clean_item(raw_item)
            if not words:
                continue
            applies: dict = {"all": True}
            if dated and year_m:
                applies = {"year": {"before": int(year_m.group(1))}}
            rules.append(
                StopRule(
                    scope="0.4",
                    rule_id=f"0.4-Е-{'нав' if forever else 'год'}-{i + 1}",
                    items=words, applies_to=applies, action="запрет",
                )
            )
    return rules


# ------------------------------------------------- поглавник (реестр + 23)


def registry_year_volume(path: Path) -> tuple[int | None, int]:
    head = path.read_text(encoding="utf-8")[:200]
    y = re.search(r"\((\d{4})\)", head)
    v = re.search(r"Том\s*(\d+)", head)
    return (int(y.group(1)) if y else None, int(v.group(1)) if v else 1)


def normalize_name(raw: str, known_names: set[str]) -> str:
    """«Лемма» (глазами Лемма) → «Лемм»: известное имя, являющееся префиксом слова."""
    word = raw.split()[0] if raw else ""
    for name in sorted(known_names, key=len, reverse=True):
        if word.lower().startswith(name.lower()):
            return name
    return word


def parse_registry_briefs(path: Path, known_names: set[str] | None = None) -> list[Brief]:
    """Постраничная сетка реестра: | Гл. | Фокал | Дата | Событие | … | на весь том."""
    year, volume = registry_year_volume(path)
    known_names = known_names or set()
    briefs: list[Brief] = []
    for table in mdparse.parse_tables(path):
        headers = [h.lower() for h in table.headers]
        if not any("фокал" in h for h in headers) or not any("гл" in h for h in headers):
            continue
        for row in table.rows:
            ch = mdparse.parse_number(cell(row, "Гл"))
            if ch is None:
                continue
            focal = cell(row, "Фокал")
            eyes = re.search(r"глазами\s+([А-ЯЁ][а-яё]+)", focal)
            if eyes:
                focal = eyes.group(1)
            event = cell(row, "Событие")
            briefs.append(
                Brief(
                    chapter=int(ch), volume=volume, year=year,
                    focal=normalize_name(focal, known_names),
                    date=cell(row, "Дата"),
                    beats=[event] if event else [],
                    scenes=[],
                    not_knows=[],
                    bans=[],
                    participants=[],
                    volume_words=None,
                    plants=[],
                )
            )
    return briefs


POGLAVNIK_HEAD_RE = re.compile(r"##\s*Гл\.?\s*(\d+)\s*·\s*([^·]+)·\s*фокал\s+([А-ЯЁ]+)", re.IGNORECASE)
SCENE_RE = re.compile(r"\*\*Сц\.\s*[\d.]+\.?\*\*\s*(.+)")


def enrich_from_poglavnik(briefs: list[Brief], path: Path, known_names: set[str]) -> None:
    """Обогащение брифов сценами и участниками из рабочего поглавника (23)."""
    by_ch = {b.chapter: b for b in briefs}
    current: Brief | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = POGLAVNIK_HEAD_RE.match(line.strip())
        if m:
            current = by_ch.get(int(m.group(1)))
            continue
        sm = SCENE_RE.match(line.strip())
        if sm and current is not None:
            scene = sm.group(1)
            parts = [p.strip() for p in scene.split("·")]
            current.scenes.append(" · ".join(parts[:3]))
            participants = {
                name for name in known_names
                if len(parts) > 1 and re.search(rf"(?<![А-Яа-яЁё]){name}", parts[1])
            }
            for name in sorted(participants):
                if name not in current.participants and name != current.focal:
                    current.participants.append(name)
            for chunk in parts:
                if chunk.lower().startswith("кладём"):
                    current.beats.append(chunk)


# ------------------------------------------------------------- матрица 31


def parse_wide_matrix(path: Path) -> list[MatrixFact]:
    """Широкая матрица: строки — факты, колонки — субъекты."""
    for table in mdparse.parse_tables(path):
        if "Факт" not in table.headers or len(table.headers) < 5:
            continue
        subject_cols = [h for h in table.headers if h not in ("#", "Факт")]
        facts: list[MatrixFact] = []
        for row in table.rows:
            num = mdparse.parse_number(row.get("#", "")) or len(facts) + 1
            fact_text = row.get("Факт", "")
            for subj in subject_cols:
                raw = row.get(subj, "").strip()
                if not raw:
                    continue
                # курсив *…* = частичное/неверное знание; жирный **…** — просто выделение
                partial = raw.startswith("*") and raw.endswith("*") and not raw.startswith("**")
                clean = raw.strip("*").strip()
                if clean in ("—", "-", ""):
                    from_ch: int | None = None
                elif clean.lower().startswith("всегда") or clean.lower().startswith("пролог"):
                    from_ch = 0
                elif subj == "Читатель":
                    from_ch = reveal_chapter(clean)  # «улики с гл.4; расчётная разгадка ≈гл.20» → 20
                else:
                    chm = CH_RE.search(clean)
                    from_ch = int(chm.group(1)) if chm else None
                source = clean.split("/", 1)[1].strip() if "/" in clean else ""
                facts.append(
                    MatrixFact(
                        fact_id=f"М-{int(num):02d}",
                        fact=fact_text,
                        subject=subj,
                        from_chapter=from_ch,
                        source=source,
                        note=("частично/неверно: " + clean) if partial else ("" if from_ch is not None else clean),
                    )
                )
        if facts:
            return facts
    raise MarkupError(path, 1, "не найдена матрица (широкая таблица с колонкой «Факт»)")


# ---------------------------------------------------------- закладки (§7)


def parse_plants_registry(path: Path) -> list[Plant]:
    """§7 реестра: | Закладка | Где лежит | Где стреляет |."""
    _, volume = registry_year_volume(path)
    plants: list[Plant] = []
    for table in mdparse.parse_tables(path):
        headers = " ".join(table.headers).lower()
        if "закладка" not in headers or "стреляет" not in headers:
            continue
        for i, row in enumerate(table.rows, start=1):
            placed_raw = cell(row, "лежит")
            chapters = [int(x) for x in CH_RE.findall(placed_raw)]
            if re.search(r"[Пп]ролог", placed_raw):
                chapters.insert(0, 0)
            fires = []
            for vm in VOL_RE.finditer(cell(row, "стреляет")):
                vol = int(vm.group(1) or vm.group(2))
                fires.append({"vol": vol})
            plants.append(
                Plant(
                    plant_id=f"З-{i:02d}",
                    what=cell(row, "Закладка"),
                    placed={"vol": volume, "ch": chapters[0]} if chapters else {"vol": volume},
                    chapters=chapters,
                    fires=fires,
                    status=placed_raw if not chapters else "",
                )
            )
    return plants


# ------------------------------------------------------- континуити 33


def parse_continuity_bullets(path: Path) -> list[ContinuityEvent]:
    """Буллеты «факт · т.X гл.Y · статус» по секциям трекера."""
    events: list[ContinuityEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("·")]
        if len(parts) < 2:
            continue
        chapters = "; ".join(p for p in parts[1:] if re.search(r"т\.?\s*\d|гл", p))
        events.append(
            ContinuityEvent(
                date="",
                event=re.sub(r"\*\*", "", parts[0]),
                chapters=re.sub(r"\*\*", "", chapters),
                note=parts[-1] if len(parts) > 2 else "",
            )
        )
    return events


# ------------------------------------------------------ информрежим (тайны)


def reveal_chapter(text: str) -> int | None:
    """Глава раскрытия читателю из ячейки: «гл. 32», «расчётная разгадка ≈гл.20» (число после «разгадк»);
    «улики с гл. 4» без разгадки — не раскрытие (None)."""
    m = re.search(r"разгадк[а-я]*\D{0,25}?гл\.?\s*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.search(r"улик", text, re.IGNORECASE):
        return None
    m = CH_RE.search(text)
    return int(m.group(1)) if m else None


def _match_matrix_fact(secret: str, matrix: list[MatrixFact]) -> str | None:
    """fact_id факта матрицы 3.1 с наибольшим совпадением слов с текстом тайны."""
    def words(t: str) -> set[str]:
        return {w for w in re.findall(r"[а-яё]{4,}", t.lower()) if w not in {"года", "полная", "картина", "слой"}}
    target = words(secret)
    best, score = None, 0
    for f in matrix:
        if f.subject != "Читатель":
            continue
        n = len(target & words(f.fact))
        if n > score:
            best, score = f, n
    if best is None or score < min(2, len(target)):
        return None
    return best.fact_id


def _matrix_knowledge(fact_id: str, matrix: list[MatrixFact]) -> tuple[int | None, dict[str, int]]:
    """(глава раскрытия читателю, {персонаж: глава полного знания}) по строке матрицы."""
    reader: int | None = None
    known: dict[str, int] = {}
    for f in matrix:
        if f.fact_id != fact_id or f.from_chapter is None:
            continue
        if f.subject == "Читатель":
            reader = f.from_chapter
        elif not f.note.startswith("частично"):
            known[f.subject] = f.from_chapter
    return reader, known


def _parse_known_by(text: str, known_names: set[str]) -> dict[str, int]:
    """«Лемм, Штерн; больше никто», «Степан, куратор ОГПУ; Штерн — с гл. 7; Лемм — с гл. 17»,
    «Лемм; Заварзин узнает в томе 3» → {имя: глава}. Без главы — 0 (знает всегда)."""
    known: dict[str, int] = {}
    for chunk in re.split(r"[;,]", text):
        chunk = chunk.strip()
        if not chunk or re.search(r"\b(никто|не узнает|не узнаёт)\b", chunk, re.IGNORECASE):
            continue
        if re.search(r"в томе\s*\d+", chunk, re.IGNORECASE):
            continue  # узнаёт в другом томе — в этом не знает
        name = normalize_name(re.sub(r"^(только|больше)\s+", "", chunk, flags=re.IGNORECASE), known_names)
        if name not in known_names:
            continue
        chm = CH_RE.search(chunk)
        known[name] = int(chm.group(1)) if chm else 0
    return known


def _merge_known(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    out = dict(a)
    for name, ch in b.items():
        out[name] = min(out[name], ch) if name in out else ch
    return out


def parse_secret_markers(path: Path) -> dict[str, list[str]]:
    """Таблица «Маркеры фильтра окна» (Р-022): | Т-№ | Маркеры | → {Т-01: [слова…]}."""
    markers: dict[str, list[str]] = {}
    for table in mdparse.parse_tables(path):
        if not any("Маркер" in h for h in table.headers):
            continue
        for row in table.rows:
            key = next((v.strip() for h, v in row.items() if h.startswith("Т")), "")
            raw = next((v for h, v in row.items() if "Маркер" in h), "")
            if key:
                markers[key] = [m.strip().strip("«»") for m in raw.split(";") if m.strip()]
    return markers


def parse_secrets(path: Path, known_names: set[str] | None = None, matrix: list[MatrixFact] | None = None) -> list[InfoBan]:
    """Реестр тайн: тайна → «НЕ упоминать» до главы, где читатель узнаёт; кто из персонажей знает (FR-C3)."""
    _, volume = registry_year_volume(path)
    known_names = known_names or set()
    parts = parse_parts(path)
    markers = parse_secret_markers(path)
    bans: list[InfoBan] = []
    for table in mdparse.parse_tables(path):
        headers = " ".join(table.headers).lower()
        if "тайна" not in headers:
            continue
        for i, row in enumerate(table.rows, start=1):
            reveal = cell(row, "узнаёт")
            secret_text = cell(row, "Тайна")
            # знание персонажей — из реестра И из матрицы 3.1 (в реестре список часто неполон)
            matrix_reader, matrix_known = None, {}
            fid = _match_matrix_fact(secret_text, matrix) if matrix else None
            if fid:
                matrix_reader, matrix_known = _matrix_knowledge(fid, matrix)
            if re.search(r"НЕ раскрыва", reveal):
                until_ch: int | None = None
            elif re.search(r"[Пп]ролог", reveal):
                until_ch = 0
            else:
                until_ch = reveal_chapter(reveal)
                if until_ch is None and matrix_reader is not None:
                    until_ch = matrix_reader
                if until_ch is None:
                    pm = re.search(r"[Чч]аст[ьи]\s+([IVX\d]+)", reveal)
                    if pm:
                        num = ROMAN.get(pm.group(1), int(pm.group(1)) if pm.group(1).isdigit() else 0)
                        part = next((p for p in parts if p["part"] == num), None)
                        if part:
                            until_ch = part["to_chapter"]  # до конца части — безопасная граница
            ban_id = f"Т-{i:02d}"
            bans.append(
                InfoBan(
                    ban_id=ban_id,
                    text=secret_text,
                    until_volume=None if until_ch is not None else volume + 1,
                    until_chapter=until_ch,
                    secret=True,
                    known_by=_merge_known(_parse_known_by(cell(row, "знают"), known_names), matrix_known),
                    markers=markers.get(ban_id, []),
                )
            )
    return bans


# --------------------------------------------------------------- досье 1.3


DOSSIER_HEAD_RE = re.compile(r"^#\s*Досье[^:]*:\s*(.+)$", re.MULTILINE)


def parse_dossiers_real(paths: list[Path], known_names: set[str]) -> list[Dossier]:
    """Карточки «# Досье 1.3: ИМЯ» (по нескольку в файле); отношения — проза [[Имя]]."""
    dossiers: list[Dossier] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        heads = list(DOSSIER_HEAD_RE.finditer(text))
        for i, head in enumerate(heads):
            body = text[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
            title = head.group(1)
            main_title = re.sub(r"\(.*?\)", "", title)  # скобки — псевдонимы/пояснения
            found = [
                (m.start(), n) for n in known_names
                if (m := re.search(n, main_title, re.IGNORECASE))
            ]
            name = min(found)[1] if found else title.split("(")[0].split()[-1].capitalize()

            def section(pattern: str) -> str:
                m = re.search(rf"##\s*{pattern}[^\n]*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
                return m.group(1).strip() if m else ""

            relations: dict[str, str] = {}
            rel_body = section(r"Отношени")
            for rm in re.finditer(r"\[\[([^\]]+)\]\]\s*[—-]+\s*([^\[]+)", rel_body):
                relations[rm.group(1).strip()] = rm.group(2).strip().rstrip(". ")
            dossiers.append(
                Dossier(
                    name=name,
                    profile=section(r"Профил"),
                    physique=section(r"Физик"),
                    speech=section(r"Речевой"),
                    relations=relations,
                )
            )
    return dossiers


# ------------------------------------------------------------- части тома


PART_RE = re.compile(r"###\s*ЧАСТЬ\s+([IVX\d]+)\.\s*«([^»]+)»\s*[—-]+\s*(.*?)\s*\(гл\.\s*(\d+)\s*[–-]\s*(\d+)\)")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def parse_parts(path: Path) -> list[dict]:
    """Части тома из заголовков реестра: «### ЧАСТЬ I. «МОКРОЕ ДЕЛО» — апрель 1926 (гл. 1–9)»."""
    parts = []
    for m in PART_RE.finditer(path.read_text(encoding="utf-8")):
        num = m.group(1)
        parts.append(
            {
                "part": ROMAN.get(num, int(num) if num.isdigit() else len(parts) + 1),
                "title": m.group(2),
                "period": m.group(3),
                "from_chapter": int(m.group(4)),
                "to_chapter": int(m.group(5)),
            }
        )
    return parts


# ------------------------------------------- закладки из контроля поглавника


def parse_poglavnik_plants(path: Path, volume: int, existing: list[Plant]) -> list[Plant]:
    """Строка «Закладки положены: знак/зола (6.2), часы (гл. 4), …» → закладки глав,
    которых нет в реестре §7 (дедупликация по главе и первому слову)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Закладки положены:\s*(.+)", text)
    if not m:
        return []
    new: list[Plant] = []
    for i, item in enumerate(re.split(r",\s*(?![^(]*\))", m.group(1).rstrip(". ")), start=1):
        loc = re.search(r"\(([^)]*)\)", item)
        name = re.sub(r"\(.*?\)", "", item).strip()
        if not loc or not name:
            continue
        ch_m = re.search(r"(\d+)", loc.group(1))
        if not ch_m:
            continue
        chapter = int(ch_m.group(1))
        stem = re.split(r"[\s/]", name.lower())[0][:4]
        if any(chapter in p.chapters and stem in p.what.lower() for p in existing + new):
            continue
        new.append(
            Plant(
                plant_id=f"П-{i:02d}",
                what=f"{name} (по контролю поглавника)",
                placed={"vol": volume, "ch": chapter},
                chapters=[chapter],
                fires=[],
                status="🔧",
            )
        )
    return new


# ------------------------------------------------ круги истории (2.1, Р-020)

CIRCLE_HEAD_RE = re.compile(r"^##\s*Круг\s+(тома|акта\s+([IVX\d]+)|главы\s+(\d+))\b(.*)$", re.MULTILINE)
CIRCLE_STEP_RE = re.compile(r"^(\d)\.\s+\*\*(.+?)\*\*\s*(?:\(([^)]*)\))?\s*(?:[—–-]+\s*)?(.*)$")
_CH_RANGE_RE = re.compile(r"гл\.?\s*([\d\s,–\-]+)")


def chapter_range(text: str) -> tuple[int | None, int | None]:
    """«гл. 1–3» / «гл. 5» / «гл. 1, 3» → (1, 3); «сц. 5.1» → (None, None)."""
    m = _CH_RANGE_RE.search(text)
    if not m:
        return None, None
    nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
    if not nums:
        return None, None
    return min(nums), max(nums)


def parse_circles(path: Path) -> list[StoryCircle]:
    """Документ 21_Круги_истории: «## Круг тома» / «## Круг акта 3 …» / «## Круг главы 5»,
    внутри — «**Суть:**», нумерованные шаги «1. **Ты** (гл. 1–3) — …», «**Слабое место:**»."""
    text = path.read_text(encoding="utf-8")
    heads = list(CIRCLE_HEAD_RE.finditer(text))
    circles: list[StoryCircle] = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        kind = h.group(1)
        if kind == "тома":
            scope, key, title = "книга", None, "Книга (том целиком)"
        elif kind.startswith("акта"):
            num = h.group(2)
            key = ROMAN.get(num, int(num) if num.isdigit() else 0)
            tm = re.search(r"«([^»]+)»", h.group(4) or "")
            scope, title = "акт", f"Акт {key}" + (f" «{tm.group(1)}»" if tm else "")
        else:
            scope, key = "глава", int(h.group(3))
            title = f"Глава {key}"
        circle = StoryCircle(scope=scope, key=key, title=title)
        current: CircleStep | None = None
        for line in body.splitlines():
            stripped = line.strip()
            sm = CIRCLE_STEP_RE.match(stripped)
            if sm:
                lo, hi = chapter_range(sm.group(3) or "")
                current = CircleStep(
                    n=int(sm.group(1)), name=sm.group(2).strip(), chapters=(sm.group(3) or "").strip(),
                    text=sm.group(4).strip(), from_chapter=lo, to_chapter=hi,
                )
                circle.steps.append(current)
                continue
            if stripped.startswith("**Суть:**"):
                circle.summary = stripped[len("**Суть:**"):].strip(); current = None
            elif stripped.startswith("**Слабое место:**"):
                circle.weak_spot = stripped[len("**Слабое место:**"):].strip(); current = None
            elif stripped and current is not None and not stripped.startswith("#"):
                current.text = (current.text + " " + stripped).strip()
        if circle.steps:
            circles.append(circle)
    return circles


def parse_acts(path: Path) -> list[Act]:
    """Таблица «Акты тома» документа 2.1 (Р-021): | Акт | Название | Главы | Части | Шаги круга |."""
    acts: list[Act] = []
    for table in mdparse.parse_tables(path):
        if "Акт" not in table.headers or "Главы" not in table.headers:
            continue
        for row in table.rows:
            nums = [int(x) for x in re.findall(r"\d+", row["Главы"])]
            if not nums or not row["Акт"].strip().isdigit():
                continue
            acts.append(Act(
                act=int(row["Акт"]), title=row.get("Название", "").strip("«» "),
                from_chapter=min(nums), to_chapter=max(nums),
                parts=row.get("Части", "").strip(), steps=row.get("Шаги круга", "").strip(),
            ))
    return sorted(acts, key=lambda a: a.act)
