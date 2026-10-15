"""Step 4 LLM fallback: only verbatim-quoted text facts survive."""

from __future__ import annotations

import json

from avant_offre.extract import llm_extract
from avant_offre.llm import gateway

TEXT = (
    "Maintenance du parc informatique.\n"
    "Les candidats doivent détenir la certification ISO 27001 en cours de validité."
)


def _complete(payload: dict[str, object]):  # type: ignore[no-untyped-def]
    def complete(task: str, messages: list[dict[str, object]]) -> gateway.LLMResult:
        return gateway.LLMResult(json.dumps(payload), "fake", 10, 10, 1.0, 0.0, "stop", "h")

    return complete


def test_verbatim_quote_is_kept() -> None:
    payload = {
        "facts": [
            {
                "fact": "qualifications",
                "value": "ISO 27001",
                "source_quote": "doivent détenir la certification ISO 27001",
                "confidence": 0.9,
            }
        ]
    }
    out = llm_extract.extract(TEXT, ["qualifications"], _complete(payload))
    assert [f.value for f in out] == ["ISO 27001"]


def test_invented_quote_is_discarded() -> None:
    payload = {
        "facts": [
            {
                "fact": "qualifications",
                "value": "Qualibat",
                "source_quote": "La qualification Qualibat est exigée",
                "confidence": 0.9,
            }
        ]
    }
    assert llm_extract.extract(TEXT, ["qualifications"], _complete(payload)) == []


def test_numeric_facts_are_never_requested_from_the_llm() -> None:
    def boom(task: str, messages: list[dict[str, object]]) -> gateway.LLMResult:
        raise AssertionError("must not be called")

    assert llm_extract.extract(TEXT, ["estimated_value_eur", "deadline"], boom) == []


def test_malformed_json_is_ignored() -> None:
    def bad(task: str, messages: list[dict[str, object]]) -> gateway.LLMResult:
        return gateway.LLMResult("not json", "fake", 1, 1, 1.0, 0.0, "stop", "h")

    assert llm_extract.extract(TEXT, ["qualifications"], bad) == []
