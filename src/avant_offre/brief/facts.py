"""BriefFacts: every fact the brief may state, with id F1…Fn and source uids.

Values are computed upstream (SQL/Python). Each fact also carries its French display string —
the exact form the template prints and the LLM is told to copy. The verifier accepts a number in
the brief only if it matches a cited fact (DECISIONS rules 2 and step 10).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from avant_offre.intel.market import MarketIntel
from avant_offre.score.scorecard import ScoreResult
from avant_offre.search.matcher import Match

Unit = Literal["EUR", "%", "count", "days", "date", "score", "text", "band", "code"]

NNBSP = " "  # narrow no-break space: French thousands separator
NBSP = " "


def fr_int(v: float) -> str:
    return f"{round(v):,}".replace(",", NNBSP)


def fr_eur(v: float) -> str:
    """Amounts ≥ 10 000 € are rounded to the thousand: the brief is not an invoice."""
    rounded = round(v, -3) if abs(v) >= 10_000 else round(v)
    return f"{fr_int(rounded)}{NBSP}€"


def fr_pct(v: float) -> str:
    return f"{round(v)}{NBSP}%"


def fr_score(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def fr_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class Fact(BaseModel):
    id: str
    key: str
    label: str
    unit: Unit
    value: float | str | None
    display: str
    sources: list[str] = Field(default_factory=list)


class BriefFacts(BaseModel):
    notice_id: str
    company_key: str | None
    band: str
    facts: list[Fact] = Field(default_factory=list)
    price_note: str | None = None  # why no price range is given, when the reason is not n

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    def by_key(self) -> dict[str, Fact]:
        return {f.key: f for f in self.facts}

    def add(
        self,
        key: str,
        label: str,
        unit: Unit,
        value: float | str | None,
        display: str,
        sources: list[str] | None = None,
    ) -> Fact:
        fact = Fact(
            id=f"F{len(self.facts) + 1}",
            key=key,
            label=label,
            unit=unit,
            value=value,
            display=display,
            sources=sources or [],
        )
        self.facts.append(fact)
        return fact


class TenderInfo(BaseModel):
    notice_id: str
    objet: str | None
    buyer_name: str | None
    deadline_on: date | None
    estimated_value_eur: float | None
    cpv: str | None = None


def build(
    tender: TenderInfo,
    score: ScoreResult,
    *,
    match: Match | None,
    intel: MarketIntel | None,
    today: date,
    company_key: str | None,
    top_competitors: int = 3,
) -> BriefFacts:
    bf = BriefFacts(notice_id=tender.notice_id, company_key=company_key, band=score.band)
    _tender_facts(bf, tender, today)
    _score_facts(bf, score, tender.notice_id)
    if match is not None:
        _match_facts(bf, match, tender.notice_id)
    if intel is not None:
        _competition_facts(bf, intel, top_competitors)
        _price_facts(bf, intel)
    return bf


def _tender_facts(bf: BriefFacts, tender: TenderInfo, today: date) -> None:
    nid = [tender.notice_id]
    if tender.objet:
        bf.add("objet", "Objet de l'avis", "text", tender.objet, tender.objet, nid)
    if tender.buyer_name:
        bf.add("buyer", "Acheteur", "text", tender.buyer_name, tender.buyer_name, nid)
    if tender.deadline_on:
        bf.add(
            "deadline",
            "Date limite de réponse",
            "date",
            tender.deadline_on.isoformat(),
            fr_date(tender.deadline_on),
            nid,
        )
        days = (tender.deadline_on - today).days
        bf.add("days_left", "Jours restants avant la date limite", "days", days, fr_int(days), nid)
    if tender.estimated_value_eur:
        bf.add(
            "estimated_value",
            "Montant estimé indiqué dans l'avis",
            "EUR",
            tender.estimated_value_eur,
            fr_eur(tender.estimated_value_eur),
            nid,
        )


def _score_facts(bf: BriefFacts, score: ScoreResult, notice_id: str) -> None:
    nid = [notice_id]
    bf.add("band", "Recommandation de la grille", "band", score.band, score.band, nid)
    if score.total is not None:
        bf.add(
            "score", "Score de la grille (0 à 1)", "score", score.total, fr_score(score.total), nid
        )
    if score.not_assessed:
        labels = ", ".join(c.label for c in score.criteria if not c.assessed)
        bf.add("not_assessed", "Critères non évalués", "text", labels, labels, nid)
    if score.hard_stops:
        stops = "; ".join(score.hard_stops)
        bf.add("hard_stops", "Critères d'arrêt", "text", stops, stops, nid)


def _match_facts(bf: BriefFacts, match: Match, notice_id: str) -> None:
    pct = 100 * match.fit_percentile
    bf.add(
        "fit",
        "Adéquation : part des autres avis de la semaine moins bien classés",
        "%",
        pct,
        fr_pct(pct),
        [notice_id],
    )
    if match.explanations:
        e = match.explanations[0]
        when = f" ({fr_date(e.notified_on)})" if e.notified_on else ""
        bf.add(
            "closest_win",
            "Contrat passé le plus proche",
            "text",
            e.objet,
            f"« {e.objet} »{when}",
            [e.uid] if e.uid else [],
        )


def _competition_facts(bf: BriefFacts, intel: MarketIntel, top: int) -> None:
    refs = intel.company_references
    if refs is not None and refs.value is not None:
        bf.add(
            "references",
            "Références similaires de l'entreprise",
            "count",
            refs.value,
            fr_int(refs.value),
            refs.sources,
        )
    bf.add(
        "n_comparables",
        "Contrats comparables analysés",
        "count",
        intel.n_comparables,
        fr_int(intel.n_comparables),
        [c.uid for c in intel.comparables],
    )
    for i, comp in enumerate(intel.competitors[:top], start=1):
        flag = (
            ", déjà titulaire chez cet acheteur"
            if comp.incumbent_with_buyer
            else ", nouveau chez cet acheteur"
            if comp.new_to_buyer
            else ""
        )
        detail = (
            f"{comp.name} ({fr_int(comp.comparable_wins)} contrats comparables remportés{flag})"
        )
        bf.add(
            f"competitor_{i}", f"Concurrent probable n°{i}", "text", comp.name, detail, comp.sources
        )
    ns = intel.newcomer_share
    if ns.value is not None:
        bf.add(
            "newcomer_share",
            "Part des contrats comparables remportés par un primo-titulaire",
            "%",
            ns.value,
            fr_pct(ns.value),
            ns.sources,
        )
        bf.add(
            "newcomer_n",
            "Contrats comparables pris en compte (nouveaux entrants)",
            "count",
            ns.n,
            fr_int(ns.n),
            ns.sources,
        )
    bt = intel.buyer_top_winner_share
    if bt.value is not None:
        bf.add(
            "buyer_top_share",
            "Part des contrats comparables de l'acheteur remportés par son premier titulaire",
            "%",
            bt.value,
            fr_pct(bt.value),
            bt.sources,
        )
    if intel.sme_share.value is not None:
        bf.add(
            "sme_share",
            "Part des comparables remportés par une PME",
            "%",
            intel.sme_share.value,
            fr_pct(intel.sme_share.value),
            intel.sme_share.sources,
        )
    if intel.bids_received.value is not None:
        bf.add(
            "bids_median",
            "Offres reçues (médiane des comparables)",
            "count",
            intel.bids_received.value,
            fr_int(intel.bids_received.value),
            intel.bids_received.sources,
        )


def _price_facts(bf: BriefFacts, intel: MarketIntel) -> None:
    pr = intel.price_range
    bf.price_note = pr.note
    if pr.p25 is not None and pr.p50 is not None and pr.p75 is not None:
        for key, label, value in (
            ("price_p25", "Prix des comparables, 1er quartile", pr.p25),
            ("price_p50", "Prix des comparables, médiane", pr.p50),
            ("price_p75", "Prix des comparables, 3e quartile", pr.p75),
        ):
            bf.add(key, label, "EUR", value, fr_eur(value), pr.sources)
    bf.add(
        "price_n",
        "Contrats comparables avec un prix exploitable",
        "count",
        pr.n,
        fr_int(pr.n),
        pr.sources,
    )
