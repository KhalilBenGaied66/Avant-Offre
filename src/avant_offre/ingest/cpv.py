"""CPV 2008 reference: official labels when reachable, hierarchy derived from codes otherwise.

SPEC §4.5: codes are enough for the logic. The hierarchy is positional — division = 2 digits,
group = 3, class = 4, category = 5 — so it is derived from the code itself. Labels are
display-only and loaded from ``sources.cpv.labels_url`` when configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The 45 divisions of the CPV 2008 main vocabulary (Commission Regulation (EC) No 213/2008).
# Used only to flag invalid codes in the data-quality report.
VALID_DIVISIONS: frozenset[str] = frozenset(
    {
        "03", "09", "14", "15", "16", "18", "19", "22", "24", "30", "31", "32", "33", "34",
        "35", "37", "38", "39", "41", "42", "43", "44", "45", "48", "50", "51", "55", "60",
        "63", "64", "65", "66", "70", "71", "72", "73", "75", "76", "77", "79", "80", "85",
        "90", "92", "98",
    }
)  # fmt: skip

_CPV_RE = re.compile(r"^\s*(\d{8})(?:-\d)?\s*$")


@dataclass(frozen=True)
class CpvLevels:
    code: str
    division: str
    group: str
    klass: str
    category: str

    @property
    def valid(self) -> bool:
        return self.division in VALID_DIVISIONS


def normalize_cpv(raw: str | None) -> str | None:
    """Return the 8-digit CPV code, or None when the value is not a CPV code."""
    if raw is None:
        return None
    m = _CPV_RE.match(raw)
    return m.group(1) if m else None


def levels(code: str) -> CpvLevels:
    return CpvLevels(code, code[:2], code[:3], code[:4], code[:5])


def group_of(code: str | None, digits: int) -> str | None:
    """Prefix used by the CPV alert baseline (SPEC §7.2), e.g. 3 digits = CPV group."""
    return code[:digits] if code else None
