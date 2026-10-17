"""TED (EU tenders) search API client. Optional, M5 or later.

Use (SPEC §4.3): add French notices above EU thresholds that are missing from BOAMP. Disabled by
``sources.ted.enabled`` until the API host is reachable and its current version verified.
"""

from __future__ import annotations

from typing import Any

import httpx

from avant_offre.ingest.manifest import http_client, with_retries
from avant_offre.settings import get_settings


def search(query: str, fields: list[str], limit: int = 100) -> list[dict[str, Any]]:
    """Anonymous expert search, e.g. ``place-of-performance=FRA AND publication-date>=20261001``."""
    s = get_settings().sources.ted
    if not s.enabled:
        raise RuntimeError("TED is disabled (sources.ted.enabled = false)")

    def _post(c: httpx.Client) -> list[dict[str, Any]]:
        r = c.post(
            f"{s.api_base}/notices/search",
            json={"query": query, "fields": fields, "limit": limit},
        )
        r.raise_for_status()
        notices = r.json().get("notices", [])
        return [n for n in notices if isinstance(n, dict)]

    with http_client() as c:
        return with_retries(_post)(c)
