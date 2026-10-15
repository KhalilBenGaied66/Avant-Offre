"""Structured facts of a BOAMP notice, whatever its format.

The ``donnees`` field holds one top-level key naming the format: ``EFORMS`` (EU thresholds and
above) or a national format (``FNSimple``, ``MAPA``, ``DSP``, ``DIVERS``). The fact names are the
same for every format; ``source`` records where they were read (``eforms`` or ``national``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from avant_offre.extract import eforms, national


@dataclass
class NoticeFacts:
    values: dict[str, Any] = field(default_factory=dict)
    source: str | None = None  # 'eforms' | 'national'; None when nothing was read
    notice_format: str | None = None  # top-level key of `donnees`

    def get(self, name: str) -> Any:
        return self.values.get(name)


def _load(donnees: str | dict[str, Any] | None) -> Any:
    if isinstance(donnees, str):
        try:
            return json.loads(donnees)
        except json.JSONDecodeError:
            return None
    return donnees


def parse(donnees: str | dict[str, Any] | None) -> NoticeFacts:
    doc = _load(donnees)
    if not isinstance(doc, dict) or not doc:
        return NoticeFacts()
    fmt = next(iter(doc)) if len(doc) == 1 else None
    if fmt in national.FORMATS:
        values = national.parse(fmt, doc[fmt])
        return NoticeFacts(values, "national" if values else None, fmt)
    if fmt in national.NOT_PARSED:
        return NoticeFacts(notice_format=fmt)
    values = eforms.parse(doc).values
    return NoticeFacts(values, "eforms" if values else None, fmt)
