"""Price range (P10–P90) over comparable non-framework awards.

Excluded from price statistics: framework agreements (their amount is a ceiling, not a spend),
amounts the publisher flags ``aberrant``, and amounts ≤ 0. Quantiles use linear interpolation
(numpy default). Below ``intel.min_price_n`` comparables the range is "not assessed".
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, Field

from avant_offre.intel.comparables import Comparable
from avant_offre.settings import get_settings


class PriceRange(BaseModel):
    p10: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    n: int = 0
    sources: list[str] = Field(default_factory=list)
    excluded_frameworks: int = 0

    @property
    def assessed(self) -> bool:
        return self.p50 is not None


def usable(c: Comparable) -> bool:
    return (
        c.amount_eur is not None
        and c.amount_eur > 0
        and not c.is_framework
        and (c.amount_anomaly or "") != "aberrant"
    )


def price_range(comparables: Sequence[Comparable], min_n: int | None = None) -> PriceRange:
    min_n = get_settings().intel.min_price_n if min_n is None else min_n
    kept = [c for c in comparables if usable(c)]
    frameworks = sum(1 for c in comparables if c.is_framework)
    if len(kept) < max(1, min_n):
        return PriceRange(
            n=len(kept), sources=[c.uid for c in kept], excluded_frameworks=frameworks
        )
    amounts = np.array([c.amount_eur for c in kept], dtype=float)
    q = np.quantile(amounts, [0.10, 0.25, 0.50, 0.75, 0.90])
    return PriceRange(
        p10=float(q[0]),
        p25=float(q[1]),
        p50=float(q[2]),
        p75=float(q[3]),
        p90=float(q[4]),
        n=len(kept),
        sources=[c.uid for c in kept],
        excluded_frameworks=frameworks,
    )
