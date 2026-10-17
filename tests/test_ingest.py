"""Downloads with provenance, SIRENE lookups, BOAMP field checks (offline, mocked HTTP)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from avant_offre.ingest import boamp, decp, manifest, sirene
from avant_offre.settings import get_settings


def test_download_records_manifest_and_skips_unchanged(tmp_path: Path) -> None:
    body = b"PAR1" + b"x" * 5000
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dest = tmp_path / "f.parquet"
    status, entry = manifest.download("decp", "https://example.test/f", dest, client=client)
    assert status == "downloaded"
    assert dest.read_bytes() == body
    assert entry.sha256 == manifest.sha256_file(dest)
    assert manifest.Manifest.load().entries["decp"].source_url == "https://example.test/f"
    status2, _ = manifest.download("decp", "https://example.test/f", dest, client=client)
    assert status2 == "unchanged"
    assert calls[-1]["if-none-match"] == '"v1"'


def test_download_resumes_partial_file(tmp_path: Path) -> None:
    body = b"0123456789" * 100
    dest = tmp_path / "f.bin"
    dest.with_name("f.bin.part").write_bytes(body[:300])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=300-"
        return httpx.Response(206, content=body[300:])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    manifest.download("x", "https://example.test/x", dest, client=client)
    assert dest.read_bytes() == body


def test_proxy_refusal_is_not_retried() -> None:
    assert not manifest._retryable(httpx.ProxyError("403"))
    assert manifest._retryable(httpx.ConnectError("reset"))


def test_sirene_api_parsing_and_cache() -> None:
    siren = "123456782"
    payload = {
        "results": [
            {
                "siren": siren,
                "nature_juridique": "1000",
                "date_creation": "2015-06-01",
                "nom_complet": "X",
                "categorie_entreprise": "PME",
            }
        ]
    }
    n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    recs = sirene.lookup_api([siren], client=client, sleep=False)
    assert recs[siren].legal_category == "1000"
    assert recs[siren].created_on is not None
    sirene.lookup_api([siren], client=client, sleep=False)
    assert n == 1  # second call served from the cache


def test_sirene_api_field_change_fails_loudly() -> None:
    with pytest.raises(sirene.SireneFieldError, match="observed keys"):
        sirene.parse_api_result(
            "123456782", {"results": [{"siren": "123456782", "other": 1}]}, check_fields=True
        )


def test_sirene_not_found() -> None:
    rec = sirene.parse_api_result("123456782", {"results": []}, check_fields=True)
    assert rec.found is False


def test_boamp_missing_field_reports_observed(tmp_path: Path) -> None:
    p = tmp_path / "b.jsonl"
    p.write_text(json.dumps({"idweb": "1", "objet": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(boamp.BoampFieldError, match="Observed fields"):
        boamp.check_fields(boamp.read_jsonl(p))


def test_boamp_export_query_uses_configured_fields() -> None:
    url, params = boamp.export_url(date(2026, 10, 15))
    f = get_settings().sources.boamp.fields
    assert url.endswith("/exports/jsonl")
    assert f["published_on"] in params["where"] and "2026-10-15" in params["where"]


def test_no_download_reuses_only_a_verified_snapshot() -> None:
    with pytest.raises(decp.SnapshotMissingError):
        decp.fetch(use_local=True)  # nothing recorded yet
    path = decp.raw_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PAR1 snapshot")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"PAR1 snapshot"))
    )
    manifest.download("decp", "https://example.test/decp", path, client=client)
    assert decp.fetch(use_local=True).sha256 == manifest.sha256_file(path)
    path.write_bytes(b"PAR1 changed on disk")
    with pytest.raises(decp.SnapshotMissingError):
        decp.fetch(use_local=True)


def test_boamp_fetch_retries_a_truncated_export() -> None:
    full = b"".join(
        json.dumps({"idweb": f"26-{i}", "objet": "x"}).encode() + b"\n" for i in range(3)
    )
    bodies = [full[:-15], full]  # first response is cut mid-record, without an HTTP error

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bodies.pop(0))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = boamp.fetch(date(2026, 10, 16), client=client)
    assert path.read_bytes() == full
    assert bodies == []
