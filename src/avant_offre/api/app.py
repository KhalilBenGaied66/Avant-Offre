"""FastAPI application (single API key).

- The analytic store is opened read-only; feedback and stored briefs go to ``data/app.duckdb``.
- Requests are served one at a time (a process-wide lock): this is an internal tool for one bid
  office, and DuckDB connections are not shared across threads. Scale-out notes: docs/HANDOFF.md.
- Every winner name in a response comes from ``company_names`` (personal data rule).
- Nothing here writes to an external system.
"""

from __future__ import annotations

import secrets
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any, ClassVar, Literal

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, model_validator

from avant_offre import __version__
from avant_offre.digest import adaptive_card, digest
from avant_offre.intel.market import MarketIntel
from avant_offre.score.scorecard import ScoreResult
from avant_offre.service import Engine, NotFoundError, Shortlist
from avant_offre.settings import get_settings
from avant_offre.store import db

settings = get_settings()
api_key_header = APIKeyHeader(name=settings.api.key_header, auto_error=False)

app = FastAPI(
    title="Avant-Offre API",
    version=__version__,
    description="Go/no-go copilot for French public tenders. Read-only towards the outside "
    "world; every number is computed in SQL/Python and carries its sources.",
)
if settings.api.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=[settings.api.key_header, "Content-Type"],
    )


class _State:
    lock = threading.Lock()
    conn: duckdb.DuckDBPyConnection | None = None
    app_conn: duckdb.DuckDBPyConnection | None = None
    engine_cache: ClassVar[dict[str, Any]] = {}


def require_key(key: Annotated[str | None, Security(api_key_header)]) -> None:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(503, "AVANT_OFFRE_API_KEY is not configured on the server")
    if key is None or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "missing or invalid API key")


Protected = Depends(require_key)


@contextmanager
def engine_scope() -> Iterator[Engine]:
    with _State.lock:
        if _State.conn is None:
            if not get_settings().db_path.exists():
                raise HTTPException(503, "no data store: run `make data-sample` first")
            _State.conn = db.connect(read_only=True)
        if _State.app_conn is None:
            _State.app_conn = db.app_connect()
        engine = Engine(_State.conn, date.today(), app_conn=_State.app_conn)
        # Reuse the search index and competitor model across requests of the same day.
        cache = _State.engine_cache
        if cache.get("day") == engine.today:
            engine._index = cache.get("index")
            engine._competitors = cache.get("competitors")
        try:
            yield engine
        except NotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            _State.engine_cache = {
                "day": engine.today,
                "index": engine._index,
                "competitors": engine._competitors,
            }


def _profile(engine: Engine, siret: str | None, free_text: str | None = None) -> Any:
    return engine.profile(siret=siret, free_text=free_text)


# ---- endpoints ---------------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "mode": s.mode,
        "store": s.db_path.exists(),
        "api_key_configured": bool(s.api_key),
    }


@app.get("/tenders", dependencies=[Protected])
def list_tenders(
    siret: Annotated[str | None, Query(description="SIRET or SIREN of the company")] = None,
    free_text: Annotated[str | None, Query(max_length=2000)] = None,
    week: Annotated[str | None, Query(pattern=r"^\d{4}-W\d{2}$")] = None,
) -> Shortlist:
    """Ranked shortlist of the week's tenders, with exclusion reasons."""
    with engine_scope() as engine:
        return engine.shortlist(_profile(engine, siret, free_text), week)


@app.get("/tenders/{notice_id}", dependencies=[Protected])
def get_tender(notice_id: str) -> dict[str, Any]:
    with engine_scope() as engine:
        return engine.tender(notice_id)


@app.get("/tenders/{notice_id}/intel", dependencies=[Protected])
def tender_intel(notice_id: str, siret: str | None = None) -> MarketIntel:
    with engine_scope() as engine:
        key = engine.profile(siret=siret).company_key if siret else None
        return engine.intel(notice_id, key)


@app.get("/tenders/{notice_id}/score", dependencies=[Protected])
def tender_score(notice_id: str, siret: str | None = None) -> ScoreResult:
    with engine_scope() as engine:
        return engine.score(notice_id, engine.profile(siret=siret) if siret else None)


class BriefOut(BaseModel):
    brief_id: str
    notice_id: str
    text: str
    model: str | None
    fallback: bool
    fallback_reason: str | None
    removed: list[dict[str, str]]
    cost_usd: float | None
    facts: list[dict[str, Any]]


@app.post("/tenders/{notice_id}/brief", dependencies=[Protected])
def tender_brief(notice_id: str, siret: str) -> BriefOut:
    with engine_scope() as engine:
        b, facts = engine.brief(notice_id, engine.profile(siret=siret))
    return BriefOut(
        brief_id=b.brief_id,
        notice_id=notice_id,
        text=b.text,
        model=b.model,
        fallback=b.fallback,
        fallback_reason=b.fallback_reason,
        removed=[
            {"section": r.section, "sentence": r.sentence, "reason": r.reason} for r in b.removed
        ],
        cost_usd=b.cost_usd,
        facts=[f.model_dump() for f in facts.facts],
    )


@app.get("/awards", dependencies=[Protected])
def awards(
    uids: Annotated[str, Query(description="Comma-separated award uids, max 200")],
) -> list[dict[str, Any]]:
    """Source awards behind a fact (winner names pass through the personal data rule)."""
    ids = [u for u in uids.split(",") if u][:200]
    with engine_scope() as engine:
        return db.fetch_dicts(
            engine.conn,
            """
            SELECT a.uid, a.notified_on, a.buyer_name, a.objet, a.cpv, a.exec_dept,
                   CASE WHEN a.is_framework THEN NULL ELSE a.amount_eur END AS amount_eur,
                   a.is_framework,
                   list(DISTINCT n.display_name) FILTER (WHERE n.display_name IS NOT NULL)
                       AS winners
            FROM awards a
            LEFT JOIN award_winners w USING (uid)
            LEFT JOIN company_names n ON n.company_key = w.company_key
            WHERE a.uid IN (SELECT unnest(?))
            GROUP BY ALL ORDER BY a.notified_on DESC
            """,
            [ids],
        )


@app.get("/digest/{siret}/weekly", dependencies=[Protected])
def weekly_digest(siret: str, week: str | None = None) -> dict[str, Any]:
    """Digest JSON + Teams Adaptive Card payload (delivery: Power Automate)."""
    with engine_scope() as engine:
        d = digest.build(engine, engine.shortlist(engine.profile(siret=siret), week), siret)
    card = adaptive_card.build(d)
    return {
        "digest": d.model_dump(mode="json"),
        "adaptive_card": card,
        "teams_message": adaptive_card.teams_message(card),
    }


@app.get("/digest/{siret}/weekly.html", dependencies=[Protected], response_class=HTMLResponse)
def weekly_digest_html(siret: str, week: str | None = None) -> str:
    with engine_scope() as engine:
        d = digest.build(engine, engine.shortlist(engine.profile(siret=siret), week), siret)
    return digest.render_html(d)


class FeedbackIn(BaseModel):
    notice_id: str = Field(max_length=100)
    siret: str | None = Field(None, max_length=20)
    kind: Literal["relevance", "decision"]
    value: Literal["relevant", "not_relevant", "go", "no_go"]
    reason: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _consistent(self) -> FeedbackIn:
        allowed = {"relevance": {"relevant", "not_relevant"}, "decision": {"go", "no_go"}}
        if self.value not in allowed[self.kind]:
            raise ValueError(f"{self.value!r} is not a valid {self.kind} value")
        return self


@app.post("/feedback", dependencies=[Protected], status_code=201)
def feedback(item: FeedbackIn) -> dict[str, str]:
    """Record the committee's decision or a relevance judgement. Nothing is automated after."""
    with engine_scope() as engine:
        engine.tender(item.notice_id)  # 404 on unknown notice
        key = engine.profile(siret=item.siret).company_key if item.siret else None
        fid = uuid.uuid4().hex[:16]
        assert engine.app_conn is not None
        engine.app_conn.execute(
            "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?)",
            [fid, datetime.now(UTC), item.notice_id, key, item.kind, item.value, item.reason],
        )
    return {"feedback_id": fid}
