"""MCP server (stdio and streamable HTTP) wrapping steps 5–8 as read-only tools.

The agent answers ad-hoc questions ("who usually wins with this buyer?") by calling these tools
from Claude or Microsoft Copilot Studio; it never answers from memory (DECISIONS step 11). Every
tool returns structured JSON with the award ``uid``s behind each value, and winner names pass
through the personal data rule. Tools only read: the analytic store is opened read-only and no
brief is stored.

Run: ``avant-offre mcp --transport stdio`` (Claude Desktop / Claude Code) or
``avant-offre mcp --transport http`` (Copilot Studio; API key header required).
"""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import duckdb
from mcp.server.mcpserver import MCPServer

from avant_offre.service import Engine, NotFoundError
from avant_offre.store import db

INSTRUCTIONS = (
    "Avant-Offre: French public procurement data (DECP awards, BOAMP open tenders) for a bid "
    "office. Answer ONLY from tool results, never from memory or general knowledge. Quote the "
    "numbers exactly as returned with their n, and cite the award uids or notice ids returned "
    "in 'sources'. If a tool returns no data, say so. These tools are read-only: never claim "
    "that a bid was submitted or a message sent."
)
GROUNDING = " Answer only from this result; do not add facts from memory."
DESCRIPTIONS = {
    "search_tenders": "Ranked open tenders of the week for a company (SIRET/SIREN) or a "
    "free-text profile, with GO/REVIEW/NO-GO bands, and the excluded tenders with their "
    "reasons. week: ISO week such as 2026-W42 (default: the last 7 days).",
    "get_tender": "One open tender: buyer, deadline, CPV, estimated value, and extracted facts "
    "with their source (eforms, or llm with a verbatim quote).",
    "match_explanations": "Why a tender matches a company: fit percentile and the 3 past "
    "contracts of the company that explain it best (award uids, titles, dates).",
    "market_stats": "How open the market is for a tender: newcomer share, SME win share, median "
    "bids received, buyer concentration, each with n and source award uids.",
    "competitors": "Likely competitors for a tender from public award history (similar "
    "contracts, recent wins weighted more), flagged incumbent or new to this buyer. Companies "
    "without public history cannot appear: use market_stats for the newcomer share.",
    "price_range": "P10/P25/median/P75/P90 of comparable award amounts (framework agreements and "
    "aberrant amounts excluded), with n and source uids.",
    "score_tender": "Go/no-go scorecard: per-criterion values and weights, criteria not "
    "assessed, hard stops and band. The weights belong to the bid team.",
    "bid_brief": "One-page French brief for the go/no-go committee, with [F#] citations to the "
    "facts returned alongside it. Its numbers are verified against those facts.",
}
DESCRIPTIONS = {k: v + GROUNDING for k, v in DESCRIPTIONS.items()}


def _dump(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, ensure_ascii=False, default=str)


def create_server(
    connect: Callable[[], duckdb.DuckDBPyConnection] | None = None,
    today: Callable[[], date] = date.today,
) -> MCPServer:
    """Build the server; ``connect`` returns the analytic store connection (tests inject one)."""
    server = MCPServer("avant-offre", instructions=INSTRUCTIONS)
    lock = threading.Lock()
    state: dict[str, Any] = {}

    @contextmanager
    def engine() -> Iterator[Engine]:
        with lock:
            if "conn" not in state:
                state["conn"] = connect() if connect else db.connect(read_only=True)
            eng = Engine(state["conn"], today())
            eng._index, eng._competitors = state.get("index"), state.get("competitors")
            try:
                yield eng
            finally:
                state["index"], state["competitors"] = eng._index, eng._competitors

    def run(fn: Callable[[Engine], Any]) -> str:
        try:
            with engine() as eng:
                return _dump(fn(eng))
        except (NotFoundError, ValueError) as exc:
            return _dump({"error": str(exc)})

    @server.tool(description=DESCRIPTIONS["search_tenders"])
    def search_tenders(
        siret: str | None = None, free_text: str | None = None, week: str | None = None
    ) -> str:
        return run(lambda e: e.shortlist(e.profile(siret=siret, free_text=free_text), week))

    @server.tool(description=DESCRIPTIONS["get_tender"])
    def get_tender(notice_id: str) -> str:
        return run(lambda e: e.tender(notice_id))

    @server.tool(description=DESCRIPTIONS["match_explanations"])
    def match_explanations(notice_id: str, siret: str) -> str:
        def fn(e: Engine) -> Any:
            m = e.match_for(notice_id, e.profile(siret=siret))
            if m is None:
                return {"error": "tender not eligible or not published this week"}
            return dataclasses.asdict(m)

        return run(fn)

    @server.tool(description=DESCRIPTIONS["market_stats"])
    def market_stats(notice_id: str) -> str:
        def fn(e: Engine) -> Any:
            i = e.intel(notice_id)
            return {
                "n_comparables": i.n_comparables,
                "newcomer_share_pct": i.newcomer_share,
                "sme_share_pct": i.sme_share,
                "bids_received_median": i.bids_received,
                "buyer_top_winner_share_pct": i.buyer_top_winner_share,
            }

        return run(fn)

    @server.tool(description=DESCRIPTIONS["competitors"])
    def competitors(notice_id: str, siret: str | None = None) -> str:
        def fn(e: Engine) -> Any:
            key = e.profile(siret=siret).company_key if siret else None
            return {
                "competitors": [
                    c.model_dump(mode="json") for c in e.intel(notice_id, key).competitors
                ]
            }

        return run(fn)

    @server.tool(description=DESCRIPTIONS["price_range"])
    def price_range(notice_id: str) -> str:
        return run(lambda e: e.intel(notice_id).price_range)

    @server.tool(description=DESCRIPTIONS["score_tender"])
    def score_tender(notice_id: str, siret: str | None = None) -> str:
        return run(lambda e: e.score(notice_id, e.profile(siret=siret) if siret else None))

    @server.tool(description=DESCRIPTIONS["bid_brief"])
    def bid_brief(notice_id: str, siret: str) -> str:
        def fn(e: Engine) -> Any:
            b, facts = e.brief(notice_id, e.profile(siret=siret), persist=False)
            return {
                "text": b.text,
                "fallback": b.fallback,
                "facts": [f.model_dump() for f in facts.facts],
            }

        return run(fn)

    return server


def main(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8001) -> None:
    server = create_server()
    if transport == "stdio":
        server.run("stdio")
        return
    import uvicorn  # noqa: PLC0415
    from starlette.middleware.base import BaseHTTPMiddleware  # noqa: PLC0415
    from starlette.responses import JSONResponse  # noqa: PLC0415

    from avant_offre.settings import get_settings  # noqa: PLC0415

    s = get_settings()
    http_app = server.streamable_http_app(host=host)

    async def check_key(request: Any, call_next: Any) -> Any:
        import secrets  # noqa: PLC0415

        given = request.headers.get(s.api.key_header)
        if not s.api_key or not given or not secrets.compare_digest(given, s.api_key):
            return JSONResponse({"error": "missing or invalid API key"}, status_code=401)
        return await call_next(request)

    http_app.add_middleware(BaseHTTPMiddleware, dispatch=check_key)
    uvicorn.run(http_app, host=host, port=port)


if __name__ == "__main__":
    main()
