"""Single entry point for LLM calls (LiteLLM).

Models come from ``config/models.yaml`` per task, so a provider or model swap is a config
change (DECISIONS rule 7). The same code talks to a free local server in development
(llama.cpp, ``scripts/llm_local.sh``) and, in a company, to vLLM / TGI on a GPU or to a managed
endpoint in its own cloud tenant: every one of them speaks the OpenAI-compatible chat API, or a
provider LiteLLM knows (docs/HANDOFF.md §2).

Behaviour:
- no client library, no key for a provider that needs one, or a self-hosted endpoint that does
  not answer -> ``LLMUnavailableError`` (callers fall back to deterministic output and say so);
- a rejected model id -> ``ModelRejectedError`` (configuration error: fail loudly);
- any stop other than a normal end of turn (truncation, refusal, content filter) is returned
  with ``ok = False`` so the caller can fall back.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from avant_offre.llm.tracing import prompt_hash
from avant_offre.settings import TaskModel, get_models

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "mistral": "MISTRAL_API_KEY"}
NORMAL_STOPS = {"stop", "end_turn"}
API_BASE_ENV = "AVANT_OFFRE_LLM_API_BASE"
HEALTH_TTL_S = 30.0  # a server started after the API process is picked up within this delay

_health: dict[str, tuple[float, bool]] = {}


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


@dataclass(frozen=True)
class Endpoint:
    """Where and how a model is called: the task's own settings for its configured model, the
    provider's defaults for an alternative compared in the evaluation."""

    model: str
    api_base: str | None
    key_env: str | None
    timeout_s: float
    num_retries: int


def settings_for(task: str, model: str | None = None) -> TaskModel:
    """The task's own settings for its model; an alternative's settings for that model; else the
    task's settings applied to the provider's own API."""
    models = get_models()
    cfg = models.tasks[task]
    if model is None or model == cfg.model:
        return cfg
    for alt in models.alternatives:
        if alt.model == model:
            return alt
    return cfg.model_copy(update={"model": model, "api_base": None, "api_key_env": None})


def endpoint(task: str, model: str | None = None) -> Endpoint:
    cfg = settings_for(task, model)
    provider = cfg.model.split("/", 1)[0]
    api_base = (os.environ.get(API_BASE_ENV) or cfg.api_base) if cfg.api_base else None
    key_env = cfg.api_key_env or (None if api_base else PROVIDER_KEYS.get(provider))
    return Endpoint(cfg.model, api_base, key_env, cfg.timeout_s, cfg.num_retries)


def _reachable(api_base: str) -> bool:
    now = time.monotonic()
    cached = _health.get(api_base)
    if cached is not None and now - cached[0] < HEALTH_TTL_S:
        return cached[1]
    try:
        ok = httpx.get(f"{api_base.rstrip('/')}/models", timeout=2.0).status_code < 500
    except httpx.HTTPError:
        ok = False
    _health[api_base] = (now, ok)
    return ok


def unavailable_reason(task: str, model: str | None = None) -> str | None:
    """Why ``task`` cannot call ``model`` right now, or None when it can."""
    ep = endpoint(task, model)
    try:
        import litellm  # noqa: F401, PLC0415
    except ImportError:
        return "the LLM client is not installed (`uv sync --extra llm`)"
    if ep.key_env and not os.environ.get(ep.key_env):
        return f"{ep.model}: {ep.key_env} is not set"
    if ep.api_base and not _reachable(ep.api_base):
        return f"{ep.model}: no LLM server answers at {ep.api_base} (`make llm-local`)"
    return None


def available(task: str, model: str | None = None) -> bool:
    return unavailable_reason(task, model) is None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = get_models().prices_per_mtok.get(model)
    if price is None:
        return None
    return round((input_tokens * price.input + output_tokens * price.output) / 1e6, 6)


def complete(task: str, messages: list[dict[str, Any]], *, model: str | None = None) -> LLMResult:
    cfg = settings_for(task, model)
    ep = endpoint(task, model)
    if (reason := unavailable_reason(task, model)) is not None:
        raise LLMUnavailableError(reason)
    import litellm  # noqa: PLC0415
    from litellm import exceptions as llm_errors  # noqa: PLC0415

    kwargs: dict[str, Any] = {
        "model": ep.model,
        "messages": messages,
        "max_tokens": cfg.max_tokens,
        "timeout": ep.timeout_s,
        "num_retries": ep.num_retries,
    }
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if ep.api_base:
        kwargs["api_base"] = ep.api_base
        # OpenAI-compatible servers want a bearer token even when they do not check it.
        kwargs["api_key"] = os.environ.get(ep.key_env, "") if ep.key_env else "not-needed"
    started = time.perf_counter()
    try:
        resp = litellm.completion(**kwargs)
    except (llm_errors.NotFoundError, llm_errors.BadRequestError) as exc:
        if "model" in str(exc).lower():
            raise ModelRejectedError(f"{ep.model} rejected by the provider: {exc}") from exc
        raise
    except (
        llm_errors.APIConnectionError,
        llm_errors.Timeout,
        llm_errors.ServiceUnavailableError,
        llm_errors.RateLimitError,
    ) as exc:
        # The endpoint is down, overloaded or too slow: the caller falls back, it does not crash.
        raise LLMUnavailableError(f"{ep.model}: {exc.__class__.__name__}") from exc
    latency = 1000 * (time.perf_counter() - started)
    choice = resp.choices[0]
    usage = getattr(resp, "usage", None)
    tin = int(getattr(usage, "prompt_tokens", 0) or 0)
    tout = int(getattr(usage, "completion_tokens", 0) or 0)
    return LLMResult(
        text=choice.message.content or "",
        model=ep.model,
        input_tokens=tin,
        output_tokens=tout,
        latency_ms=latency,
        cost_usd=estimate_cost(ep.model, tin, tout),
        finish_reason=getattr(choice, "finish_reason", None),
        prompt_hash=prompt_hash(messages),
    )
