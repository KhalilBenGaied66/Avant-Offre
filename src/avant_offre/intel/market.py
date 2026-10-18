"""Market intelligence for one tender (or one test award in a backtest). No AI.

Pure aggregation over the comparables found by step-6 search: likely competitors, newcomer
share, price range, SME win share, bids received, the buyer's concentration, and the company's
own references. Every value carries its n and the award uids behind it.
"""

from __future__ import annotations

from datetime import date

import duckdb
from pydantic import BaseModel, Field

from avant_offre.intel import prices, stats
from avant_offre.intel.comparables import Comparable, ComparablesIndex
from avant_offre.intel.competitors import Competitor, CompetitorModel
from avant_offre.intel.prices import PriceRange
from avant_offre.intel.stats import Stat
from avant_offre.settings import get_settings


class ComparableView(BaseModel):
    uid: str
    similarity: float
    notified_on: date
    buyer_name: str | None
    objet: str | None
    amount_eur: float | None
    is_framework: bool


class MarketIntel(BaseModel):
    reference: str
    ref_date: date
    buyer_siret: str | None
    n_comparables: int
    comparables: list[ComparableView] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)
    newcomer_share: Stat
    price_range: PriceRange
    sme_share: Stat
    bids_received: Stat
    buyer_top_winner_share: Stat
    company_references: Stat | None = None


def compute(
    conn: duckdb.DuckDBPyConnection,
    index: ComparablesIndex,
    model: CompetitorModel,
    *,
    reference: str,
    text: str,
    ref_date: date,
    buyer_siret: str | None,
    company_key: str | None = None,
    depts: list[str] | None = None,
    division: str | None = None,
    buyer_name: str | None = None,
) -> MarketIntel:
    cfg = get_settings().intel
    comps: list[Comparable] = index.search(text, ref_date, depts=depts, buyer_name=buyer_name)
    uids = [c.uid for c in comps]
    share, n_buyer, buyer_uids = model.buyer_top_share(comps, buyer_siret)
    references = None
    if company_key is not None:
        own = [
            c.uid
            for c in comps
            if c.similarity >= cfg.references_similarity
            and company_key in model.winners.get(c.uid, [])
        ]
        references = Stat(value=float(len(own)), n=len(comps), sources=own)
    return MarketIntel(
        reference=reference,
        ref_date=ref_date,
        buyer_siret=buyer_siret,
        n_comparables=len(comps),
        comparables=[
            ComparableView(
                uid=c.uid,
                similarity=c.similarity,
                notified_on=c.notified_on,
                buyer_name=c.buyer_name,
                objet=c.objet,
                amount_eur=None if c.is_framework or c.is_dynamic_system else c.amount_eur,
                is_framework=c.is_framework,
            )
            for c in comps[: cfg.display_comparables]
        ],
        competitors=model.predict(comps, ref_date, buyer_siret, exclude=company_key),
        newcomer_share=stats.newcomer_share(conn, uids, cfg.left_censor_months),
        price_range=prices.price_range(comps, division=division),
        sme_share=stats.sme_share(conn, uids),
        bids_received=stats.bids_received(comps),
        buyer_top_winner_share=Stat(
            value=None if share is None else 100.0 * share,
            n=n_buyer,
            sources=buyer_uids,
            note=None if share is not None else "aucun contrat comparable chez cet acheteur",
        ),
        company_references=references,
    )


def for_tender(
    conn: duckdb.DuckDBPyConnection,
    notice_id: str,
    index: ComparablesIndex,
    model: CompetitorModel,
    *,
    company_key: str | None = None,
    today: date | None = None,
) -> MarketIntel:
    row = conn.execute(
        "SELECT objet, buyer_siret, cpv_division, buyer_name FROM tenders WHERE notice_id = ?",
        [notice_id],
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown notice {notice_id}")
    return compute(
        conn,
        index,
        model,
        reference=notice_id,
        text=row[0] or "",
        ref_date=today or date.today(),
        buyer_siret=row[1],
        company_key=company_key,
        division=row[2],
        buyer_name=row[3],
    )
