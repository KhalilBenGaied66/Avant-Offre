"""LLM gateway: endpoint resolution, availability, the call it makes, and graceful failure."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from litellm import exceptions as llm_errors

from avant_offre.llm import gateway
from avant_offre.settings import get_models

WRITER = "brief_writer"


@pytest.fixture(autouse=True)
def _no_health_cache() -> None:
    gateway._health.clear()


def test_task_model_uses_its_own_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(gateway.API_BASE_ENV)  # set by the test fixture
    cfg = get_models().tasks[WRITER]
    ep = gateway.endpoint(WRITER)
    assert ep.model == cfg.model and ep.api_base == cfg.api_base
    assert ep.key_env == cfg.api_key_env  # a self-hosted endpoint needs no provider key


def test_alternative_uses_its_own_settings() -> None:
    alt = get_models().alternatives[0]
    assert gateway.settings_for(WRITER, alt.model).max_tokens == alt.max_tokens
    ep = gateway.endpoint(WRITER, alt.model)
    assert ep.api_base is None and ep.key_env == gateway.PROVIDER_KEYS.get(alt.model.split("/")[0])


def test_deployment_overrides_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gateway.API_BASE_ENV, "https://llm.example.test/v1")
    assert gateway.endpoint(WRITER).api_base == "https://llm.example.test/v1"


def test_unreachable_server_is_unavailable_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "_reachable", lambda base: False)
    assert "no LLM server answers" in (gateway.unavailable_reason(WRITER) or "")
    with pytest.raises(gateway.LLMUnavailableError):
        gateway.complete(WRITER, [{"role": "user", "content": "x"}])


def test_missing_key_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reason = gateway.unavailable_reason(WRITER, "anthropic/claude-sonnet-5-5")
    assert reason is not None and "ANTHROPIC_API_KEY" in reason


def _response(text: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )


def test_call_carries_endpoint_timeout_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _response("## Recommandation\nGO.")

    monkeypatch.setattr(gateway, "_reachable", lambda base: True)
    monkeypatch.setattr(litellm, "completion", fake)
    res = gateway.complete(WRITER, [{"role": "user", "content": "x"}])
    cfg = get_models().tasks[WRITER]
    assert seen["api_base"] == gateway.endpoint(WRITER).api_base
    assert seen["api_key"] == "not-needed"
    assert seen["timeout"] == cfg.timeout_s and seen["num_retries"] == cfg.num_retries
    assert seen["temperature"] == cfg.temperature and seen["max_tokens"] == cfg.max_tokens
    assert res.ok and res.cost_usd == 0  # self-hosted: no per-token price


def test_connection_error_becomes_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(**kwargs: Any) -> Any:
        raise llm_errors.APIConnectionError(message="refused", llm_provider="openai", model="m")

    monkeypatch.setattr(gateway, "_reachable", lambda base: True)
    monkeypatch.setattr(litellm, "completion", down)
    with pytest.raises(gateway.LLMUnavailableError):
        gateway.complete(WRITER, [{"role": "user", "content": "x"}])
