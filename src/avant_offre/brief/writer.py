"""Brief writer: the deterministic template by default, the LLM when opted in.

``brief.writer: template`` (default) renders the template; ``llm``, or a model named by the
caller (the evaluation), asks the model. The model receives only the facts (id, label, display)
and the output contract; its text goes through the verifier; a failed or unavailable LLM gives
the template, marked ``fallback = true`` with the reason. Every brief records model, tokens,
cost, removed sentences and fallback (SPEC §6.9), and every call is traced.
"""

from __future__ import annotations

import hashlib
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
Réponds avec la note seule, en Markdown, sans préambule. Recopie exactement ce squelette, dans cet
ordre, et complète chaque section par une à trois phrases courtes. N'écris jamais deux fois la même
phrase.

## Recommandation
{band}. <une phrase qui cite les faits décisifs>

## Pourquoi
- <adéquation et références, avec citations>

## Concurrence
- <concurrents probables et ouverture du marché, avec citations>

## Prix
- <fourchette de prix des comparables, avec citations>

## Points à vérifier
- <date limite et critères non évalués, avec citations>"""


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


def cache_key(facts: BriefFacts, model: str | None = None) -> str:
    """Same facts, model settings, prompt and verifier limits give the same brief: a stored one
    is returned instead of calling the model again (the weekly batch and every reviewer opening
    the same tender share it)."""
    task = gateway.settings_for("brief_writer", model)
    cfg = get_settings().brief
    blob = json.dumps(
        {
            "facts": facts.model_dump(mode="json"),
            "model": task.model,
            "max_tokens": task.max_tokens,
            "temperature": task.temperature,
            "prompt": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
            "verifier": [cfg.max_words, cfg.max_removed],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


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
    if model is None and cfg.writer == "template":
        return _template_brief(facts, "template: brief.writer")
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


def store(
    conn: duckdb.DuckDBPyConnection, brief: Brief, facts: BriefFacts, key: str | None = None
) -> None:
    """Persist a brief. ``key`` makes it reusable; a brief written because no model answered
    is stored without one, so the next request tries the model again."""
    ensure_app_tables(conn)
    conn.execute(
        """
        INSERT INTO briefs (brief_id, notice_id, company_key, created_at, model, input_tokens,
            output_tokens, cost_usd, removed_sentences, fallback, fallback_reason, text, facts,
            cache_key, removed, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
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
            key if brief.model is not None else None,
            json.dumps([vars(r) for r in brief.removed], ensure_ascii=False),
            brief.latency_ms,
        ],
    )


def cached(conn: duckdb.DuckDBPyConnection, key: str) -> Brief | None:
    ensure_app_tables(conn)
    row = conn.execute(
        """
        SELECT brief_id, notice_id, company_key, text, model, fallback, fallback_reason, removed,
               input_tokens, output_tokens, cost_usd, latency_ms
        FROM briefs WHERE cache_key = ? ORDER BY created_at DESC LIMIT 1
        """,
        [key],
    ).fetchone()
    if row is None:
        return None
    removed = [verifier.Removed(**r) for r in json.loads(row[7] or "[]")]
    return Brief(
        brief_id=row[0],
        notice_id=row[1],
        company_key=row[2],
        text=row[3],
        model=row[4],
        fallback=bool(row[5]),
        fallback_reason=row[6],
        removed=removed,
        input_tokens=int(row[8] or 0),
        output_tokens=int(row[9] or 0),
        cost_usd=row[10],
        latency_ms=row[11],
    )
