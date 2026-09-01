"""Текстовые счётчики Э1: предложения (Д-2), слова, n-граммы (Д-4), TTR (Д-3).

Деление на предложения: регэксп по `.!?…` с обработкой прямой речи
(тире-реплики) и словаря сокращений (пополняемый файл data/сокращения.txt).
Метрики считаются по всему тексту, включая диалоги; исключаются только
размеченные документы-вставки (Д-7): блок между строками
`→ ДОКУМЕНТ` и `← КОНЕЦ ДОКУМЕНТА`.
"""

from __future__ import annotations

import re
from collections import Counter
from importlib import resources
from pathlib import Path

DOC_START = "→ ДОКУМЕНТ"
DOC_END = "← КОНЕЦ ДОКУМЕНТА"

_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:-[А-Яа-яЁёA-Za-z0-9]+)*")
# конец предложения: терминатор + закрывающие кавычки/скобки (остаются в предложении)
_SENT_END_RE = re.compile(r"[.!?…]+[»«\"')\]]*")
_ABBR_MASK = "\x01"  # непечатаемый маркер точки внутри сокращения


def _load_abbreviations(extra_path: Path | None = None) -> list[str]:
    text = resources.files("ugar").joinpath("data/сокращения.txt").read_text(encoding="utf-8")
    abbrs = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if extra_path and extra_path.exists():
        abbrs += [
            ln.strip()
            for ln in extra_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
    # длинные раньше коротких, чтобы «т.д.» маскировалось до «д.»
    return sorted(set(abbrs), key=len, reverse=True)


def strip_document_inserts(text: str) -> str:
    """Убирает документы-вставки из текста повествователя (Д-7, FR-V1.1)."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(DOC_START):
            inside = True
            continue
        if stripped.startswith(DOC_END):
            inside = False
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def strip_markdown(text: str) -> str:
    """Снимает заголовки/выделение MD, чтобы счётчики видели чистую прозу."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`]{1,3}", "", text)
    return text


def split_sentences(text: str, extra_abbr: Path | None = None) -> list[str]:
    """Деление на предложения по Д-2."""
    abbrs = _load_abbreviations(extra_abbr)
    masked = text
    for abbr in abbrs:
        pattern = re.compile(r"(?<![А-Яа-яЁёA-Za-z])" + re.escape(abbr))
        masked = pattern.sub(abbr.replace(".", _ABBR_MASK), masked)
    sentences: list[str] = []
    for para in masked.splitlines():
        para = para.strip()
        if not para:
            continue
        # тире-реплики режем как обычные предложения; терминатор внутри слова
        # (десятичные числа) предложение не завершает
        start = 0
        for m in _SENT_END_RE.finditer(para):
            end = m.end()
            if end < len(para) and not para[end].isspace():
                continue
            chunk = para[start:end].strip()
            if chunk:
                sentences.append(chunk.replace(_ABBR_MASK, "."))
            start = end
        tail = para[start:].strip()
        if tail:
            sentences.append(tail.replace(_ABBR_MASK, "."))
    return sentences


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def word_count(text: str) -> int:
    return len(words(text))


def sentence_lengths(text: str, extra_abbr: Path | None = None) -> list[int]:
    return [len(words(s)) for s in split_sentences(text, extra_abbr) if words(s)]


def normalize(text: str) -> list[str]:
    """Нормализация для n-грамм (Д-4): нижний регистр, без пунктуации."""
    return [w.lower().replace("ё", "е") for w in words(text)]


def ngrams(tokens: list[str], n: int) -> Counter:
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def ttr(tokens: list[str]) -> float:
    """TTR по словоформам без лемматизации (Д-3)."""
    if not tokens:
        return 0.0
    return len({t.lower() for t in tokens}) / len(tokens)


def rolling_ttr(tokens: list[str], window: int) -> list[tuple[int, float]]:
    """TTR нарастающим окном `window` слов: [(позиция конца окна, ttr)]."""
    result: list[tuple[int, float]] = []
    if len(tokens) < window:
        return result
    step = max(1, window // 10)
    for end in range(window, len(tokens) + 1, step):
        result.append((end, ttr(tokens[end - window : end])))
    return result


def narrator_text(raw: str) -> str:
    """Текст для метрик повествователя: без вставок-документов и разметки MD."""
    return strip_markdown(strip_document_inserts(raw))
