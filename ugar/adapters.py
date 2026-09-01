"""Адаптеры API моделей (раздел 6): Писатель — Gemini, Верификатор-2/Канонист — Anthropic.

Общие требования §6.3: ключи только из окружения/.env (Д-9); ретраи — 3 попытки
с экспоненциальной паузой на сетевых/5xx; таймаут 120 с; при исчерпании —
понятная ошибка и подсказка ручного режима (NFR-3). Каждый вызов — строка
logs/api.jsonl. Тексты передаются ТОЛЬКО в эти два API.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from .apilog import log_call
from .config import ApiConfig, ModelConfig


class ManualModeNeeded(RuntimeError):
    """API недоступен — конвейер деградирует в ручной режим (NFR-3)."""

    def __init__(self, reason: str, hint: str):
        super().__init__(f"{reason}\n\nРучной режим: {hint}")
        self.reason = reason
        self.hint = hint


def _estimate_cost(mc: ModelConfig, tokens_in: int | None, tokens_out: int | None) -> float | None:
    """Оценка стоимости вызова по ценам из config.yaml (§6.3)."""
    if not mc.price_in_per_1m and not mc.price_out_per_1m:
        return None
    return round(
        (tokens_in or 0) * mc.price_in_per_1m / 1_000_000
        + (tokens_out or 0) * mc.price_out_per_1m / 1_000_000,
        6,
    )


def _retry_call(fn, api: ApiConfig, logs_dir: Path, *, role: str, mc: ModelConfig, chapter: int | None):
    last_error: Exception | None = None
    for attempt in range(api.retries):
        start = time.monotonic()
        try:
            text, tokens_in, tokens_out = fn()
            log_call(
                logs_dir,
                role=role,
                model=mc.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_est=_estimate_cost(mc, tokens_in, tokens_out),
                chapter=chapter,
                duration=time.monotonic() - start,
            )
            return text
        except Exception as e:  # сетевые/5xx — ретраим с экспоненциальной паузой
            last_error = e
            log_call(
                logs_dir,
                role=role,
                model=mc.model,
                chapter=chapter,
                duration=time.monotonic() - start,
                error=f"{type(e).__name__}: {e}",
            )
            if attempt < api.retries - 1:
                time.sleep(api.backoff_base_s * (2**attempt))
    raise ManualModeNeeded(
        f"Вызов {role} ({mc.model}) не удался после {api.retries} попыток: {last_error}",
        "скопируйте входной файл (окно/промпт) в чат модели вручную и сохраните ответ "
        "в ожидаемый файл артефакта — каждый шаг такта исполним отдельно (FR-O2).",
    )


def call_gemini(prompt: str, mc: ModelConfig, api: ApiConfig, logs_dir: Path, chapter: int | None = None) -> str:
    """Писатель (§6.1): один вызов = одна глава/сцена; system-инструкций вне окна нет."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ManualModeNeeded(
            "Не найден GEMINI_API_KEY (задайте в .env, Д-9).",
            "скопируйте chapters/N/window.md в чат Gemini и сохраните ответ как chapters/N/draft_1.md, затем продолжите с `ugar verify1 N`.",
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ManualModeNeeded(
            "SDK google-genai не установлен (pip install 'ugar-pipeline[llm]').",
            "ручной вызов модели через веб-интерфейс, ответ — в chapters/N/draft_k.md.",
        )

    def do():
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=api.timeout_s * 1000))
        resp = client.models.generate_content(
            model=mc.model, contents=prompt, config=types.GenerateContentConfig(**mc.params)
        )
        usage = getattr(resp, "usage_metadata", None)
        return (
            resp.text or "",
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )

    return _retry_call(do, api, logs_dir, role="писатель", mc=mc, chapter=chapter)


def call_anthropic(
    system: str,
    user: str,
    mc: ModelConfig,
    api: ApiConfig,
    logs_dir: Path,
    *,
    role: str,
    chapter: int | None = None,
) -> str:
    """Верификатор-2 / Канонист (§6.2)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ManualModeNeeded(
            "Не найден ANTHROPIC_API_KEY (задайте в .env, Д-9).",
            "скопируйте подготовленный промпт (chapters/N/*_prompt.md) в чат Claude и сохраните JSON-ответ в ожидаемый файл.",
        )
    try:
        import anthropic
    except ImportError:
        raise ManualModeNeeded(
            "SDK anthropic не установлен (pip install 'ugar-pipeline[llm]').",
            "ручной вызов модели через веб-интерфейс.",
        )

    def do():
        client = anthropic.Anthropic(api_key=key, timeout=float(api.timeout_s))
        resp = client.messages.create(
            model=mc.model,
            max_tokens=mc.params.get("max_tokens", 8192),
            system=system,
            messages=[{"role": "user", "content": user}],
            **{k: v for k, v in mc.params.items() if k != "max_tokens"},
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    return _retry_call(do, api, logs_dir, role=role, mc=mc, chapter=chapter)
