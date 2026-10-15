"""LLM brief writer constrained to BriefFacts.

The model receives only the facts (id, label, display) and the output contract; its text goes
through the verifier; a failed or unavailable LLM gives the deterministic template, marked
``fallback = true`` with the reason. Every brief records model, tokens, cost, removed sentences
and fallback (SPEC §6.9), and every call is traced.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb

from avant_offre.brief import template, verifier
from avant_offre.brief.facts import BriefFacts
from avant_offre.llm import gateway, tracing
from avant_offre.settings import get_settings
from avant_offre.store.db import ensure_app_tables

SYSTEM = """Tu rédiges la note go/no-go d'un bureau des appels d'offres, en français.
Règles impératives :
- Utilise uniquement les faits fournis. Aucun conseil ni information au-delà des faits.
- N'écris aucun nombre, montant, pourcentage ou date qui ne figure pas dans les faits. Recopie
  la forme « display » du fait.
- Chaque phrase qui énonce un fait se termine par sa ou ses citations, par exemple [F3] ou [F3, F7].
- Cinq sections, dans cet ordre, chacune introduite par « ## » : Recommandation, Pourquoi,
  Concurrence, Prix, Points à vérifier.
- La première phrase de « Recommandation » répète exactement la recommandation de la grille
  ({band}) ; tu ne la changes jamais.
- Cite les titres de contrats entre « ».
- {max_words} mots au maximum.
Réponds avec la note seule, en Markdown, sans préambule."""


@dataclass
class Brief:
    brief_id: str
    notice_id: str
    company_key: str | None
    text: str
    model: str | None
    fallback: bool
    fallback_reason: str | None
    removed: list[verifier.Removed] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float | None = None


def messages_for(facts: BriefFacts) -> list[dict[str, str]]:
    cfg = get_settings().brief
    payload = {
        "recommandation_de_la_grille": facts.band,
        "faits": [{"id": f.id, "libellé": f.label, "display": f.display} for f in facts.facts],
    }
    return [
        {"role": "system", "content": SYSTEM.format(band=facts.band, max_words=cfg.max_words)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
    ]


def _template_brief(facts: BriefFacts, reason: str, model: str | None = None) -> Brief:
    return Brief(
        brief_id=uuid.uuid4().hex[:16],
        notice_id=facts.notice_id,
        company_key=facts.company_key,
        text=template.render(facts),
        model=model,
        fallback=True,
        fallback_reason=reason,
    )


def write(facts: BriefFacts, *, model: str | None = None) -> Brief:
    cfg = get_settings().brief
    messages = messages_for(facts)
    try:
        res = gateway.complete("brief_writer", messages, model=model)
    except gateway.LLMUnavailableError as exc:
        return _template_brief(facts, f"llm_unavailable: {exc}")
    trace = res.trace()
    if not res.ok:
        tracing.record("brief_writer", {**trace, "verifier": "not_run", "fallback": True})
        brief = _template_brief(facts, f"llm_stop:{res.finish_reason}", res.model)
    else:
        check = verifier.verify(
            res.text, facts, max_removed=cfg.max_removed, max_words=cfg.max_words
        )
        tracing.record(
            "brief_writer",
            {
                **trace,
                "verifier": "fallback" if check.fallback else "pass",
                "removed": len(check.removed),
                "fallback": check.fallback,
                "fallback_reason": check.fallback_reason,
            },
        )
        if check.fallback:
            brief = _template_brief(facts, f"verifier: {check.fallback_reason}", res.model)
            brief.removed = check.removed
        else:
            brief = Brief(
                brief_id=uuid.uuid4().hex[:16],
                notice_id=facts.notice_id,
                company_key=facts.company_key,
                text=check.text,
                model=res.model,
                fallback=False,
                fallback_reason=None,
                removed=check.removed,
            )
    brief.input_tokens, brief.output_tokens = res.input_tokens, res.output_tokens
    brief.cost_usd, brief.latency_ms = res.cost_usd, res.latency_ms
    return brief


def store(conn: duckdb.DuckDBPyConnection, brief: Brief, facts: BriefFacts) -> None:
    ensure_app_tables(conn)
    conn.execute(
        "INSERT INTO briefs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            brief.brief_id,
            brief.notice_id,
            brief.company_key,
            datetime.now(UTC),
            brief.model,
            brief.input_tokens,
            brief.output_tokens,
            brief.cost_usd,
            len(brief.removed),
            brief.fallback,
            brief.fallback_reason,
            brief.text,
            facts.model_dump_json(),
        ],
    )
