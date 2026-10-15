"""Parse the French national BOAMP notice formats (``FNSimple``, ``MAPA``).

Many open BOAMP notices are not eForms but national formats used below the EU thresholds
(shares in the generated "Notice formats" table of DATA_QUALITY.md, finding F-005).
``FNSimple`` and ``MAPA`` are parsed here; ``DSP`` and ``DIVERS`` are rare and not parsed.
These formats have named, shallow fields, so they are read by path.

Free text is copied as written, never interpreted: FNSimple award criteria are a paragraph and
are left to the LLM fallback with its verbatim-quote check; a MAPA duration given only as a
sentence stays missing. A price range is not turned into a point estimate.
"""

from __future__ import annotations

import re
from typing import Any

from avant_offre.extract.eforms import (
    DURATION_TO_MONTHS,
    months_between,
    text_of,
    to_date,
    to_float,
)

FORMATS = ("FNSimple", "MAPA")
NOT_PARSED = ("DSP", "DIVERS")


def _get(node: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _as_list(node: Any) -> list[Any]:
    if node is None or node == "":
        return []
    return node if isinstance(node, list) else [node]


def _text(node: Any, *path: str) -> str | None:
    return text_of(_get(node, *path))


def _cpv(node: Any) -> str | None:
    code = _text(node, "objetPrincipal", "classPrincipale")
    m = re.match(r"(\d{8})", code or "")
    return m.group(1) if m else None


def _eur(node: Any) -> float | None:
    """A point value in euros (``{"@devise": "EUR", "valeur": "135000"}``); ranges give None."""
    if not isinstance(node, dict) or (_text(node, "@devise") or "EUR").upper() != "EUR":
        return None
    return to_float(_text(node, "valeur"))


def _date(node: Any, *path: str) -> str | None:
    d = to_date(_text(node, *path))
    return d.isoformat() if d else None


def _fnsimple(body: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    initial = _get(body, "initial")
    nature = _get(initial, "natureMarche")
    procedure = _get(initial, "procedure")

    lots = [
        {
            "id": str(i),
            "title": _text(lot, "description"),
            "cpv": _cpv(_get(lot, "codeCPV")),
            "estimated_value_eur": _eur(_get(lot, "estimationValeur")),
        }
        for i, lot in enumerate(_as_list(_get(initial, "lots", "lot")), 1)
    ]
    if lots:
        facts["lots"] = lots

    if cpv := _cpv(_get(nature, "codeCPV")) or next((x["cpv"] for x in lots if x["cpv"]), None):
        facts["cpv_main"] = cpv

    value = _eur(_get(nature, "valeurEstimee"))
    lot_values = [v for x in lots if isinstance(v := x["estimated_value_eur"], float)]
    if value is None and lots and len(lot_values) == len(lots):
        value = sum(lot_values)
    if value is not None:
        facts["estimated_value_eur"] = value

    if deadline := _date(procedure, "dateReceptionOffres"):
        facts["deadline"] = deadline

    if (months := to_float(_text(nature, "dureeMois"))) is not None:
        facts["duration_months"] = months

    quals = [
        q
        for key in ("capaciteExercice", "capaciteEcoFin", "capaciteTech")
        if (q := _text(procedure, key))
    ]
    if quals:
        facts["qualifications"] = quals

    organisme = _get(body, "organisme")
    if "siret" in (_get(organisme, "typeIdentificationNational") or {}):
        siret = re.sub(r"\s", "", _text(organisme, "codeIdentificationNational") or "")
        if re.fullmatch(r"\d{14}", siret):
            facts["buyer_siret"] = siret
    return facts


def _mapa_duration(duree: Any) -> float | None:
    if (months := to_float(_text(duree, "nbMois"))) is not None:
        return months
    if (days := to_float(_text(duree, "nbJours"))) is not None:
        return round(days * DURATION_TO_MONTHS["DAY"], 1)
    start, end = to_date(_text(duree, "dateACompterDu")), to_date(_text(duree, "dateJusquau"))
    return months_between(start, end) if start and end else None


def _mapa(body: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    initial = _get(body, "initial")

    if deadline := _date(initial, "delais", "receptionOffres"):
        facts["deadline"] = deadline

    # `delais/validite` is how long a bid stays valid, not the contract duration.
    if (months := _mapa_duration(_get(initial, "duree"))) is not None:
        facts["duration_months"] = months

    criteria = [
        {
            "type": None,
            "description": _text(c, "critere"),
            "weight": to_float(_text(c, "criterePCT")),
        }
        for c in _as_list(_get(initial, "criteres", "criterePondere"))
        if _text(c, "critere")
    ]
    if criteria:
        facts["award_criteria"] = criteria

    lots = [
        {
            "id": _text(lot, "numLot") or str(i),
            "title": _text(lot, "description"),
            "cpv": None,
            "estimated_value_eur": None,
        }
        for i, lot in enumerate(_as_list(_get(initial, "lots", "lot")), 1)
    ]
    if lots:
        facts["lots"] = lots
    return facts


def parse(fmt: str, body: Any) -> dict[str, Any]:
    """Facts of one national-format notice; ``fmt`` is the top-level key of ``donnees``."""
    if fmt == "FNSimple":
        return _fnsimple(body)
    if fmt == "MAPA":
        return _mapa(body)
    return {}
