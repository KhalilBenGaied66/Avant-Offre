"""Personal data rule (SPEC §4.6): pseudonymize natural-person winners.

Sole traders ("entrepreneur individuel", SIRENE legal category 1000) are natural persons. Their
name never leaves the system: UI, API, MCP outputs, demo data and committed reports show
``Entreprise individuelle #<hash6>`` instead. The identifier is kept internally for joins.

Fail closed: when the legal status of a winner is unknown (no SIRENE record and no legal form in
the name), its name is also masked, with a label that says so.

``hash6`` is a stable display label, not anonymization: the data stays personal data
(pseudonymized) under the GDPR.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

NATURAL_PERSON_LEGAL_CATEGORY = "1000"
NON_DIFFUSIBLE_MARK = "[Données personnelles non-diffusibles]"

# Legal-form tokens that only legal persons carry (French and common foreign forms).
LEGAL_FORM_TOKENS: frozenset[str] = frozenset(
    {
        "sa", "sas", "sasu", "sarl", "eurl", "snc", "scs", "sca", "sci", "scp", "scop", "scic",
        "selarl", "selas", "gie", "sem", "spl", "association", "groupement", "societe",
        "gmbh", "ag", "kg", "bv", "nv", "ltd", "limited", "plc", "llc", "inc", "spa", "srl",
        "sl", "sll", "sprl", "oy", "ab", "as", "aps", "kft", "sro", "doo",
    }
)  # fmt: skip


def hash6(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]


def _tokens(name: str) -> list[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", ascii_name.replace(".", ""))  # "S.A.R.L." -> "sarl"


def has_legal_form(name: str | None) -> bool:
    return bool(name) and any(t in LEGAL_FORM_TOKENS for t in _tokens(name or ""))


def is_natural_person(legal_category: str | None, name: str | None) -> bool | None:
    """True / False when known, None when the legal status cannot be established."""
    if name and NON_DIFFUSIBLE_MARK.lower() in name.lower():
        return True
    if legal_category:
        return legal_category.strip() == NATURAL_PERSON_LEGAL_CATEGORY
    if has_legal_form(name):
        return False
    return None


def display_name(name: str | None, key: str, natural_person: bool | None) -> str:
    if natural_person is False and name:
        return name
    if natural_person is True:
        return f"Entreprise individuelle #{hash6(key)}"
    return f"Titulaire non vérifié #{hash6(key)}"


def public_key(key: str, natural_person: bool | None) -> str:
    """An identifier safe to show outside the store.

    A legal person keeps its own key (its SIREN, public company data). A natural person, or a
    winner whose status is unknown, gets an opaque hash: a sole trader's SIREN finds the
    person's name in SIRENE. ``PUBLIC_KEY_SQL`` is the same rule in DuckDB.
    """
    if natural_person is False:
        return key
    return "anon-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


PUBLIC_KEY_SQL = (
    "CASE WHEN {natural} IS NOT DISTINCT FROM false THEN {key} "
    "ELSE 'anon-' || substr(sha256({key}), 1, 12) END"
)
