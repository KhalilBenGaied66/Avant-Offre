"""Single entry point for LLM calls (LiteLLM).

Models come from ``config/models.yaml`` per task, so a provider or model swap is a config
change (DECISIONS rule 7). Behaviour:
- no client library or no API key for the provider -> ``LLMUnavailableError`` (callers fall back
  to deterministic output and say so);
- a rejected model id -> ``ModelRejectedError`` (configuration error: fail loudly);
- any stop other than a normal end of turn (truncation, refusal, content filter) is returned
  with ``ok = False`` so the caller can fall back.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from avant_offre.llm.tracing import prompt_hash
from avant_offre.settings import get_models

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "mistral": "MISTRAL_API_KEY"}
NORMAL_STOPS = {"stop", "end_turn"}


class LLMUnavailableError(RuntimeError):
    pass


class ModelRejectedError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float | None
    finish_reason: str | None
    prompt_hash: str

    @property
    def ok(self) -> bool:
        return (self.finish_reason or "stop") in NORMAL_STOPS and bool(self.text.strip())

    def trace(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "cost_usd": self.cost_usd,
            "finish_reason": self.finish_reason,
        }


def available(model: str) -> bool:
    provider = model.split("/", 1)[0]
    key = PROVIDER_KEYS.get(provider)
    if key is not None and not os.environ.get(key):
        return False
    try:
        import litellm  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = get_models().prices_per_mtok.get(model)
    if price is None:
        return None
    return round((input_tokens * price.input + output_tokens * price.output) / 1e6, 6)


def complete(task: str, messages: list[dict[str, Any]], *, model: str | None = None) -> LLMResult:
    cfg = get_models().tasks[task]
    model = model or cfg.model
    if not available(model):
        provider = model.split("/", 1)[0]
        raise LLMUnavailableError(
            f"{model}: needs `uv sync --extra llm` and {PROVIDER_KEYS.get(provider, 'a key')}"
        )
    import litellm  # noqa: PLC0415
    from litellm import exceptions as llm_errors  # noqa: PLC0415

    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": cfg.max_tokens}
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    started = time.perf_counter()
    try:
        resp = litellm.completion(**kwargs)
    except (llm_errors.NotFoundError, llm_errors.BadRequestError) as exc:
        if "model" in str(exc).lower():
            raise ModelRejectedError(f"{model} rejected by the provider: {exc}") from exc
        raise
    latency = 1000 * (time.perf_counter() - started)
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    tin = int(getattr(usage, "prompt_tokens", 0) or 0)
    tout = int(getattr(usage, "completion_tokens", 0) or 0)
    return LLMResult(
        text=choice.message.content or "",
        model=model,
        input_tokens=tin,
        output_tokens=tout,
        latency_ms=latency,
        cost_usd=estimate_cost(model, tin, tout),
        finish_reason=getattr(choice, "finish_reason", None),
        prompt_hash=prompt_hash(messages),
    )
