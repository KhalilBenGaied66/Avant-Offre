"""Step 7 statistics and step 8 scorecard."""

from __future__ import annotations

import math
from datetime import date

import pytest

from avant_offre.intel.comparables import Comparable
from avant_offre.intel.competitors import CompetitorModel
from avant_offre.intel.market import MarketIntel
from avant_offre.intel.prices import PriceRange, price_range
from avant_offre.intel.stats import Stat, bids_received
from avant_offre.score import scorecard
from avant_offre.settings import get_scorecard


def comp(
    uid: str,
    amount: float | None,
    *,
    framework: bool = False,
    anomaly: str | None = None,
    sim: float = 1.0,
    d: date = date(2024, 1, 1),
    buyer: str | None = "B1",
    bids: int | None = None,
) -> Comparable:
    return Comparable(
        uid, sim, d, buyer, "Buyer", "objet", "72000000", "75", amount, framework, anomaly, bids
    )


def test_price_range_excludes_frameworks_and_aberrant() -> None:
    comps = [comp(f"u{i}", float(100 * (i + 1))) for i in range(9)]
    comps += [
        comp("fw", 1e9, framework=True),
        comp("ab", 1e9, anomaly="aberrant"),
        comp("zero", 0.0),
        comp("none", None),
    ]
    pr = price_range(comps, min_n=5)
    assert pr.n == 9 and pr.excluded_frameworks == 1
    assert pr.p50 == pytest.approx(500.0)
    assert pr.p25 == pytest.approx(300.0) and pr.p75 == pytest.approx(700.0)
    assert "fw" not in pr.sources


def test_price_range_not_assessed_below_min_n() -> None:
    pr = price_range([comp("a", 1.0), comp("b", 2.0)], min_n=5)
    assert not pr.assessed and pr.n == 2


def test_bids_received_ignores_zero_and_missing() -> None:
    s = bids_received([("a", 0), ("b", None), ("c", 3), ("d", 5)])
    assert s.value == 4.0 and s.n == 2 and s.sources == ["c", "d"]


class _Model(CompetitorModel):
    def __init__(self) -> None:  # bypass SQL loading: winners given directly
        self.winners = {"u1": ["A"], "u2": ["A", "B"], "u3": ["C"]}
        self.buyer_history = {("A", "B1")}
        self.names = {"A": "ALPHA", "B": "BETA", "C": "GAMMA"}


def test_competitor_score_formula_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AVANT_OFFRE_INTEL__TAU_DAYS", "365")
    monkeypatch.setenv("AVANT_OFFRE_INTEL__SAME_BUYER_BOOST", "0.5")
    from avant_offre.settings import reset_caches  # noqa: PLC0415

    reset_caches()
    ref = date(2025, 1, 1)
    comps = [
        comp("u1", 1.0, sim=0.8, d=date(2024, 1, 2), buyer="B1"),
        comp("u2", 1.0, sim=0.5, d=date(2023, 1, 2), buyer="B2"),
        comp("u3", 1.0, sim=0.9, d=date(2024, 12, 1), buyer="B2"),
    ]
    out = _Model().predict(comps, ref, "B1", exclude="C")
    by = {c.company_key: c for c in out}
    assert "C" not in by  # the company itself is excluded
    exp_a = 0.8 * math.exp(-365 / 365) * 1.5 + 0.5 * math.exp(-730 / 365)
    assert by["A"].score == pytest.approx(exp_a, rel=1e-5)
    assert by["A"].incumbent_with_buyer and not by["A"].new_to_buyer
    assert by["B"].new_to_buyer and not by["B"].incumbent_with_buyer
    assert [c.company_key for c in out] == ["A", "B"]


def _intel(**kw: object) -> MarketIntel:
    base: dict[str, object] = dict(
        reference="T",
        ref_date=date(2026, 10, 15),
        buyer_siret="B1",
        n_comparables=50,
        newcomer_share=Stat(value=20.0, n=40),
        price_range=PriceRange(p25=100.0, p50=150.0, p75=200.0, n=30),
        sme_share=Stat(value=None, n=0),
        bids_received=Stat(value=None, n=0),
        buyer_top_winner_share=Stat(value=75.0, n=4),
        company_references=Stat(value=2.0, n=50),
    )
    base.update(kw)
    return MarketIntel(**base)  # type: ignore[arg-type]


def test_price_realism_decay() -> None:
    assert scorecard.price_realism(150, 100, 200, 4.0) == 1.0
    assert scorecard.price_realism(400, 100, 200, 4.0) == pytest.approx(0.5)
    assert scorecard.price_realism(25, 100, 200, 4.0) == pytest.approx(0.0)


def test_scorecard_values_weights_and_band() -> None:
    t = scorecard.TenderInputs(
        notice_id="T",
        deadline_on=date(2026, 11, 14),
        estimated_value_eur=150.0,
        dept="75",
        fit_percentile=0.9,
    )
    r = scorecard.score(t, _intel(), date(2026, 10, 15))
    v = {c.id: c.value for c in r.criteria}
    assert v == pytest.approx(
        {
            "fit": 0.9,
            "references": 2 / 3,
            "incumbent_risk": 0.25,
            "openness": 0.2,
            "price_realism": 1.0,
            "deadline": 1.0,
        },
        abs=1e-4,
    )
    expected = 0.3 * 0.9 + 0.2 * 2 / 3 + 0.15 * 0.25 + 0.1 * 0.2 + 0.1 * 1 + 0.15 * 1
    assert r.total == pytest.approx(expected, abs=1e-4)
    assert r.band == "GO" and r.not_assessed == [] and r.assessed_weight == pytest.approx(1.0)


def test_missing_inputs_are_not_imputed() -> None:
    t = scorecard.TenderInputs(
        notice_id="T", deadline_on=None, estimated_value_eur=None, dept="75", fit_percentile=0.5
    )
    r = scorecard.score(t, None, date(2026, 10, 15))
    assert r.not_assessed == [
        "references",
        "incumbent_risk",
        "openness",
        "price_realism",
        "deadline",
    ]
    assert r.total == pytest.approx(0.5) and r.assessed_weight == pytest.approx(0.3)
    assert r.band == "REVIEW"


def test_hard_stop_forces_no_go() -> None:
    cfg = get_scorecard()
    t = scorecard.TenderInputs(
        notice_id="T",
        deadline_on=date(2026, 10, 20),
        estimated_value_eur=150.0,
        dept="75",
        fit_percentile=1.0,
    )
    r = scorecard.score(t, _intel(), date(2026, 10, 15), cfg)
    assert r.band == "NO-GO" and r.hard_stops
