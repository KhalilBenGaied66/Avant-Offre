"""HTTP API, weekly digest + Adaptive Card, MCP server (fictitious fixture store)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import anyio
import duckdb
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from avant_offre.agent.mcp_server import create_server
from avant_offre.api import app as api_module
from avant_offre.digest import adaptive_card, digest
from avant_offre.service import Engine
from avant_offre.settings import get_settings, reset_caches
from avant_offre.store import db
from tests.helpers import add_tenders, build_store

KEY = "test-key"


@pytest.fixture
def store_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("AVANT_OFFRE_API_KEY", KEY)
    monkeypatch.setenv("AVANT_OFFRE_INTEL__MIN_PRICE_N", "3")
    reset_caches()
    conn = db.connect()
    build_store(conn, tmp_path)
    add_tenders(conn, tmp_path, date.today())
    conn.close()
    api_module._State.conn = None
    api_module._State.app_conn = None
    api_module._State.engine_cache = {}
    yield get_settings().db_path
    for c in (api_module._State.conn, api_module._State.app_conn):
        if c is not None:
            c.close()
    api_module._State.conn = api_module._State.app_conn = None


def _alpha(path: Path) -> str:
    with duckdb.connect(str(path), read_only=True) as c:
        row = c.execute(
            "SELECT company_key FROM company_names WHERE display_name = 'ALPHA INFORMATIQUE'"
        ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.fixture
def client(store_file: Path) -> TestClient:
    api_module.settings = get_settings()
    return TestClient(api_module.app)


H = {"X-API-Key": KEY}


def test_health_is_open_and_the_rest_needs_the_key(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/tenders/T1").status_code == 401
    assert client.get("/tenders/T1", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/tenders/T1", headers=H).status_code == 200


def test_shortlist_detail_intel_score_brief(client: TestClient, store_file: Path) -> None:
    siren = _alpha(store_file)
    sl = client.get("/tenders", params={"siret": siren}, headers=H).json()
    assert {i["notice_id"] for i in sl["eligible"]} == {"T1", "T2", "T4"}
    assert sl["excluded"][0]["labels"] == ["Date limite trop proche"]
    intel = client.get("/tenders/T2/intel", headers=H).json()
    assert intel["price_range"]["n"] == len(intel["price_range"]["sources"])
    assert all("CAMILLE" not in c["name"] for c in intel["competitors"])
    score = client.get("/tenders/T1/score", params={"siret": siren}, headers=H).json()
    assert score["band"] in {"GO", "REVIEW", "NO-GO"}
    brief = client.post("/tenders/T1/brief", params={"siret": siren}, headers=H).json()
    assert brief["fallback"] is True and "## Recommandation" in brief["text"]
    first_source = next(f for f in brief["facts"] if f["sources"] and f["key"] != "objet")
    awards = client.get(
        "/awards", params={"uids": ",".join(first_source["sources"][:3])}, headers=H
    ).json()
    assert isinstance(awards, list)


def test_errors_are_explicit(client: TestClient) -> None:
    assert client.get("/tenders/NOPE", headers=H).status_code == 404
    assert client.get("/tenders", params={"siret": "999999999"}, headers=H).status_code == 404
    assert client.get("/tenders", params={"week": "42"}, headers=H).status_code == 422


def test_feedback_validation_and_storage(client: TestClient, store_file: Path) -> None:
    ok = client.post(
        "/feedback",
        headers=H,
        json={"notice_id": "T1", "kind": "decision", "value": "go", "reason": "référence forte"},
    )
    assert ok.status_code == 201
    bad = client.post(
        "/feedback", headers=H, json={"notice_id": "T1", "kind": "decision", "value": "relevant"}
    )
    assert bad.status_code == 422
    assert (
        client.post(
            "/feedback", headers=H, json={"notice_id": "NOPE", "kind": "decision", "value": "go"}
        ).status_code
        == 404
    )


def test_digest_payload_and_card(client: TestClient, store_file: Path) -> None:
    siren = _alpha(store_file)
    out = client.get(f"/digest/{siren}/weekly", headers=H).json()
    card = out["adaptive_card"]
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    assert card["$schema"].startswith("http://adaptivecards.io")
    adaptive_card.AdaptiveCard.model_validate(card)  # round-trips through the strict model
    assert len(json.dumps(out["teams_message"]).encode()) < adaptive_card.TEAMS_MAX_BYTES
    assert out["digest"]["counts"]["eligible"] == 3
    html = client.get(f"/digest/{siren}/weekly.html", headers=H).text
    assert "<table" in html and "Avant-Offre" in html


def test_card_model_rejects_invalid_properties() -> None:
    with pytest.raises(ValueError):
        adaptive_card.TextBlock(text="x", color="Purple")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        adaptive_card.TextBlock.model_validate({"type": "TextBlock", "text": "x", "colour": "Good"})


def test_html_digest_escapes_data(store_file: Path) -> None:
    with duckdb.connect(str(store_file), read_only=True) as c:
        engine = Engine(c, date.today())
        d = digest.build(engine, engine.shortlist(engine.profile(siret=_alpha(store_file))), "x")
    d.items[0].objet = "<script>alert(1)</script>"
    assert "<script>" not in digest.render_html(d)


def test_mcp_session_calls_every_tool(store_file: Path) -> None:
    siren = _alpha(store_file)

    def connect() -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(store_file), read_only=True)

    server = create_server(connect=connect)
    calls = {
        "search_tenders": {"siret": siren},
        "get_tender": {"notice_id": "T1"},
        "match_explanations": {"notice_id": "T1", "siret": siren},
        "market_stats": {"notice_id": "T2"},
        "competitors": {"notice_id": "T2"},
        "price_range": {"notice_id": "T2"},
        "score_tender": {"notice_id": "T1", "siret": siren},
        "bid_brief": {"notice_id": "T1", "siret": siren},
    }

    async def session() -> dict[str, object]:
        out: dict[str, object] = {}
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert names == set(calls)
            assert all("memory" in (t.description or "") for t in tools.tools)
            for name, args in calls.items():
                res = await client.call_tool(name, args)
                text = res.content[0].text  # type: ignore[union-attr]
                out[name] = json.loads(text)
        return out

    results = anyio.run(session)
    assert all("error" not in r for r in results.values() if isinstance(r, dict))
    assert results["bid_brief"]["fallback"] is True  # type: ignore[index]
    payload = json.dumps(results)
    assert "CAMILLE" not in payload  # personal data rule holds through the agent tools
