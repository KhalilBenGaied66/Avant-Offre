"""DECP consolidated (awarded contracts) downloader and schema check.

The consolidated tabular file is published by data.gouv.fr (SPEC §4.1). Its column names are
taken from the publisher's schema (docs/DATA_QUALITY.md F-001) and checked against the real file
before any transform runs: a missing column stops the pipeline with the observed schema.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from avant_offre.ingest.manifest import Manifest, ManifestEntry, download, sha256_file
from avant_offre.settings import get_settings

log = logging.getLogger(__name__)

# Columns the transforms read. Required ones must exist; optional ones are used when present.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "uid",
    "id",
    "acheteur_id",
    "acheteur_nom",
    "titulaire_id",
    "titulaire_typeIdentifiant",
    "titulaire_nom",
    "objet",
    "montant",
    "codeCPV",
    "procedure",
    "nature",
    "techniques",
    "dureeMois",
    "dateNotification",
    "lieuExecution_code",
    "lieuExecution_typeCode",
    "offresRecues",
    "modification_id",
)
OPTIONAL_COLUMNS: tuple[str, ...] = (
    "formePrix",
    "idAccordCadre",
    "donneesActuelles",
    "datePublicationDonnees",
    "acheteur_departement_code",
    "titulaire_categorie",
    "titulaire_activite_code",
    "titulaire_departement_code",
    "montant_anomalie",
    "sourceDataset",
)


class SchemaMismatchError(RuntimeError):
    pass


def raw_path() -> Path:
    return get_settings().raw_dir / "decp" / "decp.parquet"


class SnapshotMissingError(RuntimeError):
    pass


def local_snapshot() -> ManifestEntry:
    """The snapshot already on disk, checked against its manifest entry (``--no-download``)."""
    entry = Manifest.load().entries.get("decp")
    path = raw_path()
    if entry is None or not path.exists():
        raise SnapshotMissingError(f"no DECP snapshot recorded at {path}: run online once.")
    if sha256_file(path) != entry.sha256:
        raise SnapshotMissingError(f"{path} does not match its manifest checksum.")
    log.info("DECP reused: snapshot of %s (%s)", entry.downloaded_at, entry.final_url)
    return entry


def fetch(*, use_local: bool = False) -> ManifestEntry:
    if use_local:
        return local_snapshot()
    s = get_settings()
    status, entry = download(
        "decp", s.sources.decp.parquet_url, raw_path(), licence=s.sources.decp.licence
    )
    log.info("DECP %s (%s bytes, %s)", status, entry.bytes, entry.final_url)
    return entry


def observed_schema(path: Path) -> list[tuple[str, str]]:
    rel = duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')")
    return [(str(r[0]), str(r[1])) for r in rel.fetchall()]


def check_schema(path: Path) -> list[tuple[str, str]]:
    """Return the observed (name, type) list; raise if a required column is missing."""
    schema = observed_schema(path)
    names = {n for n, _ in schema}
    missing = [c for c in REQUIRED_COLUMNS if c not in names]
    if missing:
        listing = "\n".join(f"  {n}: {t}" for n, t in schema)
        raise SchemaMismatchError(
            f"DECP file {path} lacks required columns {missing}.\nObserved schema:\n{listing}"
        )
    absent_optional = [c for c in OPTIONAL_COLUMNS if c not in names]
    if absent_optional:
        log.warning("DECP optional columns absent: %s", absent_optional)
    return schema
