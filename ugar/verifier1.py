"""Верификатор-1 (Э1): формальные проверки текста (FR-V1.1…FR-V1.10).

Все пороги — ТОЛЬКО из norms.json (02 §5); в коде констант нет
(критерий приёмки 6). Метрики повествователя считаются без документов-вставок
(Д-7); деление на предложения — по Д-2.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from . import exporter, guard, textutils
from .paths import Workspace
from .schemas import Brief, CheckResult, DiffReport, Edit, Norm, StopRule, Verdict

MAX_QUOTES = 10


def _norm_value(norms: dict[str, Norm], norm_id: str) -> float:
    """Числовое значение нормы-параметра. Пороги берутся ТОЛЬКО из norms.json
    (критерий приёмки 6) — отсутствие значения это ошибка канона, не повод
    для зашитого в код умолчания."""
    n = norms[norm_id]
    value = n.max if n.max is not None else n.min
    if value is None:
        raise RuntimeError(
            f"Норма «{norm_id}» (02 §5) не имеет числового значения — заполните таблицу норм в каноне."
        )
    return value


def _status(actual: float, norm: Norm) -> str:
    """PASS/FLAG/BRAK по коридору нормы. BRAK — только если задан порог брака."""
    if norm.brak is not None:
        if norm.min is not None and actual < norm.brak:
            return "BRAK"
        if norm.min is None and norm.max is not None and actual > norm.brak:
            return "BRAK"
    if norm.min is not None and actual < norm.min:
        return "FLAG"
    if norm.max is not None and actual > norm.max:
        return "FLAG"
    return "PASS"


def _corridor(norm: Norm) -> str:
    parts = []
    if norm.min is not None:
        parts.append(f"мин {norm.min:g}")
    if norm.max is not None:
        parts.append(f"макс {norm.max:g}")
    if norm.brak is not None:
        parts.append(f"брак {norm.brak:g}")
    return ", ".join(parts) + (f" {norm.unit}" if norm.unit else "")


def _stoplist_applies(rule: StopRule, brief: Brief) -> bool:
    applies = rule.applies_to
    if "focal" in applies:
        return applies["focal"] == brief.focal
    if "year" in applies and brief.year is not None:
        y = applies["year"]
        if "before" in y:
            return brief.year < y["before"]
        if "from" in y:
            return y["from"] <= brief.year <= y.get("to", 9999)
    return True


def _find_items(text: str, items: list[str]) -> list[str]:
    found = []
    low = text.lower().replace("ё", "е")
    for item in items:
        needle = item.lower().replace("ё", "е")
        if re.search(r"(?<![а-яa-z])" + re.escape(needle) + r"(?![а-яa-z])", low):
            found.append(item)
    return found


def _quote_sentences(sentences: list[str], items: set[str]) -> list[str]:
    """Предложения-цитаты, содержащие любой из элементов (слово или оборот)."""
    needles = {i.lower().replace("ё", "е") for i in items}
    quotes = []
    for s in sentences:
        low = s.lower().replace("ё", "е")
        toks = set(textutils.normalize(s))
        if any(n in toks or (" " in n and n in low) for n in needles):
            quotes.append(s)
        if len(quotes) >= MAX_QUOTES:
            break
    return quotes


def _matching_runs(text_tokens: list[str], target_ngrams: set[tuple], n: int) -> list[str]:
    """Максимальные дословные совпадения длиной ≥ n токенов."""
    runs: list[str] = []
    i = 0
    while i <= len(text_tokens) - n:
        if tuple(text_tokens[i : i + n]) in target_ngrams:
            j = i + n
            while j <= len(text_tokens) - 1 and tuple(text_tokens[j - n + 1 : j + 1]) in target_ngrams:
                j += 1
            runs.append(" ".join(text_tokens[i:j]))
            i = j
        else:
            i += 1
    return runs[:MAX_QUOTES]


def run_verify1(ws: Workspace, chapter: int, draft: int) -> Verdict:
    exports_dir = ws.exports
    norms = exporter.load_norms(exports_dir)
    stoplists = exporter.load_stoplists(exports_dir)
    brief = exporter.load_brief(exports_dir, chapter)

    raw = ws.draft_path(chapter, draft).read_text(encoding="utf-8")
    window_path = ws.window_path(chapter)
    window_raw = window_path.read_text(encoding="utf-8") if window_path.exists() else ""

    own = exporter.find_corpus_file(ws.corpus, chapter, brief.volume)
    checks = analyze(
        raw,
        window_raw,
        brief,
        norms,
        stoplists,
        corpus_dir=ws.corpus,
        own_stem=own.stem if own else None,
        extra_abbr=ws.root / "сокращения.txt",  # пополняемый словарь (Д-2)
    )
    verdict = Verdict(chapter=chapter, draft=draft, checks=checks)
    guard.write_text(
        ws.chapter_dir(chapter) / "verdict.json",
        json.dumps(verdict.model_dump(), ensure_ascii=False, indent=2) + "\n",
    )
    return verdict


def analyze(
    raw: str,
    window_raw: str,
    brief: Brief,
    norms: dict[str, Norm],
    stoplists: list[StopRule],
    *,
    corpus_dir: Path | None = None,
    own_stem: str | None = None,
    extra_abbr: Path | None = None,
) -> list[CheckResult]:
    """Чистое ядро Э1: текст + контекст → список результатов проверок."""
    text = textutils.narrator_text(raw)
    sentences = textutils.split_sentences(text, extra_abbr)
    lengths = [len(textutils.words(s)) for s in sentences if textutils.words(s)]
    tokens = textutils.normalize(text)
    n_words = len(tokens)
    checks: list[CheckResult] = []

    def add(check_id: str, norm_id: str, actual: float, quotes: list[str] | None = None, note: str = "") -> None:
        norm = norms[norm_id]
        checks.append(
            CheckResult(
                check_id=check_id,
                status=_status(actual, norm),
                threshold=_corridor(norm),
                actual=f"{actual:g}",
                quotes=quotes or [],
                rule_source=norm.source,
                note=note,
            )
        )

    # FR-V1.2 — длины фраз и объём
    avg = sum(lengths) / len(lengths) if lengths else 0.0
    add("V1.2a_средняя_длина", "средняя_длина", round(avg, 2))

    short_thr = _norm_value(norms, "короткая_фраза_порог")
    long_thr = _norm_value(norms, "длинная_фраза_порог")
    if lengths:
        add("V1.2b_доля_коротких", "доля_коротких", round(sum(1 for x in lengths if x <= short_thr) / len(lengths), 3))
        add("V1.2c_доля_длинных", "доля_длинных", round(sum(1 for x in lengths if x >= long_thr) / len(lengths), 3))
        longest = max(zip(lengths, [s for s in sentences if textutils.words(s)]))
        add("V1.2d_максимум_длины", "максимум_длины", longest[0], quotes=[longest[1]])

    if brief.volume_words:
        deviation = abs(n_words - brief.volume_words) / brief.volume_words
        tolerance = _norm_value(norms, "объём_допуск")
        checks.append(
            CheckResult(
                check_id="V1.2e_объём",
                status="BRAK" if deviation > tolerance else "PASS",
                threshold=f"{brief.volume_words} слов ± {tolerance:.0%}",
                actual=f"{n_words} слов (отклонение {deviation:.0%})",
                rule_source=norms["объём_допуск"].source,
            )
        )

    # FR-V1.3 — плотность «был/было/были»
    byl_forms = {"был", "было", "были", "была"}
    byl_count = sum(1 for t in tokens if t in byl_forms)
    add(
        "V1.3_был",
        "был_на_250",
        round(byl_count / n_words * 250, 2) if n_words else 0.0,
        quotes=_quote_sentences(sentences, byl_forms),
        note=f"{byl_count} вхождений на {n_words} слов",
    )

    # FR-V1.4 — наречия-усилители
    intensifiers = {
        w.lower().replace("ё", "е") for r in stoplists if r.kind == "усилитель" for w in r.items
    }
    int_count = sum(1 for t in tokens if t in intensifiers)
    add(
        "V1.4_усилители",
        "усилители_на_1000",
        round(int_count / n_words * 1000, 2) if n_words else 0.0,
        quotes=_quote_sentences(sentences, intensifiers),
        note=f"{int_count} вхождений",
    )

    # FR-V1.5 — запрещённая лексика (год главы и фокал)
    for rule in stoplists:
        if rule.kind != "лексика" or not _stoplist_applies(rule, brief):
            continue
        found = _find_items(text, rule.items)
        if found:
            checks.append(
                CheckResult(
                    check_id="V1.5_стоп_лексика",
                    status="FLAG",
                    threshold=f"действие: {rule.action}",
                    actual="; ".join(found),
                    quotes=_quote_sentences(sentences, {w.lower().replace("ё", "е") for w in found}),
                    rule_source=f"{rule.rule_id} (реестр {rule.scope})",
                )
            )
    if not any(c.check_id == "V1.5_стоп_лексика" for c in checks):
        checks.append(
            CheckResult(
                check_id="V1.5_стоп_лексика", status="PASS", threshold="0 вхождений", actual="0",
                rule_source="stoplists.json",
            )
        )

    # FR-V1.6 — вставка окна («утечка промпта»)
    leak_n = int(_norm_value(norms, "утечка_нграмма"))
    win_tokens = textutils.normalize(window_raw)
    leaks = (
        _matching_runs(tokens, set(textutils.ngrams(win_tokens, leak_n)), leak_n) if win_tokens else []
    )
    checks.append(
        CheckResult(
            check_id="V1.6_утечка_окна",
            status="FLAG" if leaks else "PASS",
            threshold=f"совпадения ≥ {leak_n} слов с окном",
            actual=str(len(leaks)),
            quotes=leaks,
            rule_source=norms["утечка_нграмма"].source,
        )
    )

    # FR-V1.7 — межглавные повторы против corpus/
    rep_n = int(_norm_value(norms, "повтор_нграмма"))
    repeats: list[str] = []
    sources: list[str] = []
    if corpus_dir is not None and corpus_dir.exists():
        text_ngrams = set(textutils.ngrams(tokens, rep_n))
        for f in sorted(corpus_dir.glob("*.txt")):
            if own_stem and f.stem == own_stem:
                continue
            other = f.read_text(encoding="utf-8").split()
            hits = _matching_runs(other, text_ngrams, rep_n)
            if hits:
                sources.append(f.stem)
                repeats.extend(f"[{f.stem}] {h}" for h in hits[:3])
    checks.append(
        CheckResult(
            check_id="V1.7_межглавные_повторы",
            status="FLAG" if repeats else "PASS",
            threshold=f"n-граммы ≥ {rep_n} слов против корпуса",
            actual=str(len(repeats)),
            quotes=repeats[:MAX_QUOTES],
            rule_source=norms["повтор_нграмма"].source,
            note="главы-источники: " + ", ".join(sources) if sources else "",
        )
    )

    # FR-V1.8 — TTR
    ttr_val = textutils.ttr(tokens)
    checks.append(
        CheckResult(
            check_id="V1.8a_ttr_главы",
            status="PASS",  # по главе — справочно
            threshold="справочно",
            actual=f"{ttr_val:.3f}",
            rule_source=norms["ttr_мин"].source,
        )
    )
    win_size = int(_norm_value(norms, "ttr_окно_слов"))
    part_tokens: list[str] = []
    if corpus_dir is not None and corpus_dir.exists():
        for f in sorted(corpus_dir.glob("*.txt")):
            if own_stem and f.stem == own_stem:
                continue
            part_tokens.extend(f.read_text(encoding="utf-8").split())
    part_tokens.extend(tokens)
    rolling = textutils.rolling_ttr(part_tokens, win_size)
    min_ttr = min((v for _, v in rolling), default=None)
    ttr_norm = norms["ttr_мин"]
    checks.append(
        CheckResult(
            check_id="V1.8b_ttr_окно",
            status=(
                "FLAG" if min_ttr is not None and ttr_norm.min is not None and min_ttr < ttr_norm.min else "PASS"
            ),
            threshold=f"мин {ttr_norm.min:g} в окне {win_size} слов",
            actual=f"{min_ttr:.3f}" if min_ttr is not None else f"часть короче {win_size} слов — не считается",
            rule_source=ttr_norm.source,
        )
    )

    return checks



# ------------------------------------------------------- FR-V1.10 дифф-контроль


def diff_check(ws: Workspace, chapter: int, draft_before: int, draft_after: int, edits: list[Edit]) -> DiffReport:
    """Сопоставление черновиков до/после правок: внесено / не внесено / самоволия.

    Свободные указания (пустое «было») механически не проверяемы: текст указания
    не обязан появиться в прозе. Они выносятся в unverifiable и приёмку не
    блокируют — их результат автор оценивает глазами.
    """
    old = ws.draft_path(chapter, draft_before).read_text(encoding="utf-8")
    new = ws.draft_path(chapter, draft_after).read_text(encoding="utf-8")

    verifiable = [e for e in edits if e.before.strip()]
    unverifiable = [e.seq for e in edits if not e.before.strip()]
    applied = 0
    not_applied: list[int] = []
    for e in verifiable:
        ok_removed = e.before not in new
        ok_added = (not e.after.strip()) or (e.after in new)
        if ok_removed and ok_added:
            applied += 1
        else:
            not_applied.append(e.seq)

    # самовольные изменения: изменённые фрагменты, не объяснимые ни одной правкой
    unauthorized: list[str] = []
    old_sents = textutils.split_sentences(textutils.strip_markdown(old))
    new_sents = textutils.split_sentences(textutils.strip_markdown(new))
    sm = difflib.SequenceMatcher(a=old_sents, b=new_sents, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old_frag = " ".join(old_sents[i1:i2])
        new_frag = " ".join(new_sents[j1:j2])
        explained = any(
            (e.before.strip() and e.before.strip() in old_frag)
            or (e.after.strip() and e.after.strip() in new_frag)
            for e in edits
        )
        if not explained:
            unauthorized.append(new_frag or f"[удалено]: {old_frag}")

    report = DiffReport(
        chapter=chapter,
        draft_before=draft_before,
        draft_after=draft_after,
        applied_share=round(applied / len(verifiable), 3) if verifiable else 1.0,
        not_applied=not_applied,
        unauthorized=unauthorized[:MAX_QUOTES * 2],
        unverifiable=unverifiable,
    )
    guard.write_text(
        ws.chapter_dir(chapter) / "diff_report.json",
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n",
    )
    return report
