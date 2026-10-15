"""Application service shared by the CLI, the HTTP API, the MCP server and the digest.

One ``Engine`` per request scope: it holds the DuckDB connection, the reference date, and the
lazily built search and competitor models. Every output that names a winner goes through
``company_names`` (personal data rule). Nothing here writes outside the local store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb
from pydantic import BaseModel, Field

from avant_offre.brief import facts as brief_facts
from avant_offre.brief import writer
from avant_offre.intel import market
from avant_offre.intel.comparables import ComparablesIndex, live_index
from avant_offre.intel.competitors import CompetitorModel
from avant_offre.intel.market import MarketIntel
from avant_offre.score import scorecard
from avant_offre.score.scorecard import ScoreResult, TenderInputs
from avant_offre.search import filters, matcher, profile
from avant_offre.search.matcher import Match
from avant_offre.search.profile import Profile
from avant_offre.store.db import fetch_dicts, fetch_one, table_exists


class NotFoundError(KeyError):
    pass


class ShortlistItem(BaseModel):
    notice_id: str
    rank: int
    fit_percentile: float
    band: str
    total: float | None
    deadline_on: date | None
    published_on: date | None
    buyer_name: str | None
    objet: str | None
    dept: str | None
    url: str | None
    explanations: list[dict[str, Any]] = Field(default_factory=list)


class Excluded(BaseModel):
    notice_id: str
    objet: str | None
    deadline_on: date | None
    reasons: list[str]
    labels: list[str]


class Shortlist(BaseModel):
    company_key: str | None
    week_start: date
    week_end: date
    eligible: list[ShortlistItem]
    excluded: list[Excluded]


def week_bounds(week: str | None, today: date) -> tuple[date, date]:
    """ISO week 'YYYY-Www' -> [monday, next monday). Default: the 7 days up to today."""
    if not week:
        return today - timedelta(days=7), today + timedelta(days=1)
    year, w = week.upper().split("-W")
    monday = date.fromisocalendar(int(year), int(w), 1)
    return monday, monday + timedelta(days=7)


@dataclass
class Engine:
    conn: duckdb.DuckDBPyConnection
    today: date = field(default_factory=date.today)
    _index: ComparablesIndex | None = None
    _competitors: CompetitorModel | None = None
    _matches: dict[str, dict[str, Match]] = field(default_factory=dict)

    # ---- inputs --------------------------------------------------------------------------
    def require(self, table: str) -> None:
        if not table_exists(self.conn, table):
            raise NotFoundError(f"no {table} in the store: run `make data-sample` first")

    def profile(self, siret: str | None = None, free_text: str | None = None) -> Profile:
        if siret:
            key = profile.company_key_for(self.conn, siret)
            if key is None:
                raise NotFoundError(f"{siret}: no award in the store; use a free-text profile")
            return profile.from_company(self.conn, key, self.today)
        if free_text:
            return profile.from_free_text(free_text, self.today)
        raise ValueError("a SIRET/SIREN or a free-text description is required")

    @property
    def index(self) -> ComparablesIndex:
        if self._index is None:
            self._index = live_index(self.conn)
        return self._index

    @property
    def competitors(self) -> CompetitorModel:
        if self._competitors is None:
            self._competitors = CompetitorModel(self.conn, history_before=self.today)
        return self._competitors

    # ---- steps 5–6 -----------------------------------------------------------------------
    def shortlist(self, prof: Profile, week: str | None = None) -> Shortlist:
        self.require("tenders")
        start, end = week_bounds(week, self.today)
        in_week = {
            r[0]
            for r in self.conn.execute(
                "SELECT notice_id FROM tenders WHERE published_on >= ? AND published_on < ?",
                [start, end],
            ).fetchall()
        }
        elig = [e for e in filters.eligibility(self.conn, self.today) if e.notice_id in in_week]
        ok = [e.notice_id for e in elig if e.eligible]
        matches = matcher.match_tenders(self.conn, prof, ok)
        self._matches[prof.profile_id] = {m.notice_id: m for m in matches}
        rows = {
            r["notice_id"]: r
            for r in fetch_dicts(
                self.conn,
                "SELECT notice_id, objet, buyer_name, deadline_on, published_on, dept, url, "
                "estimated_value_eur FROM tenders WHERE notice_id IN (SELECT unnest(?))",
                [list(in_week)],
            )
        }
        items = []
        for m in matches:
            r = rows[m.notice_id]
            sc = self.score(m.notice_id, prof)
            items.append(
                ShortlistItem(
                    notice_id=m.notice_id,
                    rank=m.rank,
                    fit_percentile=m.fit_percentile,
                    band=sc.band,
                    total=sc.total,
                    deadline_on=r["deadline_on"],
                    published_on=r["published_on"],
                    buyer_name=r["buyer_name"],
                    objet=r["objet"],
                    dept=r["dept"],
                    url=r["url"],
                    explanations=[e.__dict__ for e in m.explanations],
                )
            )
        excluded = [
            Excluded(
                notice_id=e.notice_id,
                objet=rows[e.notice_id]["objet"],
                deadline_on=rows[e.notice_id]["deadline_on"],
                reasons=e.reasons,
                labels=e.labels,
            )
            for e in elig
            if not e.eligible
        ]
        return Shortlist(
            company_key=prof.company_key,
            week_start=start,
            week_end=end,
            eligible=items,
            excluded=excluded,
        )

    def match_for(self, notice_id: str, prof: Profile) -> Match | None:
        cached = self._matches.get(prof.profile_id)
        if cached is None:
            self.shortlist(prof)
            cached = self._matches.get(prof.profile_id, {})
        return cached.get(notice_id)

    # ---- steps 7–10 ----------------------------------------------------------------------
    def tender(self, notice_id: str) -> dict[str, Any]:
        self.require("tenders")
        row = fetch_one(
            self.conn,
            "SELECT notice_id, source, buyer_name, buyer_siret, objet, published_on, "
            "deadline_on, dept, cpv, procedure, estimated_value_eur, url, duplicate_of, "
            "dedup_reason FROM tenders WHERE notice_id = ?",
            [notice_id],
        )
        if row is None:
            raise NotFoundError(f"unknown notice {notice_id}")
        row["facts"] = fetch_dicts(
            self.conn,
            "SELECT fact, value, source, source_quote, confidence FROM tender_facts "
            "WHERE notice_id = ? ORDER BY fact, source",
            [notice_id],
        )
        return row

    def intel(self, notice_id: str, company_key: str | None = None) -> MarketIntel:
        self.tender(notice_id)
        return market.for_tender(
            self.conn,
            notice_id,
            self.index,
            self.competitors,
            company_key=company_key,
            today=self.today,
        )

    def score(self, notice_id: str, prof: Profile | None) -> ScoreResult:
        t = self.tender(notice_id)
        m = self.match_for(notice_id, prof) if prof is not None else None
        intel = self.intel(notice_id, prof.company_key if prof else None)
        inputs = TenderInputs(
            notice_id=notice_id,
            deadline_on=t["deadline_on"],
            estimated_value_eur=t["estimated_value_eur"],
            dept=t["dept"],
            fit_percentile=m.fit_percentile if m else None,
        )
        return scorecard.score(inputs, intel, self.today)

    def brief(
        self, notice_id: str, prof: Profile, *, persist: bool = True, model: str | None = None
    ) -> tuple[writer.Brief, brief_facts.BriefFacts]:
        t = self.tender(notice_id)
        m = self.match_for(notice_id, prof)
        intel = self.intel(notice_id, prof.company_key)
        sc = self.score(notice_id, prof)
        bf = brief_facts.build(
            brief_facts.TenderInfo(
                notice_id=notice_id,
                objet=t["objet"],
                buyer_name=t["buyer_name"],
                deadline_on=t["deadline_on"],
                estimated_value_eur=t["estimated_value_eur"],
                cpv=t["cpv"],
            ),
            sc,
            match=m,
            intel=intel,
            today=self.today,
            company_key=prof.company_key,
        )
        b = writer.write(bf, model=model)
        if persist:
            writer.store(self.conn, b, bf)
        return b, bf
