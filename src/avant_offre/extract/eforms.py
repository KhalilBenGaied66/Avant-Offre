"""Parse structured eForms content of BOAMP notices.

BOAMP notices published since 31 January 2024 use EU eForms (UBL). The ``donnees`` field holds a
JSON transcription of that XML; its exact layout is unverified (DATA_QUALITY F-002), so the parser
does not depend on the nesting: it looks up eForms element names wherever they appear, ignoring
namespace prefixes (``cbc:``, ``cac:``, ``efbc:``…) and the usual XML-to-JSON text conventions
(``#text``, ``_``, ``$``, ``value``).

Facts read here are ``source = eforms``: structured fields are read, not inferred (DECISIONS
rule 1). The LLM fallback (``llm_extract``) only runs for facts this parser could not find.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

TEXT_KEYS = ("#text", "_", "$", "value", "text", "#value", "content")
ATTR_PREFIXES = ("@", "$")

FACTS = (
    "cpv_main",
    "estimated_value_eur",
    "deadline",
    "duration_months",
    "procedure_code",
    "lots",
    "award_criteria",
    "qualifications",
    "contract_folder_id",
    "buyer_siret",
)


def local(key: str) -> str:
    """'cbc:EndDate' -> 'EndDate'; '{urn:…}EndDate' -> 'EndDate'."""
    key = key.rsplit("}", 1)[-1]
    return key.rsplit(":", 1)[-1]


def text_of(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str | int | float):
        s = str(node).strip()
        return s or None
    if isinstance(node, dict):
        for k in TEXT_KEYS:
            if k in node:
                return text_of(node[k])
        return None
    if isinstance(node, list) and node:
        return text_of(node[0])
    return None


def attr_of(node: Any, name: str) -> str | None:
    if not isinstance(node, dict):
        return None
    for k, v in node.items():
        if local(k.lstrip("@$")) == name and (k.startswith(ATTR_PREFIXES) or k == name):
            return text_of(v)
        if k in ("$", "attributes", "@attributes") and isinstance(v, dict):
            found = attr_of({f"@{kk}": vv for kk, vv in v.items()}, name)
            if found:
                return found
    return None


def find_all(node: Any, name: str) -> Iterator[Any]:
    """Every value stored under an element whose local name is ``name`` (depth-first)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if local(k) == name:
                if isinstance(v, list):
                    yield from v
                else:
                    yield v
            yield from find_all(v, name)
    elif isinstance(node, list):
        for item in node:
            yield from find_all(item, name)


def first(node: Any, name: str) -> Any:
    return next(find_all(node, name), None)


def path_text(node: Any, *names: str) -> str | None:
    cur = node
    for n in names:
        cur = first(cur, n)
        if cur is None:
            return None
    return text_of(cur)


_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def to_float(s: str | None) -> float | None:
    if not s:
        return None
    m = _NUM.search(s.replace(" ", "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def to_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return date.fromisoformat(m.group(1)) if m else None


DURATION_TO_MONTHS = {"MONTH": 1.0, "YEAR": 12.0, "DAY": 12.0 / 365.25, "WEEK": 12.0 / 52.18}


@dataclass
class EformsFacts:
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        return self.values.get(name)


def _duration_months(node: Any) -> float | None:
    for d in find_all(node, "DurationMeasure"):
        value = to_float(text_of(d))
        unit = (attr_of(d, "unitCode") or "MONTH").upper()
        if value is not None and unit in DURATION_TO_MONTHS:
            return round(value * DURATION_TO_MONTHS[unit], 1)
    return None


def _criteria(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for crit in find_all(node, "SubordinateAwardingCriterion"):
        weight = None
        for param in find_all(crit, "AwardCriterionParameter"):
            code = path_text(param, "ParameterCode")
            if code is None or "weight" in code.lower() or "per-exa" in code.lower():
                weight = to_float(path_text(param, "ParameterNumeric"))
                break
        out.append(
            {
                "type": path_text(crit, "AwardingCriterionTypeCode"),
                "description": path_text(crit, "Description") or path_text(crit, "Name"),
                "weight": weight,
            }
        )
    return out


def _lots(node: Any) -> list[dict[str, Any]]:
    out = []
    for lot in find_all(node, "ProcurementProjectLot"):
        project = first(lot, "ProcurementProject")
        out.append(
            {
                "id": path_text(lot, "ID"),
                "title": path_text(project, "Name") if project is not None else None,
                "cpv": path_text(project, "ItemClassificationCode") if project else None,
                "estimated_value_eur": to_float(
                    path_text(project, "EstimatedOverallContractAmount")
                )
                if project is not None
                else None,
            }
        )
    return out


def parse(donnees: str | dict[str, Any] | None) -> EformsFacts:
    """Extract the structured facts of one notice. Missing facts are simply absent."""
    if donnees is None:
        return EformsFacts()
    if isinstance(donnees, str):
        try:
            doc: Any = json.loads(donnees)
        except json.JSONDecodeError:
            return EformsFacts()
    else:
        doc = donnees
    facts: dict[str, Any] = {}

    # Main CPV: the first classification code of the notice-level project.
    main = first(doc, "MainCommodityClassification")
    cpv = path_text(main, "ItemClassificationCode") if main is not None else None
    if cpv and (m := re.match(r"(\d{8})", cpv)):
        facts["cpv_main"] = m.group(1)

    amounts = [
        v
        for a in find_all(doc, "EstimatedOverallContractAmount")
        if (attr_of(a, "currencyID") or "EUR").upper() == "EUR"
        and (v := to_float(text_of(a))) is not None
    ]
    if amounts:
        facts["estimated_value_eur"] = max(amounts)  # notice total >= any lot

    period = first(doc, "TenderSubmissionDeadlinePeriod")
    if period is not None and (d := to_date(path_text(period, "EndDate"))):
        facts["deadline"] = d.isoformat()

    if (months := _duration_months(first(doc, "ProcurementProject") or doc)) is not None:
        facts["duration_months"] = months

    if code := path_text(doc, "ProcedureCode"):
        facts["procedure_code"] = code

    if lots := _lots(doc):
        facts["lots"] = lots

    if criteria := _criteria(doc):
        facts["award_criteria"] = criteria

    quals = [
        q
        for req in find_all(doc, "TendererQualificationRequest")
        if (q := path_text(req, "Description"))
    ]
    quals += [q for sc in find_all(doc, "SelectionCriteria") if (q := path_text(sc, "Description"))]
    if quals:
        facts["qualifications"] = quals

    if folder := path_text(doc, "ContractFolderID"):
        facts["contract_folder_id"] = folder

    party = first(doc, "ContractingParty")
    for ident in find_all(party, "PartyIdentification") if party is not None else []:
        value = re.sub(r"\s", "", path_text(ident, "ID") or "")
        if re.fullmatch(r"\d{14}", value):
            facts["buyer_siret"] = value
            break

    return EformsFacts(facts)
