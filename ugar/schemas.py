"""Схемы данных конвейера (раздел 5 ТЗ): выгрузки, вердикты, флаги, правки.

Выгрузки валидируются этими схемами перед записью (FR-X2); невалидная
выгрузка не записывается.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- выгрузки 5.2


class StopRule(BaseModel):
    """Строка stoplists.json — из 03/04 и Р-016 (усилители)."""

    scope: Literal["0.3", "0.4"]
    rule_id: str
    items: list[str]
    applies_to: dict = Field(default_factory=dict)  # {focal?|year?|all}
    action: Literal["запрет", "флаг"] = "запрет"
    kind: Literal["лексика", "усилитель"] = "лексика"


class MatrixFact(BaseModel):
    """Строка matrix.json — из 31. from_chapter=None → субъект НЕ знает."""

    fact_id: str
    fact: str
    subject: str
    from_chapter: int | None = None
    source: str = ""
    note: str = ""


class Plant(BaseModel):
    """Строка plants.json (закладки) — из 3.2/реестра тома."""

    plant_id: str
    what: str
    placed: dict  # {vol, ch}
    chapters: list[int] = Field(default_factory=list)  # все главы, где лежит (реестр §7)
    fires: list[dict] = Field(default_factory=list)  # [{vol, ch?}]
    status: str = ""


class Norm(BaseModel):
    """Числовой порог Э1 — из 02 §5. Единственный источник порогов (FR критерий 6)."""

    min: float | None = None
    max: float | None = None
    brak: float | None = None
    unit: str = ""
    source: str = "02 §5"


class ContinuityEvent(BaseModel):
    """Строка continuity.json — из 33."""

    date: str
    event: str
    chapters: str = ""
    note: str = ""


class Brief(BaseModel):
    """Глава поглавника (briefs.json — из 23)."""

    chapter: int
    volume: int = 1
    date: str = ""
    year: int | None = None
    focal: str = ""
    scenes: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)  # персонажи сцен главы
    beats: list[str] = Field(default_factory=list)
    bans: list[str] = Field(default_factory=list)       # запреты
    not_knows: list[str] = Field(default_factory=list)  # явные «НЕ знает»
    volume_words: int | None = None
    plants: list[str] = Field(default_factory=list)     # plant_id, назначенные главе


class Dossier(BaseModel):
    """Досье персонажа для окна (FR-C1): профиль, физика, речевой паспорт, отношения."""

    name: str
    profile: str = ""
    physique: str = ""
    speech: str = ""
    relations: dict[str, str] = Field(default_factory=dict)


class InfoBan(BaseModel):
    """Запрет информрежима из 2.2 (FR-C3): резервы будущих томов."""

    ban_id: str
    text: str
    until_volume: int | None = None
    # реестр тайн: глава, в которой читатель узнаёт (до неё — «НЕ упоминать»)
    until_chapter: int | None = None
    secret: bool = False  # текст — содержание тайны: Писателю сообщать нельзя (FR-C3)


# --------------------------------------------------------- вердикты и флаги


class CheckResult(BaseModel):
    """Результат одной проверки Э1 (FR-V1.9)."""

    check_id: str
    status: Literal["PASS", "FLAG", "BRAK"]
    threshold: str
    actual: str
    quotes: list[str] = Field(default_factory=list)
    rule_source: str = ""
    note: str = ""


class Verdict(BaseModel):
    chapter: int
    draft: int
    checks: list[CheckResult]

    @property
    def has_brak(self) -> bool:
        return any(c.status == "BRAK" for c in self.checks)

    @property
    def flags(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status != "PASS"]


class Flag(BaseModel):
    """Флаг Э2 (FR-V2.2). kind=samovolka требует решения автора."""

    flag_id: str
    type: str
    severity: Literal["критично", "важно", "мелочь"] = "важно"
    quote: str
    rule: str
    recommendation: str = ""
    kind: Literal["violation", "samovolka"] = "violation"


class Resolution(BaseModel):
    """Решение автора по самоволке (FR-V2.5)."""

    flag_id: str
    decision: Literal["вычеркнуть", "канонизировать"] | None = None
    target_registry: str | None = None


# ------------------------------------------------------------------- правки


class Edit(BaseModel):
    """Строка edits.jsonl (5.3). Класс проставляет Канонист, подтверждает автор."""

    chapter: int
    seq: int
    before: str
    after: str
    class_: Literal["вкус", "факт", "канон"] | None = Field(default=None, alias="class")
    note: str = ""

    model_config = {"populate_by_name": True}


class DiffReport(BaseModel):
    """Отчёт дифф-контроля (FR-V1.10)."""

    chapter: int
    draft_before: int
    draft_after: int
    applied_share: float
    not_applied: list[int] = Field(default_factory=list)      # seq невнесённых правок
    unauthorized: list[str] = Field(default_factory=list)     # самовольные изменения
    # свободные указания (УКАЗАНИЕ:): механически не проверяемы, приёмку не блокируют
    unverifiable: list[int] = Field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.not_applied and not self.unauthorized


# ---------------------------------------------------------------- регрессия


class GoldenTest(BaseModel):
    """Золотой тест (FR-R1)."""

    test_id: str
    fragment: str
    context_slice: dict = Field(default_factory=dict)  # chapter, focal, year, window?
    expected_flags: list[str] = Field(default_factory=list)  # check_id / type
    echelon: Literal["Э1", "Э2"] = "Э1"
