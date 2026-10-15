"""LLM fallback for facts present only in free text, with verbatim quote check.

Runs only for facts the eForms parser did not find (SPEC §6.4) and only for text facts —
required qualifications/certifications and award criteria as written — never for amounts or
dates, which must come from structured fields (DECISIONS rule 1). Output is JSON validated by
pydantic; each fact must carry the exact source quote, and the quote must be found verbatim in
the notice text (whitespace-normalized), or the fact is discarded.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field, ValidationError

from avant_offre.extract import eforms
from avant_offre.llm import gateway, tracing
from avant_offre.settings import get_models

log = logging.getLogger(__name__)

LLM_FACTS = ("qualifications", "award_criteria")
FactName = Literal["qualifications", "award_criteria"]

SYSTEM = """Tu extrais des informations d'un avis de marché public, en français.
Ne renvoie que des faits écrits dans le texte. Pour chaque fait, recopie mot pour mot la phrase
source dans "source_quote". Si un fait n'est pas dans le texte, ne le renvoie pas.
Faits recherchés : {facts}.
- qualifications : certifications, qualifications ou habilitations exigées des candidats.
- award_criteria : critères d'attribution et leur pondération, tels qu'écrits.
Réponds uniquement avec un objet JSON : {{"facts": [{{"fact": "...", "value": "...",
"source_quote": "...", "confidence": 0.0}}]}}"""


class ExtractedFact(BaseModel):
    fact: FactName
    value: str
    source_quote: str = Field(min_length=8)
    confidence: float = Field(ge=0, le=1)


class Extraction(BaseModel):
    facts: list[ExtractedFact]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# Free-text fields of the national formats sent to the model. An allowlist, so the buyer's
# contact person (name, e-mail, phone) present in the same records is never sent.
NATIONAL_TEXT_FIELDS = (
    "intitule",
    "description",
    "criteresAttrib",
    "capaciteExercice",
    "capaciteEcoFin",
    "capaciteTech",
    "principales",
    "garanties",
)


def notice_text(objet: str | None, raw_json: str | None) -> str:
    """Free text of a notice: title, eForms Description elements, national free-text fields."""
    parts = [objet or ""]
    if raw_json:
        record: Any = json.loads(raw_json)
        donnees = record.get("donnees") if isinstance(record, dict) else None
        doc: Any = json.loads(donnees) if isinstance(donnees, str) else donnees
        if doc is not None:
            for name in ("Description", *NATIONAL_TEXT_FIELDS):
                parts += [t for d in eforms.find_all(doc, name) if (t := eforms.text_of(d))]
    return "\n".join(p for p in parts if p)


def parse_response(text: str, source: str, wanted: list[str]) -> list[ExtractedFact]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return []
    try:
        extraction = Extraction.model_validate_json(match.group(0))
    except ValidationError:
        return []
    haystack = _norm(source)
    return [f for f in extraction.facts if f.fact in wanted and _norm(f.source_quote) in haystack]


def extract(
    text: str,
    missing: list[str],
    complete: Callable[[str, list[dict[str, Any]]], gateway.LLMResult] = gateway.complete,
) -> list[ExtractedFact]:
    wanted = [f for f in missing if f in LLM_FACTS]
    if not wanted or not text.strip():
        return []
    messages = [
        {"role": "system", "content": SYSTEM.format(facts=", ".join(wanted))},
        {"role": "user", "content": text},
    ]
    res = complete("fact_extractor", messages)
    kept = parse_response(res.text, text, wanted) if res.ok else []
    tracing.record("fact_extractor", {**res.trace(), "kept_facts": len(kept)})
    return kept


def run(
    conn: duckdb.DuckDBPyConnection,
    limit: int | None = None,
    complete: Callable[[str, list[dict[str, Any]]], gateway.LLMResult] = gateway.complete,
) -> dict[str, int]:
    """Fill missing text facts for tenders; writes tender_facts rows with source = llm."""
    if not get_models().llm_extraction_enabled:
        return {"skipped": 1}
    rows = conn.execute(
        """
        SELECT t.notice_id, t.objet, t.raw_json,
               list(f.fact) FILTER (WHERE f.source <> 'llm') AS have
        FROM tenders t LEFT JOIN tender_facts f USING (notice_id)
        WHERE t.duplicate_of IS NULL
        GROUP BY ALL ORDER BY t.notice_id
        """
    ).fetchall()
    counts = {"notices": 0, "facts": 0, "discarded_or_absent": 0}
    for nid, objet, raw, have in rows[:limit] if limit else rows:
        missing = [f for f in LLM_FACTS if f not in (have or [])]
        if not missing:
            continue
        counts["notices"] += 1
        try:
            facts = extract(notice_text(objet, raw), missing, complete)
        except gateway.LLMUnavailableError as exc:
            log.warning("LLM extraction skipped: %s", exc)
            return {**counts, "unavailable": 1}
        counts["facts"] += len(facts)
        counts["discarded_or_absent"] += len(missing) - len({f.fact for f in facts})
        for f in facts:
            conn.execute(
                "INSERT INTO tender_facts VALUES (?, ?, ?, 'llm', ?, ?)",
                [
                    nid,
                    f.fact,
                    json.dumps(f.value, ensure_ascii=False),
                    f.source_quote,
                    f.confidence,
                ],
            )
    return counts
