"""Synthetic TEST FIXTURES shaped like the DECP tabular schema.

Fictitious companies and buyers, deterministic (seeded). Used only to exercise code paths;
never used for any reported number.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def luhn_complete(prefix: str) -> str:
    """Append the digit that makes ``prefix`` Luhn-valid."""
    for d in "0123456789":
        cand = prefix + d
        total = 0
        for i, ch in enumerate(reversed(cand)):
            n = int(ch)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        if total % 10 == 0:
            return cand
    raise AssertionError("unreachable")


def make_siret(seed: int) -> str:
    siren = luhn_complete(f"{seed:08d}")
    return luhn_complete(siren + "0001")


@dataclass(frozen=True)
class Company:
    name: str
    id: str | None
    id_type: str | None
    size: str | None
    dept: str
    theme: str
    weight: float = 1.0


THEMES: dict[str, tuple[str, list[str]]] = {
    "it": (
        "72",
        [
            "Maintenance applicative du logiciel de gestion {x}",
            "Développement d'une application web pour {x}",
            "Infogérance des serveurs et hébergement {x}",
            "Tierce maintenance applicative et support logiciel {x}",
            "Migration du système d'information vers le cloud {x}",
        ],
    ),
    "clean": (
        "90",
        [
            "Nettoyage des locaux administratifs {x}",
            "Entretien et nettoyage des bâtiments scolaires {x}",
            "Prestations de propreté et nettoyage des vitres {x}",
            "Entretien des espaces verts {x}",
        ],
    ),
    "build": (
        "45",
        [
            "Travaux de réhabilitation de l'école {x}",
            "Travaux de voirie et réseaux divers {x}",
            "Rénovation énergétique du gymnase {x}",
            "Construction d'un équipement sportif {x}",
        ],
    ),
    "consult": (
        "79",
        [
            "Assistance et conseil en organisation {x}",
            "Étude de stratégie et accompagnement au changement {x}",
            "Prestations de conseil en gestion financière {x}",
            "Formation et accompagnement des agents {x}",
        ],
    ),
}

PLACES = ["municipal", "communautaire", "départemental", "du centre", "nord", "sud", "est"]

COMPANIES: list[Company] = [
    Company("ALPHA INFORMATIQUE", make_siret(1001), "SIRET", "PME", "75", "it", 2.0),
    Company("EPSILON DATA", make_siret(1002), "SIRET", "ETI", "92", "it", 1.5),
    Company("BETA PROPRETE", make_siret(1003), "SIRET", "PME", "69", "clean", 2.0),
    Company("GAMMA BTP", make_siret(1004), "SIRET", "GE", "13", "build", 2.0),
    Company("DELTA CONSEIL", make_siret(1005), "SIRET", "PME", "75", "consult", 1.5),
    Company("KAPPA TRAVAUX", make_siret(1006), "SIRET", "PME", "69", "build", 1.0),
    # Fictitious sole trader (legal category 1000 in the SIRENE fixture).
    Company("CAMILLE EXEMPLE", make_siret(1007), "SIRET", "PME", "92", "clean", 1.0),
    Company("ZETA GMBH", "DE123456789", "TVA", None, "75", "it", 0.5),
    Company("OMEGA SERVICES", None, None, None, "13", "clean", 0.5),
    Company("SIGMA CONSULTING", make_siret(1008), "SIRET", "PME", "13", "consult", 1.0),
    Company("THETA LOGICIELS", make_siret(1009), "SIRET", "PME", "69", "it", 1.0),
    Company("IOTA NETTOYAGE", make_siret(1010), "SIRET", "PME", "75", "clean", 1.0),
]

BUYERS = [
    (make_siret(2001), "VILLE DE TESTVILLE", "75"),
    (make_siret(2002), "DEPARTEMENT DE FIXTURE", "92"),
    (make_siret(2003), "METROPOLE EXEMPLE", "69"),
    (make_siret(2004), "COMMUNAUTE DE COMMUNES DEMO", "13"),
]

LOCATION_FORMS = [
    ("Code postal", lambda d: f"{d}001" if len(d) == 2 else f"{d}00"),
    ("Code commune", lambda d: f"{d}056"),
    ("Code département", lambda d: d),
]


def build_rows(seed: int = 7, n_awards: int = 420) -> list[dict[str, object]]:
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    start = date(2023, 1, 1)
    span = (date(2025, 12, 31) - start).days
    weights = [c.weight for c in COMPANIES]
    for i in range(n_awards):
        comp = rng.choices(COMPANIES, weights=weights)[0]
        division, templates = THEMES[comp.theme]
        buyer_id, buyer_name, buyer_dept = rng.choice(BUYERS)
        # Companies mostly work in their own department.
        dept = comp.dept if rng.random() < 0.8 else buyer_dept
        type_code, make_code = rng.choice(LOCATION_FORMS)
        notified = start + timedelta(days=rng.randrange(span))
        objet = rng.choice(templates).format(x=rng.choice(PLACES))
        is_framework = rng.random() < 0.15
        amount = round(rng.lognormvariate(11.5, 0.8), 2)
        uid = f"{buyer_id}{2023 + i // 150}{i:05d}{division}000000"
        base: dict[str, object] = {
            "uid": uid,
            "id": f"{2023 + i // 150}{i:05d}",
            "acheteur_id": buyer_id,
            "acheteur_nom": buyer_name,
            "acheteur_departement_code": buyer_dept,
            "objet": objet,
            "montant": amount * (10 if is_framework else 1),
            "codeCPV": f"{division}{rng.randrange(100000, 999999)}-{rng.randrange(10)}",
            "procedure": rng.choice(
                ["Procédure non négociée ouverte", "Procédure négociée restreinte"]
            ),
            "nature": "Marché",
            "techniques": "Accord-cadre" if is_framework else None,
            "dureeMois": rng.choice([12, 24, 36, 48]),
            "dateNotification": notified,
            "lieuExecution_code": make_code(dept),
            "lieuExecution_typeCode": type_code,
            "offresRecues": rng.choice([None, 1, 2, 3, 4, 5, 7]),
            "formePrix": rng.choice(["Forfaitaire", "Unitaire", "Mixte"]),
            "idAccordCadre": None,
            "montant_anomalie": "aberrant" if rng.random() < 0.01 else None,
            "titulaire_id": comp.id,
            "titulaire_typeIdentifiant": comp.id_type,
            "titulaire_nom": comp.name,
            "titulaire_categorie": comp.size,
            "titulaire_activite_code": None,
            "titulaire_departement_code": comp.dept,
            "modification_id": 0,
            "donneesActuelles": True,
        }
        rows.append(base)
        # Some awards have a co-winner (groupement).
        if rng.random() < 0.08:
            other = rng.choice([c for c in COMPANIES if c.theme == comp.theme and c != comp])
            rows.append(
                {
                    **base,
                    "titulaire_id": other.id,
                    "titulaire_typeIdentifiant": other.id_type,
                    "titulaire_nom": other.name,
                    "titulaire_categorie": other.size,
                    "titulaire_departement_code": other.dept,
                }
            )
        # Some awards are modified later (amount change).
        if rng.random() < 0.1:
            rows.append(
                {
                    **base,
                    "modification_id": 1,
                    "montant": float(base["montant"]) * 1.1,  # type: ignore[arg-type]
                    "dateNotification": notified + timedelta(days=200),
                    "donneesActuelles": True,
                }
            )
    # Two exact duplicate rows and one row outside the sample scope (division 33).
    rows.append(dict(rows[0]))
    rows.append(dict(rows[1]))
    rows.append({**rows[2], "uid": "OUTOFSCOPE1", "codeCPV": "33100000-1"})
    return rows


def write_decp_fixture(path: Path, seed: int = 7) -> Path:
    rows = build_rows(seed)
    cols = list(rows[0].keys())
    table = pa.table({c: [r.get(c) for r in rows] for c in cols})
    pq.write_table(table, path)
    return path


# SIRENE fixture: legal category per SIREN (fictitious). 1000 = entrepreneur individuel.
SIRENE_FIXTURE: dict[str, dict[str, str]] = {
    c.id[:9]: {
        "nature_juridique": "1000" if c.name == "CAMILLE EXEMPLE" else "5710",
        "date_creation": "2010-03-01",
    }
    for c in COMPANIES
    if c.id_type == "SIRET" and c.id
}
