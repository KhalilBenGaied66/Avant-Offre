"""eForms parsing and the tenders table (BOAMP fixture records, fictitious)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from avant_offre.extract import eforms
from avant_offre.ingest import boamp
from avant_offre.transform import dedup

# A JSON transcription of eForms UBL elements, in two styles (prefixed keys, "#text"/"@attr").
EFORMS_DOC = {
    "ContractNotice": {
        "cbc:ContractFolderID": "proc-0001",
        "cac:TenderingProcess": {
            "cbc:ProcedureCode": {"#text": "open", "@listName": "procurement-procedure-type"},
            "cac:TenderSubmissionDeadlinePeriod": {
                "cbc:EndDate": "2026-11-20+01:00",
                "cbc:EndTime": "12:00:00+01:00",
            },
        },
        "cac:ProcurementProject": {
            "cbc:Name": "Maintenance applicative",
            "cac:MainCommodityClassification": {
                "cbc:ItemClassificationCode": {"#text": "72267100", "@listName": "cpv"}
            },
            "cac:RequestedTenderTotal": {
                "cbc:EstimatedOverallContractAmount": {"#text": "450000", "@currencyID": "EUR"}
            },
            "cac:PlannedPeriod": {"cbc:DurationMeasure": {"#text": "3", "@unitCode": "YEAR"}},
        },
        "cac:ProcurementProjectLot": [
            {
                "cbc:ID": "LOT-0001",
                "cac:ProcurementProject": {
                    "cbc:Name": "Lot 1 TMA",
                    "cac:RequestedTenderTotal": {
                        "cbc:EstimatedOverallContractAmount": {
                            "#text": "300000",
                            "@currencyID": "EUR",
                        }
                    },
                },
                "cac:TenderingTerms": {
                    "cac:AwardingTerms": {
                        "cac:AwardingCriterion": {
                            "cac:SubordinateAwardingCriterion": [
                                {
                                    "cbc:AwardingCriterionTypeCode": "quality",
                                    "cbc:Description": "Valeur technique",
                                    "efac:AwardCriterionParameter": {
                                        "efbc:ParameterCode": "per-exa",
                                        "efbc:ParameterNumeric": "60",
                                    },
                                },
                                {
                                    "cbc:AwardingCriterionTypeCode": "price",
                                    "cbc:Description": "Prix",
                                    "efac:AwardCriterionParameter": {
                                        "efbc:ParameterCode": "per-exa",
                                        "efbc:ParameterNumeric": "40",
                                    },
                                },
                            ]
                        }
                    },
                    "cac:TendererQualificationRequest": {
                        "cbc:Description": "Certification ISO 27001 exigée"
                    },
                },
            }
        ],
    }
}


def test_parse_eforms_facts() -> None:
    f = eforms.parse(json.dumps(EFORMS_DOC))
    assert f.get("cpv_main") == "72267100"
    assert f.get("estimated_value_eur") == 450000.0
    assert f.get("deadline") == "2026-11-20"
    assert f.get("duration_months") == 36.0
    assert f.get("procedure_code") == "open"
    assert f.get("contract_folder_id") == "proc-0001"
    assert [c["weight"] for c in f.get("award_criteria")] == [60.0, 40.0]
    assert f.get("lots")[0]["id"] == "LOT-0001"
    assert f.get("qualifications") == ["Certification ISO 27001 exigée"]


def test_parse_tolerates_garbage() -> None:
    assert eforms.parse("not json").values == {}
    assert eforms.parse(None).values == {}
    assert eforms.parse({"unrelated": {"x": 1}}).values == {}


def _record(idweb: str, objet: str, published: str, donnees: object) -> dict[str, object]:
    return {
        "idweb": idweb,
        "objet": objet,
        "nomacheteur": "VILLE DE TESTVILLE",
        "dateparution": published,
        "datelimitereponse": "2026-11-20",
        "code_departement": ["75"],
        "procedure_libelle": "Procédure ouverte",
        "nature_libelle": "Avis de marché",
        "type_marche": ["SERVICES"],
        "url_avis": f"https://example.test/{idweb}",
        "donnees": json.dumps(donnees),
    }


def test_build_tenders_and_dedup(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    p = tmp_path / "boamp_open_2026-10-15.jsonl"
    recs = [
        _record("26-100", "Maintenance applicative", "2026-10-01", EFORMS_DOC),
        _record("26-100", "Maintenance applicative", "2026-10-01", EFORMS_DOC),  # same id
        _record("26-101", "Maintenance applicative (rectificatif)", "2026-10-05", EFORMS_DOC),
        _record("26-102", "Nettoyage des locaux", "2026-10-03", {}),
    ]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    counts = boamp.build_tenders(conn, [p])
    assert counts["tenders"] == 3
    row = conn.execute(
        "SELECT dept, cpv, cpv_division, estimated_value_eur, deadline_on FROM tenders "
        "WHERE notice_id = '26-100'"
    ).fetchone()
    assert row is not None
    assert row[:4] == ("75", "72267100", "72", 450000.0)
    by_reason = dedup.apply_to_tenders(conn)
    assert by_reason == {"same_procedure_id": 1}
    kept = conn.execute("SELECT duplicate_of FROM tenders WHERE notice_id = '26-100'").fetchone()
    assert kept == ("26-101",)
    facts = conn.execute(
        "SELECT count(DISTINCT fact) FROM tender_facts WHERE source = 'eforms'"
    ).fetchone()
    assert facts is not None and facts[0] >= 8
