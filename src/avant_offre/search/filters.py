"""Step 5 — SQL eligibility filters, each exclusion with a reason code. No AI.

Rules come from the bid team's hard stops (``config/scorecard.yaml``: minimum days to deadline,
maximum amount, allowed departments) and ``settings.filters`` (minimum amount, procedures,
excluded CPV divisions). A tender is eligible when it has no reason code. Unknown values never
exclude except the deadline: a tender whose deadline is unknown cannot be planned, so it is
listed with ``deadline_missing`` for a person to check. User-provided values are bound as
parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import duckdb

from avant_offre.settings import get_scorecard, get_settings

REASON_LABELS: dict[str, str] = {
    "duplicate": "Doublon d'un autre avis",
    "deadline_missing": "Date limite de réponse inconnue",
    "deadline_too_close": "Date limite trop proche",
    "department_excluded": "Hors des départements retenus",
    "amount_below_min": "Montant estimé sous le minimum",
    "amount_above_max": "Montant estimé au-dessus du maximum",
    "procedure_excluded": "Procédure non retenue",
    "cpv_division_excluded": "Domaine CPV exclu",
}


@dataclass(frozen=True)
class FilterRules:
    min_days_to_deadline: int = 0
    allowed_departments: list[str] | None = None
    min_amount_eur: float | None = None
    max_amount_eur: float | None = None
    procedures: list[str] | None = None
    excluded_cpv_divisions: list[str] = field(default_factory=list)


def default_rules() -> FilterRules:
    hs = get_scorecard().hard_stops
    f = get_settings().filters
    return FilterRules(
        min_days_to_deadline=hs.min_days_to_deadline or 0,
        allowed_departments=hs.allowed_departments,
        min_amount_eur=f.min_amount_eur,
        max_amount_eur=hs.max_amount_eur,
        procedures=f.procedures,
        excluded_cpv_divisions=list(f.excluded_cpv_divisions),
    )


@dataclass(frozen=True)
class Eligibility:
    notice_id: str
    reasons: list[str]

    @property
    def eligible(self) -> bool:
        return not self.reasons

    @property
    def labels(self) -> list[str]:
        return [REASON_LABELS.get(r, r) for r in self.reasons]


SQL = """
SELECT notice_id, list_filter([
    CASE WHEN duplicate_of IS NOT NULL THEN 'duplicate' END,
    CASE WHEN deadline_on IS NULL THEN 'deadline_missing' END,
    CASE WHEN deadline_on < CAST($today AS DATE) + CAST($min_days AS INTEGER)
         THEN 'deadline_too_close' END,
    CASE WHEN $depts IS NOT NULL AND (dept IS NULL OR NOT list_contains($depts, dept))
         THEN 'department_excluded' END,
    CASE WHEN $min_amount IS NOT NULL AND estimated_value_eur < $min_amount
         THEN 'amount_below_min' END,
    CASE WHEN $max_amount IS NOT NULL AND estimated_value_eur > $max_amount
         THEN 'amount_above_max' END,
    CASE WHEN $procedures IS NOT NULL AND procedure IS NOT NULL
              AND NOT list_contains($procedures, procedure)
         THEN 'procedure_excluded' END,
    CASE WHEN list_contains($excluded_divs, cpv_division) THEN 'cpv_division_excluded' END
], x -> x IS NOT NULL) AS reasons
FROM tenders
ORDER BY notice_id
"""


def eligibility(
    conn: duckdb.DuckDBPyConnection, today: date, rules: FilterRules | None = None
) -> list[Eligibility]:
    r = rules or default_rules()
    rows = conn.execute(
        SQL,
        {
            "today": today,
            "min_days": r.min_days_to_deadline,
            "depts": r.allowed_departments,
            "min_amount": r.min_amount_eur,
            "max_amount": r.max_amount_eur,
            "procedures": r.procedures,
            "excluded_divs": r.excluded_cpv_divisions or [],
        },
    ).fetchall()
    return [Eligibility(nid, list(reasons)) for nid, reasons in rows]
