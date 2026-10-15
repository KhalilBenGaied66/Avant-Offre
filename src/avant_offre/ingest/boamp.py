"""BOAMP open notices downloader (Opendatasoft explore API v2.1).

Live mode only: the backtest does not depend on BOAMP (SPEC §4.2). A pull exports the notices
published in the last ``lookback_days`` whose answer deadline is not past, as JSONL, then
``build_tenders`` maps the configured fields into the ``tenders`` table and reads the eForms
content with ``extract.eforms``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx

from avant_offre.extract import eforms
from avant_offre.ingest.manifest import Manifest, ManifestEntry, http_client, sha256_file
from avant_offre.runinfo import utc_now
from avant_offre.settings import get_settings
from avant_offre.store.db import set_meta
from avant_offre.transform.normalize import register_macros

log = logging.getLogger(__name__)


class BoampFieldError(RuntimeError):
    pass


def export_url(today: date) -> tuple[str, dict[str, str]]:
    s = get_settings().sources.boamp
    f = s.fields
    since = today - timedelta(days=s.lookback_days)
    where = (
        f"{f['published_on']} >= date'{since.isoformat()}' "
        f"AND {f['deadline_on']} >= date'{today.isoformat()}'"
    )
    return f"{s.api_base}/exports/jsonl", {"where": where}


def fetch(today: date | None = None, client: httpx.Client | None = None) -> Path:
    s = get_settings()
    today = today or date.today()
    url, params = export_url(today)
    dest = s.raw_dir / "boamp" / f"boamp_open_{today.isoformat()}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _run(c: httpx.Client) -> str:
        with c.stream("GET", url, params=params) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
            return str(resp.url)

    if client is not None:
        final = _run(client)
    else:
        with http_client() as c:
            final = _run(c)
    Manifest.load().record(
        ManifestEntry(
            name="boamp_open",
            source_url=url,
            final_url=final,
            path=str(dest),
            downloaded_at=utc_now(),
            sha256=sha256_file(dest),
            bytes=dest.stat().st_size,
            licence=s.sources.boamp.licence,
            extra={"where": params["where"]},
        )
    )
    return dest


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
    return out


def check_fields(records: list[dict[str, Any]]) -> None:
    s = get_settings().sources.boamp
    if not records:
        return
    observed = set().union(*(r.keys() for r in records[:50]))
    missing = [
        f"{logical} -> {s.fields[logical]}"
        for logical in s.required_fields
        if s.fields[logical] not in observed
    ]
    if missing:
        raise BoampFieldError(
            f"BOAMP records lack configured fields {missing}. Observed fields: {sorted(observed)}. "
            "Fix sources.boamp.fields in config/settings.yaml."
        )


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _as_text(value: Any) -> str | None:
    value = _first(value)
    return None if value is None else str(value)


def build_tenders(conn: duckdb.DuckDBPyConnection, paths: Iterable[Path]) -> dict[str, int]:
    """Create ``tenders`` and ``tender_facts`` (source = eforms) from BOAMP JSONL pulls."""
    f = get_settings().sources.boamp.fields
    records: dict[str, dict[str, Any]] = {}
    seen = 0
    for path in paths:
        recs = read_jsonl(path)
        check_fields(recs)
        for r in recs:
            seen += 1
            nid = _as_text(r.get(f["notice_id"]))
            if nid:
                records[nid] = r  # identical ids collapse here (same_notice_id)
    set_meta(conn, "boamp_records_seen", seen)
    set_meta(conn, "boamp_duplicate_ids", seen - len(records))

    staging = []
    facts_rows = []
    for nid, r in records.items():
        donnees = r.get(f["donnees"])
        parsed = eforms.parse(donnees)
        for fact, value in parsed.values.items():
            facts_rows.append(
                (nid, fact, json.dumps(value, ensure_ascii=False), "eforms", None, 1.0)
            )
        staging.append(
            (
                nid,
                "boamp",
                _as_text(r.get(f["buyer_name"])),
                _as_text(r.get(f["objet"])),
                _as_text(r.get(f["published_on"])),
                parsed.get("deadline") or _as_text(r.get(f["deadline_on"])),
                _as_text(r.get(f["dept"])),
                parsed.get("cpv_main"),
                _as_text(r.get(f.get("procedure", ""))) or parsed.get("procedure_code"),
                parsed.get("estimated_value_eur"),
                json.dumps(parsed.get("lots") or [], ensure_ascii=False),
                json.dumps(parsed.get("award_criteria") or [], ensure_ascii=False),
                parsed.get("contract_folder_id"),
                _as_text(r.get(f.get("url", ""))),
                json.dumps(r, ensure_ascii=False, default=str),
            )
        )
    register_macros(conn)
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE tenders_staging (
            notice_id VARCHAR, source VARCHAR, buyer_name VARCHAR, objet VARCHAR,
            published_raw VARCHAR, deadline_raw VARCHAR, dept_raw VARCHAR, cpv VARCHAR,
            procedure VARCHAR, estimated_value_eur DOUBLE, lots_json VARCHAR,
            criteria_json VARCHAR, folder_id VARCHAR, url VARCHAR, raw_json VARCHAR)
        """
    )
    if staging:
        conn.executemany(
            "INSERT INTO tenders_staging VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            staging,
        )
    conn.execute(
        """
        CREATE OR REPLACE TABLE tenders AS
        SELECT notice_id, source, buyer_name, objet,
               TRY_CAST(substr(published_raw, 1, 10) AS DATE) AS published_on,
               TRY_CAST(substr(deadline_raw, 1, 10) AS DATE) AS deadline_on,
               ao_dept_from_dept(dept_raw) AS dept,
               cpv, substr(cpv, 1, 2) AS cpv_division, procedure, estimated_value_eur,
               lots_json, criteria_json, folder_id, url, raw_json,
               CAST(NULL AS VARCHAR) AS duplicate_of, CAST(NULL AS VARCHAR) AS dedup_reason
        FROM tenders_staging
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE TABLE tender_facts (
            notice_id VARCHAR, fact VARCHAR, value JSON, source VARCHAR,
            source_quote VARCHAR, confidence DOUBLE)
        """
    )
    if facts_rows:
        conn.executemany("INSERT INTO tender_facts VALUES (?, ?, ?, ?, ?, ?)", facts_rows)
    return {"tenders": len(staging), "tender_facts": len(facts_rows)}


def latest_pulls() -> list[Path]:
    d = get_settings().raw_dir / "boamp"
    return sorted(d.glob("boamp_open_*.jsonl"))[-1:] if d.exists() else []
