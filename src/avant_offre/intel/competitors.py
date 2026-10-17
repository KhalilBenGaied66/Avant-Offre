"""Likely competitors: recency- and similarity-weighted winners of comparable awards.

score(company) = Σ over comparables it won of
    similarity × exp(−age_days / τ) × (1 + same_buyer_boost × [same buyer])
with τ and the boost from config (``intel.tau_days``, ``intel.same_buyer_boost``).

Flags:
- ``incumbent_with_buyer`` — won at least one comparable award from this buyer;
- ``new_to_buyer``         — no award at all from this buyer before the history cutoff.

Newcomers are not named: a company with no public award history cannot appear here; the brief
shows the newcomer share instead (DECISIONS, "What the data can't predict").

``CompetitorModel`` preloads winners and buyer histories once, so the backtest scores thousands
of awards without one SQL query each.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

import duckdb
from pydantic import BaseModel, Field

from avant_offre.intel.comparables import Comparable
from avant_offre.settings import get_settings
from avant_offre.transform.privacy import public_key


class Competitor(BaseModel):
    company_key: str = Field(exclude=True)  # internal (SIREN): never serialized
    public_id: str  # privacy.public_key: the SIREN of a legal person, an opaque hash otherwise
    name: str
    score: float
    comparable_wins: int
    last_win_on: date | None
    incumbent_with_buyer: bool
    new_to_buyer: bool
    sources: list[str] = Field(default_factory=list)


class CompetitorModel:
    def __init__(self, conn: duckdb.DuckDBPyConnection, history_before: date | None = None):
        """Winners of awards dated before ``history_before`` (all past awards when None)."""
        self.winners: dict[str, list[str]] = defaultdict(list)
        self.buyer_history: set[tuple[str, str]] = set()
        for uid, key, buyer in conn.execute(
            """
            SELECT DISTINCT w.uid, w.company_key, a.buyer_siret
            FROM award_winners w JOIN awards a USING (uid)
            WHERE w.company_key IS NOT NULL
              AND (CAST(? AS DATE) IS NULL OR a.notified_on < ?)
            """,
            [history_before, history_before],
        ).fetchall():
            self.winners[uid].append(key)
            if buyer:
                self.buyer_history.add((key, buyer))
        self.names: dict[str, str] = {}
        self.public_ids: dict[str, str] = {}
        for key, name, natural in conn.execute(
            "SELECT company_key, display_name, is_natural_person FROM company_names"
        ).fetchall():
            self.names[key] = name
            self.public_ids[key] = public_key(key, natural)

    def predict(
        self,
        comparables: Sequence[Comparable],
        ref_date: date,
        buyer_siret: str | None,
        *,
        exclude: str | None = None,
        top: int | None = None,
    ) -> list[Competitor]:
        cfg = get_settings().intel
        top = top or cfg.top_competitors
        score: dict[str, float] = defaultdict(float)
        wins: dict[str, list[str]] = defaultdict(list)
        last: dict[str, date] = {}
        with_buyer: set[str] = set()
        for c in comparables:
            age = max(0, (ref_date - c.notified_on).days)
            same_buyer = bool(buyer_siret) and c.buyer_siret == buyer_siret
            weight = (
                c.similarity
                * math.exp(-age / cfg.tau_days)
                * (1 + cfg.same_buyer_boost * same_buyer)
            )
            for key in self.winners.get(c.uid, []):
                if key == exclude:
                    continue
                score[key] += weight
                wins[key].append(c.uid)
                last[key] = max(last.get(key, c.notified_on), c.notified_on)
                if same_buyer:
                    with_buyer.add(key)
        ranked = sorted(score, key=lambda k: (-score[k], k))[:top]
        return [
            Competitor(
                company_key=k,
                public_id=self.public_ids.get(k) or public_key(k, None),
                name=self.names.get(k, "Titulaire non vérifié"),
                score=round(score[k], 6),
                comparable_wins=len(wins[k]),
                last_win_on=last.get(k),
                incumbent_with_buyer=k in with_buyer,
                new_to_buyer=not buyer_siret or (k, buyer_siret) not in self.buyer_history,
                sources=wins[k],
            )
            for k in ranked
        ]

    def buyer_top_share(
        self, comparables: Sequence[Comparable], buyer_siret: str | None
    ) -> tuple[float | None, int, list[str]]:
        """Share of the buyer's comparable awards won by its most frequent winner."""
        if not buyer_siret:
            return None, 0, []
        own = [c.uid for c in comparables if c.buyer_siret == buyer_siret]
        if not own:
            return None, 0, []
        counts: dict[str, int] = defaultdict(int)
        for uid in own:
            for key in set(self.winners.get(uid, [])):
                counts[key] += 1
        if not counts:
            return None, len(own), own
        return max(counts.values()) / len(own), len(own), own
