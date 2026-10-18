"""Weighted scorecard defined in config/scorecard.yaml and owned by the bid team. No AI.

Each criterion maps one computed input to [0, 1]:
- ``fit``            — percentile of the step-6 match score among this week's tenders;
- ``references``     — the company's past wins among the comparables, ``full_at`` or more = 1;
- ``incumbent_risk`` — 1 − share of the buyer's comparable awards won by its top winner;
- ``openness``       — newcomer share (step 7);
- ``price_realism``  — 1 inside [P25, P75], then linear decay in log space to 0 at
                       ``zero_at_factor`` × outside the interval;
- ``deadline``       — days to deadline / ``comfortable_days``, capped at 1.
A missing input is never imputed: the criterion is listed as not assessed and its weight leaves
the denominator. Hard stops force NO-GO and say why. The band thresholds are the bid team's.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from avant_offre.intel.market import MarketIntel
from avant_offre.settings import ScorecardConfig, get_scorecard

Band = Literal["GO", "REVIEW", "NO-GO"]

CRITERION_LABELS = {
    "fit": "Adéquation au profil",
    "references": "Références similaires",
    "incumbent_risk": "Risque sortant",
    "openness": "Ouverture du marché",
    "price_realism": "Réalisme du prix",
    "deadline": "Délai de réponse",
}


class TenderInputs(BaseModel):
    notice_id: str
    deadline_on: date | None
    estimated_value_eur: float | None
    dept: str | None
    fit_percentile: float | None


class CriterionResult(BaseModel):
    id: str
    label: str
    weight: float
    value: float | None
    input: float | None
    assessed: bool
    note: str | None = None


class ScoreResult(BaseModel):
    notice_id: str
    total: float | None
    band: Band
    criteria: list[CriterionResult]
    not_assessed: list[str] = Field(default_factory=list)
    assessed_weight: float
    hard_stops: list[str] = Field(default_factory=list)


def price_realism(value: float, p25: float, p75: float, zero_at_factor: float) -> float:
    if p25 <= value <= p75:
        return 1.0
    bound = p25 if value < p25 else p75
    distance = abs(math.log(value / bound))
    return max(0.0, 1.0 - distance / math.log(zero_at_factor))


Outcome = tuple[float | None, float | None, str | None]  # (raw input, value in [0, 1], note)


def _fit(p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date) -> Outcome:
    f = t.fit_percentile
    return (f, f, None) if f is not None else (None, None, "pas de score d'adéquation")


def _deadline(
    p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date
) -> Outcome:
    if t.deadline_on is None:
        return None, None, "deadline unknown"
    days = (t.deadline_on - today).days
    return float(days), max(0.0, min(1.0, days / p.get("comfortable_days", 30))), None


def _references(
    p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date
) -> Outcome:
    refs = intel.company_references if intel else None
    if refs is None or refs.value is None:
        return None, None, "pas de profil d'entreprise"
    return refs.value, min(1.0, refs.value / p.get("full_at", 3)), None


def _incumbent(
    p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date
) -> Outcome:
    if intel is None or intel.buyer_top_winner_share.value is None:
        return (
            None,
            None,
            intel.buyer_top_winner_share.note if intel else "pas de données de marché",
        )
    share = intel.buyer_top_winner_share.value
    return share, 1.0 - share / 100.0, None


def _openness(
    p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date
) -> Outcome:
    if intel is None or intel.newcomer_share.value is None:
        return None, None, intel.newcomer_share.note if intel else "pas de données de marché"
    return intel.newcomer_share.value, intel.newcomer_share.value / 100.0, None


def _price(p: dict[str, float], t: TenderInputs, intel: MarketIntel | None, today: date) -> Outcome:
    v = t.estimated_value_eur
    if v is None or v <= 0:
        return None, None, "pas de montant estimé dans l'avis"
    pr = intel.price_range if intel else None
    if pr is not None and pr.note:
        return v, None, pr.note
    if pr is None or pr.p25 is None or pr.p75 is None:
        return v, None, f"fourchette de prix non évaluée (n = {pr.n if pr else 0})"
    return v, price_realism(v, pr.p25, pr.p75, p.get("zero_at_factor", 4.0)), None


CRITERIA = {
    "fit": _fit,
    "references": _references,
    "incumbent_risk": _incumbent,
    "openness": _openness,
    "price_realism": _price,
    "deadline": _deadline,
}


def hard_stop_reasons(tender: TenderInputs, cfg: ScorecardConfig, today: date) -> list[str]:
    hs = cfg.hard_stops
    out = []
    if (
        hs.min_days_to_deadline is not None
        and tender.deadline_on is not None
        and (tender.deadline_on - today).days < hs.min_days_to_deadline
    ):
        out.append(f"date limite dans moins de {hs.min_days_to_deadline} jours")
    if (
        hs.max_amount_eur is not None
        and tender.estimated_value_eur is not None
        and tender.estimated_value_eur > hs.max_amount_eur
    ):
        out.append("montant estimé au-dessus du maximum")
    if hs.allowed_departments is not None and tender.dept not in hs.allowed_departments:
        out.append("département hors périmètre")
    return out


def score(
    tender: TenderInputs,
    intel: MarketIntel | None,
    today: date,
    cfg: ScorecardConfig | None = None,
) -> ScoreResult:
    cfg = cfg or get_scorecard()
    results = []
    for c in cfg.criteria:
        raw, value, note = CRITERIA[c.id](c.params, tender, intel, today)
        results.append(
            CriterionResult(
                id=c.id,
                label=CRITERION_LABELS[c.id],
                weight=c.weight,
                value=None if value is None else round(value, 4),
                input=raw,
                assessed=value is not None,
                note=note,
            )
        )
    assessed = [r for r in results if r.assessed]
    weight = sum(r.weight for r in assessed)
    total = (
        round(sum(r.weight * (r.value or 0.0) for r in assessed) / weight, 4) if weight else None
    )
    stops = hard_stop_reasons(tender, cfg, today)
    band: Band
    if stops:
        band = "NO-GO"
    elif total is None:
        band = "REVIEW"
    elif total >= cfg.bands.go:
        band = "GO"
    elif total >= cfg.bands.review:
        band = "REVIEW"
    else:
        band = "NO-GO"
    return ScoreResult(
        notice_id=tender.notice_id,
        total=total,
        band=band,
        criteria=results,
        not_assessed=[r.id for r in results if not r.assessed],
        assessed_weight=round(weight, 4),
        hard_stops=stops,
    )
