"""Step 3 — link award winners to companies: exact, SIREN, fuzzy, embedding fallback.

Order (SPEC §6.3, DECISIONS step 3):
1. ``exact``     — a valid SIRET (14 digits, Luhn; La Poste rule).
2. ``siren``     — an identifier that carries a valid SIREN: a 9-digit SIREN, a French VAT
                   number (FR + key + SIREN), or a SIRET with a bad check digit whose SIREN is
                   already known in the same department. The establishment is the company's
                   most frequent SIRET in that department, when one is known.
3. ``fuzzy``     — normalized name against known companies of the same department
                   (rapidfuzz WRatio, threshold in config).
4. ``embedding`` — residue only, when an embedder is available; always flagged.
Links from an earlier step are never overwritten by a later one.

The company key used everywhere downstream is the SIREN (legal unit), so a company that wins
through several establishments is one competitor and is not a "newcomer" when it opens a new
establishment.
"""

from __future__ import annotations

import csv
import logging
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from rapidfuzz import fuzz, process

from avant_offre.settings import get_settings
from avant_offre.transform.privacy import LEGAL_FORM_TOKENS

log = logging.getLogger(__name__)

LA_POSTE_SIREN = "356000000"

Embedder = Callable[[Sequence[str]], np.ndarray]


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def siren_valid(s: str) -> bool:
    return len(s) == 9 and luhn_valid(s)


def siret_valid(s: str) -> bool:
    if len(s) != 14 or not s.isdigit():
        return False
    if s.startswith(LA_POSTE_SIREN):  # La Poste establishments: digit sum multiple of 5
        return sum(int(c) for c in s) % 5 == 0
    return luhn_valid(s)


_VAT_FR = re.compile(r"^FR[0-9A-Z]{2}(\d{9})$")


def siren_from_vat(vat: str) -> str | None:
    m = _VAT_FR.match(vat.upper())
    if m and siren_valid(m.group(1)):
        return m.group(1)
    return None


def normalize_name(name: str | None) -> str:
    """Lowercase, strip accents, punctuation and legal-form tokens."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = re.findall(r"[a-z0-9]+", s.replace(".", ""))  # "S.A.R.L." -> "sarl"
    return " ".join(t for t in tokens if t not in LEGAL_FORM_TOKENS)


@dataclass
class Link:
    method: str
    confidence: float
    siren: str | None = None
    siret: str | None = None
    flagged: bool = False


@dataclass(frozen=True)
class WinnerRef:
    winner_id: str
    winner_id_type: str | None
    name: str | None
    dept: str | None


def link_by_identifier(
    ref: WinnerRef, known_siren_depts: dict[str, set[str]] | None = None
) -> Link | None:
    """Steps 1–2: deterministic links from the identifier alone."""
    wid = ref.winner_id.upper()
    if len(wid) == 14 and siret_valid(wid):
        return Link("exact", 1.0, siren=wid[:9], siret=wid)
    if len(wid) == 9 and siren_valid(wid):
        return Link("siren", 0.95, siren=wid)
    if (vat := siren_from_vat(wid)) is not None:
        return Link("siren", 0.95, siren=vat)
    if len(wid) == 14 and wid.isdigit() and siren_valid(wid[:9]):
        depts = (known_siren_depts or {}).get(wid[:9], set())
        if ref.dept and ref.dept in depts:
            return Link("siren", 0.85, siren=wid[:9])
    return None


def company_key(link: Link | None, ref: WinnerRef) -> str | None:
    if link and link.siren:
        return link.siren
    if ref.winner_id:
        return f"id:{ref.winner_id_type or 'NA'}:{ref.winner_id.upper()}"
    norm = normalize_name(ref.name)
    return f"name:{norm}" if norm else None


def resolve(
    conn: duckdb.DuckDBPyConnection,
    *,
    extra_candidates: Callable[[str], list[tuple[str, str]]] | None = None,
    embedder: Embedder | None = None,
) -> dict[str, int]:
    """Annotate award_winners with links. Returns the count of winner rows per method."""
    s = get_settings().entity_resolution
    rows = conn.execute(
        """
        SELECT DISTINCT w.winner_id, w.winner_id_type, w.winner_name_raw,
               coalesce(w.winner_dept, a.exec_dept) AS dept
        FROM award_winners w JOIN awards a USING (uid)
        """
    ).fetchall()
    refs = [WinnerRef(r[0] or "", r[1], r[2], r[3]) for r in rows]

    links = _exact_links(refs)
    _siren_links(refs, links)
    names_by_dept = _known_names(links)
    _fuzzy_links(refs, links, names_by_dept, extra_candidates, s.fuzzy_threshold)
    residue = [r for r in refs if r not in links and normalize_name(r.name) and r.dept]
    if embedder is not None and residue:
        _embedding_links(residue, names_by_dept, embedder, s.embedding_threshold, links)

    _write_back(conn, refs, links)
    counts = dict(
        conn.execute("SELECT link_method, count(*) FROM award_winners GROUP BY 1").fetchall()
    )
    log.info("entity resolution: %s", counts)
    return {str(k): int(v) for k, v in counts.items()}


def _exact_links(refs: list[WinnerRef]) -> dict[WinnerRef, Link]:
    """Pass 1: valid SIRET."""
    links: dict[WinnerRef, Link] = {}
    for ref in refs:
        link = link_by_identifier(ref)
        if link and link.method == "exact":
            links[ref] = link
    return links


def _siren_links(refs: list[WinnerRef], links: dict[WinnerRef, Link]) -> None:
    """Pass 2: identifiers carrying a SIREN; establishment = most frequent known SIRET."""
    siren_depts: dict[str, set[str]] = defaultdict(set)
    siret_by_siren_dept: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for ref, link in links.items():
        if link.siren and ref.dept:
            siren_depts[link.siren].add(ref.dept)
            if link.siret:
                siret_by_siren_dept[(link.siren, ref.dept)][link.siret] += 1
    for ref in refs:
        if ref in links:
            continue
        found = link_by_identifier(ref, siren_depts)
        if found is None:
            continue
        known = siret_by_siren_dept.get((found.siren or "", ref.dept or ""))
        if known:
            found.siret = known.most_common(1)[0][0]
        links[ref] = found


def _known_names(links: dict[WinnerRef, Link]) -> dict[str, dict[str, str]]:
    """dept -> normalized name -> SIREN, from the links established so far."""
    names_by_dept: dict[str, dict[str, str]] = defaultdict(dict)
    for ref, link in links.items():
        norm = normalize_name(ref.name)
        if norm and link.siren and ref.dept:
            names_by_dept[ref.dept].setdefault(norm, link.siren)
    return names_by_dept


def _fuzzy_links(
    refs: list[WinnerRef],
    links: dict[WinnerRef, Link],
    names_by_dept: dict[str, dict[str, str]],
    extra_candidates: Callable[[str], list[tuple[str, str]]] | None,
    threshold: float,
) -> None:
    """Pass 3: fuzzy names against known companies of the same department."""
    for ref in refs:
        if ref in links or not ref.dept or not normalize_name(ref.name):
            continue
        cands = dict(names_by_dept.get(ref.dept, {}))
        if extra_candidates is not None:
            for siren, name in extra_candidates(ref.dept):
                cands.setdefault(normalize_name(name), siren)
        if not cands:
            continue
        best = process.extractOne(
            normalize_name(ref.name), list(cands), scorer=fuzz.WRatio, score_cutoff=threshold
        )
        if best is not None:
            links[ref] = Link("fuzzy", round(best[1] / 100, 4), siren=cands[best[0]])


def _embedding_links(
    residue: list[WinnerRef],
    names_by_dept: dict[str, dict[str, str]],
    embedder: Embedder,
    threshold: float,
    links: dict[WinnerRef, Link],
) -> None:
    by_dept: dict[str, list[WinnerRef]] = defaultdict(list)
    for ref in residue:
        by_dept[ref.dept or ""].append(ref)
    for dept, group in by_dept.items():
        cands = names_by_dept.get(dept)
        if not cands:
            continue
        cand_names = list(cands)
        cv = embedder(cand_names)
        qv = embedder([normalize_name(r.name) for r in group])
        sims = qv @ cv.T
        for i, ref in enumerate(group):
            j = int(np.argmax(sims[i]))
            if sims[i, j] >= threshold:
                links[ref] = Link(
                    "embedding",
                    round(float(sims[i, j]), 4),
                    siren=cands[cand_names[j]],
                    flagged=True,
                )


def _write_back(
    conn: duckdb.DuckDBPyConnection, refs: list[WinnerRef], links: dict[WinnerRef, Link]
) -> None:
    records = []
    for ref in refs:
        link = links.get(ref)
        records.append(
            (
                ref.winner_id,
                ref.winner_id_type,
                ref.name,
                ref.dept,
                link.method if link else "none",
                link.confidence if link else None,
                link.siren if link else None,
                link.siret if link else None,
                link.flagged if link else False,
                company_key(link, ref),
            )
        )
    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE er_links (
            winner_id VARCHAR, winner_id_type VARCHAR, name VARCHAR, dept VARCHAR,
            method VARCHAR, confidence DOUBLE, siren VARCHAR, siret VARCHAR,
            flagged BOOLEAN, company_key VARCHAR)
        """
    )
    if records:
        conn.executemany("INSERT INTO er_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", records)
    conn.execute(
        """
        CREATE OR REPLACE TABLE award_winners AS
        SELECT w.* EXCLUDE (winner_siret, winner_siren, company_key, link_method,
                            link_confidence, link_flagged),
               l.siret AS winner_siret, l.siren AS winner_siren, l.company_key,
               coalesce(l.method, 'none') AS link_method, l.confidence AS link_confidence,
               coalesce(l.flagged, false) AS link_flagged
        FROM award_winners w
        JOIN awards a USING (uid)
        LEFT JOIN er_links l
          ON w.winner_id = l.winner_id
         AND w.winner_id_type IS NOT DISTINCT FROM l.winner_id_type
         AND w.winner_name_raw IS NOT DISTINCT FROM l.name
         AND coalesce(w.winner_dept, a.exec_dept) IS NOT DISTINCT FROM l.dept
        """
    )


def write_review_sample(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
    display: Callable[[str | None, str | None], str],
) -> int:
    """200-row hand-checkable sample, stratified by method, names passed through ``display``.

    ``display(name, company_key)`` returns the privacy-safe name (SPEC §4.6); with
    ``name=None`` it returns the company's own name.
    """
    s = get_settings()
    rows = conn.execute(
        """
        SELECT DISTINCT link_method, winner_id_type, winner_name_raw, company_key,
               winner_siren, link_confidence, link_flagged
        FROM award_winners ORDER BY ALL
        """
    ).fetchall()
    by_method: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for r in rows:
        by_method[str(r[0])].append(r)
    rng = random.Random(s.seed)
    n = s.entity_resolution.sample_csv_rows
    per = max(1, n // max(1, len(by_method)))
    picked: list[tuple[Any, ...]] = []
    for method in sorted(by_method):
        group = by_method[method]
        picked += rng.sample(group, min(per, len(group)))
    picked = picked[:n]
    legal_person = {
        str(k): natural is False
        for k, natural in conn.execute(
            "SELECT company_key, is_natural_person FROM company_names"
        ).fetchall()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "link_method",
                "winner_id_type",
                "winner_name_shown",
                "linked_company_shown",
                "linked_siren",
                "link_confidence",
                "flagged",
                "review_ok",
                "review_note",
            ]
        )
        for method, id_type, raw_name, key, siren, conf, flagged in picked:
            shown = display(str(raw_name) if raw_name else None, str(key) if key else None)
            linked = display(None, str(siren)) if siren else ""
            # A sole trader's SIREN finds the person's name in SIRENE: only legal persons keep
            # it (fail closed when the status is unknown).
            siren_shown = siren if siren and legal_person.get(str(siren)) is True else ""
            w.writerow([method, id_type, shown, linked, siren_shown, conf, flagged, "", ""])
    return len(picked)
