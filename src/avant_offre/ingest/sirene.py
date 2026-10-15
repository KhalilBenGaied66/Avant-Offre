"""SIRENE company data: lookup API (sample mode) or bulk stock (full mode).

DECP already carries size category, NAF and department for SIRET winners (DATA_QUALITY F-001).
SIRENE is queried only for what DECP lacks: the legal category (to detect sole traders,
SPEC §4.6) and the creation date.

The lookup API (recherche-entreprises.api.gouv.fr) is rate-limited: requests are spaced to stay
below the configured rate and every response is cached in ``data/cache/sirene_api.jsonl`` so a
re-run does not query again. Response field names are unverified until the host is reachable:
the first response is checked and a missing field stops the run with the observed keys.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import duckdb
import httpx
from pydantic import BaseModel

from avant_offre.ingest.manifest import (
    Manifest,
    ManifestEntry,
    download,
    http_client,
    with_retries,
)
from avant_offre.runinfo import utc_now
from avant_offre.settings import get_settings

log = logging.getLogger(__name__)

# API field -> our field. Expected names (verify on first response).
API_FIELDS = {
    "siren": "siren",
    "nature_juridique": "legal_category",
    "date_creation": "created_on",
    "nom_complet": "name",
    "categorie_entreprise": "size_category",
}
# Stock file (StockUniteLegale) column -> our field.
STOCK_FIELDS = {
    "siren": "siren",
    "categorieJuridiqueUniteLegale": "legal_category",
    "dateCreationUniteLegale": "created_on",
    "categorieEntreprise": "size_category",
}


class SireneRecord(BaseModel):
    siren: str
    legal_category: str | None = None
    created_on: date | None = None
    size_category: str | None = None
    found: bool = True
    source: str = "api"


class SireneFieldError(RuntimeError):
    pass


def _cache_path() -> Path:
    return get_settings().cache_dir / "sirene_api.jsonl"


def load_cache() -> dict[str, SireneRecord]:
    path = _cache_path()
    if not path.exists():
        return {}
    out: dict[str, SireneRecord] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = SireneRecord.model_validate_json(line)
            out[rec.siren] = rec
    return out


def parse_api_result(siren: str, payload: dict[str, object], *, check_fields: bool) -> SireneRecord:
    results = payload.get("results")
    if not isinstance(results, list):
        raise SireneFieldError(f"unexpected SIRENE API payload keys: {sorted(payload)}")
    match = next((r for r in results if isinstance(r, dict) and r.get("siren") == siren), None)
    if match is None:
        return SireneRecord(siren=siren, found=False)
    if check_fields:
        missing = [k for k in API_FIELDS if k not in match]
        if missing:
            raise SireneFieldError(
                f"SIRENE API result lacks {missing}; observed keys: {sorted(match)}"
            )
    created = match.get("date_creation")
    return SireneRecord(
        siren=siren,
        legal_category=str(match["nature_juridique"]) if match.get("nature_juridique") else None,
        created_on=date.fromisoformat(str(created)[:10]) if created else None,
        size_category=str(match["categorie_entreprise"])
        if match.get("categorie_entreprise")
        else None,
    )


def lookup_api(
    sirens: Iterable[str], client: httpx.Client | None = None, *, sleep: bool = True
) -> dict[str, SireneRecord]:
    """Look up each SIREN once (cached). Returns every known record, cached or fresh."""
    s = get_settings()
    cache = load_cache()
    todo = sorted(set(sirens) - set(cache))[: s.sources.sirene.api_max_lookups]
    if not todo:
        return cache
    log.info("SIRENE API: %d lookups (%d cached)", len(todo), len(cache))
    interval = 1.0 / s.sources.sirene.api_max_requests_per_s
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    def _get(c: httpx.Client, siren: str) -> dict[str, object]:
        r = c.get(s.sources.sirene.api_search_url, params={"q": siren, "per_page": 5})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise SireneFieldError("SIRENE API returned a non-object payload")
        return data

    get = with_retries(_get)

    def _run(c: httpx.Client) -> None:
        with path.open("a", encoding="utf-8") as fh:
            for i, siren in enumerate(todo):
                started = time.monotonic()
                rec = parse_api_result(siren, get(c, siren), check_fields=(i == 0))
                cache[siren] = rec
                fh.write(rec.model_dump_json() + "\n")
                if sleep:
                    time.sleep(max(0.0, interval - (time.monotonic() - started)))

    if client is not None:
        _run(client)
    else:
        with http_client() as c:
            _run(c)
    m = Manifest.load()
    m.record(
        ManifestEntry(
            name="sirene_api",
            source_url=s.sources.sirene.api_search_url,
            path=str(path),
            downloaded_at=utc_now(),
            licence=s.sources.sirene.licence,
            extra={"records": len(cache)},
        )
    )
    return cache


def lookup_stock(sirens: Iterable[str], stock_path: Path) -> dict[str, SireneRecord]:
    """Full mode: read the StockUniteLegale Parquet, filtered to the given SIRENs."""
    con = duckdb.connect()
    cols = {
        r[0] for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{stock_path}')").fetchall()
    }
    missing = [c for c in STOCK_FIELDS if c not in cols]
    if missing:
        raise SireneFieldError(f"SIRENE stock lacks {missing}; observed: {sorted(cols)}")
    con.execute("CREATE TEMP TABLE wanted (siren VARCHAR)")
    con.executemany("INSERT INTO wanted VALUES (?)", [(x,) for x in set(sirens)])
    rows = con.execute(
        f"""
        SELECT s.siren, CAST(s.categorieJuridiqueUniteLegale AS VARCHAR),
               TRY_CAST(s.dateCreationUniteLegale AS DATE), s.categorieEntreprise
        FROM read_parquet('{stock_path}') s JOIN wanted USING (siren)
        """
    ).fetchall()
    con.close()
    return {
        r[0]: SireneRecord(
            siren=r[0], legal_category=r[1], created_on=r[2], size_category=r[3], source="stock"
        )
        for r in rows
    }


def fetch_records(sirens: list[str]) -> dict[str, SireneRecord]:
    s = get_settings()
    if s.mode == "full":
        url = s.sources.sirene.stock_unite_legale_url
        if not url:
            raise RuntimeError(
                "Full mode needs sources.sirene.stock_unite_legale_url: pick the current "
                "StockUniteLegale Parquet resource on the SIRENE dataset page and set it."
            )
        dest = s.raw_dir / "sirene" / "StockUniteLegale.parquet"
        download("sirene_stock", url, dest, licence=s.sources.sirene.licence)
        return lookup_stock(sirens, dest)
    return lookup_api(sirens)


def write_records(conn: duckdb.DuckDBPyConnection, records: dict[str, SireneRecord]) -> None:
    conn.execute(
        """
        CREATE OR REPLACE TABLE sirene_records (
            siren VARCHAR PRIMARY KEY, legal_category VARCHAR, created_on DATE,
            size_category VARCHAR, found BOOLEAN, source VARCHAR)
        """
    )
    conn.executemany(
        "INSERT INTO sirene_records VALUES (?, ?, ?, ?, ?, ?)",
        [
            (r.siren, r.legal_category, r.created_on, r.size_category, r.found, r.source)
            for r in records.values()
        ],
    )
