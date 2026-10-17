"""Notice parsing (eForms and national formats) and the tenders table (fictitious records)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from avant_offre.extract import eforms, llm_extract, notice
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


# The layout observed on real notices (October 2026, DATA_QUALITY F-005): the buyer is a
# reference to an organisation, durations are per lot, and the bid validity period also carries
# a DurationMeasure that must not be read as the contract duration.
EFORMS_REAL_LAYOUT = {
    "EFORMS": {
        "ContractNotice": {
            "cac:ContractingParty": {
                "cac:Party": {"cac:PartyIdentification": {"cbc:ID": "ORG-0002"}}
            },
            "cac:TenderingTerms": {
                "cac:TenderValidityPeriod": {
                    "cbc:DurationMeasure": {"@unitCode": "MONTH", "#text": "4"}
                }
            },
            "cac:ProcurementProjectLot": [
                {
                    "cbc:ID": "LOT-0001",
                    "cac:ProcurementProject": {
                        "cac:PlannedPeriod": {
                            "cbc:DurationMeasure": {"@unitCode": "MONTH", "#text": "12"}
                        }
                    },
                },
                {
                    "cbc:ID": "LOT-0002",
                    "cac:ProcurementProject": {
                        "cac:PlannedPeriod": {
                            "cbc:StartDate": "2027-01-01+01:00",
                            "cbc:EndDate": "2028-12-31+01:00",
                        }
                    },
                },
            ],
            "ext:UBLExtensions": {
                "efac:Organizations": {
                    "efac:Organization": [
                        {
                            "efac:Company": {
                                "cac:PartyIdentification": {"cbc:ID": "ORG-0001"},
                                "cac:PartyLegalEntity": {"cbc:CompanyID": "PLATFORM-REF-9"},
                            }
                        },
                        {
                            "efac:Company": {
                                "cac:PartyIdentification": {"cbc:ID": "ORG-0002"},
                                "cac:PartyLegalEntity": {"cbc:CompanyID": "000 000 001 00017"},
                            }
                        },
                    ]
                }
            },
        }
    }
}


def test_eforms_real_layout_duration_and_buyer() -> None:
    f = notice.parse(json.dumps(EFORMS_REAL_LAYOUT))
    assert (f.source, f.notice_format) == ("eforms", "EFORMS")
    assert f.get("duration_months") == 24.0  # longest lot; never the 4-month bid validity
    assert f.get("buyer_siret") == "00000000100017"


def test_eforms_buyer_with_platform_number_is_not_a_siret() -> None:
    doc = json.loads(json.dumps(EFORMS_REAL_LAYOUT))
    orgs = doc["EFORMS"]["ContractNotice"]["ext:UBLExtensions"]["efac:Organizations"]
    orgs["efac:Organization"][1]["efac:Company"]["cac:PartyLegalEntity"]["cbc:CompanyID"] = "55820"
    assert notice.parse(doc).get("buyer_siret") is None


FNSIMPLE_DOC = {
    "FNSimple": {
        "organisme": {
            "nomOfficiel": "Commune de Testville",
            "typeIdentificationNational": {"siret": ""},
            "codeIdentificationNational": "00000000200015",
        },
        "initial": {
            "procedure": {
                "procedureAdapteeO": "",
                "capaciteEcoFin": "Chiffre d'affaires des trois derniers exercices.",
                "capaciteTech": "Liste des références de moins de cinq ans.",
                "dateReceptionOffres": "2026-11-06T12:00:00.000+02:00",
                "criteresAttrib": "Critères énoncés dans les documents de la consultation",
            },
            "natureMarche": {
                "intitule": "Entretien des espaces verts",
                "codeCPV": {"objetPrincipal": {"classPrincipale": "77310000"}},
                "dureeMois": "24",
                "valeurEstimee": {"@devise": "EUR", "fourchette": {"valeurHaute": "90000"}},
            },
            "lots": {
                "lot": [
                    {
                        "description": "Secteur nord",
                        "codeCPV": {"objetPrincipal": {"classPrincipale": "77310000"}},
                        "estimationValeur": {"@devise": "EUR", "valeur": "40000.0"},
                    },
                    {
                        "description": "Secteur sud",
                        "codeCPV": {"objetPrincipal": {"classPrincipale": "77311000"}},
                        "estimationValeur": {"@devise": "EUR", "valeur": "35000"},
                    },
                ]
            },
        },
    }
}

MAPA_DOC = {
    "MAPA": {
        "organisme": {"acheteurPublic": "COMMUNAUTE DE COMMUNES DE TEST"},
        "initial": {
            "criteres": {
                "criterePondere": [
                    {"criterePCT": "60", "critere": "Prix"},
                    {"criterePCT": "40", "critere": "Valeur technique"},
                ]
            },
            "delais": {"receptionOffres": "2026-11-10T10:00:00", "validite": {"nbJours": "120"}},
            "duree": {"dateACompterDu": "2027-01-01", "dateJusquau": "2027-06-30"},
            "lots": {"lot": {"numLot": "1", "description": "Projecteur"}},
        },
    }
}


def test_parse_fnsimple() -> None:
    f = notice.parse(json.dumps(FNSIMPLE_DOC))
    assert (f.source, f.notice_format) == ("national", "FNSimple")
    assert f.get("cpv_main") == "77310000"
    assert f.get("deadline") == "2026-11-06"
    assert f.get("duration_months") == 24.0
    assert f.get("buyer_siret") == "00000000200015"
    # A range is not a point estimate; the lots all carry one, so their sum is used.
    assert f.get("estimated_value_eur") == 75000.0
    assert [lot["cpv"] for lot in f.get("lots")] == ["77310000", "77311000"]
    assert len(f.get("qualifications")) == 2
    # Free-text criteria are left to the LLM fallback (verbatim quotes), not parsed here.
    assert f.get("award_criteria") is None
    assert f.get("contract_folder_id") is None  # buyer-internal ids would collide in dedup


def test_parse_mapa() -> None:
    f = notice.parse(MAPA_DOC)
    assert (f.source, f.notice_format) == ("national", "MAPA")
    assert f.get("deadline") == "2026-11-10"
    assert f.get("duration_months") == 6.0  # from the dates; never the 120-day bid validity
    assert [(c["description"], c["weight"]) for c in f.get("award_criteria")] == [
        ("Prix", 60.0),
        ("Valeur technique", 40.0),
    ]
    assert f.get("lots") == [
        {"id": "1", "title": "Projecteur", "cpv": None, "estimated_value_eur": None}
    ]
    assert f.get("buyer_siret") is None and f.get("cpv_main") is None


def test_unparsed_formats_are_labelled_not_guessed() -> None:
    f = notice.parse({"DSP": {"organisme": {}, "initial": {"descriptionMarche": {}}}})
    assert (f.values, f.source, f.notice_format) == ({}, None, "DSP")


def test_build_tenders_records_format_and_source(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    p = tmp_path / "boamp_open_2026-10-15.jsonl"
    recs = [
        _record("26-200", "Entretien des espaces verts", "2026-10-01", FNSIMPLE_DOC),
        _record("26-201", "Projecteur", "2026-10-02", MAPA_DOC),
    ]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    boamp.build_tenders(conn, [p])
    rows = conn.execute(
        "SELECT notice_id, notice_format, buyer_siret, buyer_siret_source, cpv FROM tenders "
        "ORDER BY notice_id"
    ).fetchall()
    assert rows == [
        ("26-200", "FNSimple", "00000000200015", "national", "77310000"),
        ("26-201", "MAPA", None, "none", None),
    ]
    sources = conn.execute("SELECT DISTINCT source FROM tender_facts").fetchall()
    assert sources == [("national",)]


def test_llm_text_of_national_notice_excludes_contact_person() -> None:
    doc = json.loads(json.dumps(FNSIMPLE_DOC))
    doc["FNSimple"]["initial"]["communication"] = {
        "nomContact": "Prénom Fictif",
        "adresseMailContact": "contact@example.test",
    }
    text = llm_extract.notice_text("Entretien", json.dumps({"donnees": json.dumps(doc)}))
    assert "Critères énoncés dans les documents de la consultation" in text
    assert "Secteur nord" in text
    assert "Fictif" not in text and "example.test" not in text


def test_llm_text_includes_eforms_criteria_written_as_text() -> None:
    doc = {
        "EFORMS": {
            "ContractNotice": {
                "cac:AwardingCriterion": {
                    "cbc:CalculationExpression": {
                        "@languageID": "FRA",
                        "#text": "Prix des prestations (50%)\nValeur technique (50%)",
                    }
                }
            }
        }
    }
    text = llm_extract.notice_text("Objet", json.dumps({"donnees": json.dumps(doc)}))
    assert "Prix des prestations (50%)" in text
