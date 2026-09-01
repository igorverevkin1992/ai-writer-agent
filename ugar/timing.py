"""Время такта из истории FSM: машинное против авторского (критерий приёмки 1).

Такт главы должен укладываться в ≤40 минут работы автора (замер по 10.4).
История переходов в status.yaml хранит таймстемпы — интервал между переходами
относится к состоянию, в котором глава находилась, а состояния делятся на
машинные и авторские (паузы на review/приёмке/подписи пакета).
"""

from __future__ import annotations

from datetime import datetime

AUTHOR_STATES = {"на-приёмке", "дифф-контроль", "принято"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def chapter_times(history: list[dict]) -> tuple[float, float]:
    """(машинное_с, авторское_с) по завершённым интервалам истории.

    Текущее незакрытое состояние не учитывается — пауза ещё идёт.
    """
    machine = 0.0
    author = 0.0
    for cur, nxt in zip(history, history[1:]):
        try:
            delta = (_parse(nxt["время"]) - _parse(cur["время"])).total_seconds()
        except (KeyError, ValueError):
            continue
        if delta < 0:
            continue
        if cur.get("в") in AUTHOR_STATES:
            author += delta
        else:
            machine += delta
    return machine, author


def fmt_minutes(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} с"
    return f"{seconds / 60:.1f} мин"
