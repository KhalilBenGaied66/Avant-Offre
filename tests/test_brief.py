"""Steps 9–10: facts, template, verifier, writer (with a fake gateway)."""

from __future__ import annotations

from datetime import date

import pytest

from avant_offre.brief import facts as bf
from avant_offre.brief import template, verifier, writer
from avant_offre.intel.competitors import Competitor
from avant_offre.intel.market import MarketIntel
from avant_offre.intel.prices import UNRELIABLE_NOTE, PriceRange
from avant_offre.intel.stats import Stat
from avant_offre.llm import gateway
from avant_offre.score.scorecard import CriterionResult, ScoreResult
from avant_offre.search.matcher import Explanation, Match
from avant_offre.settings import get_scorecard

TODAY = date(2026, 10, 15)


def full_facts(band: str = "REVIEW") -> bf.BriefFacts:
    t = bf.TenderInfo(
        notice_id="26-1",
        objet="Maintenance applicative. Lot 2",
        buyer_name="VILLE DE TESTVILLE",
        deadline_on=date(2026, 11, 20),
        estimated_value_eur=450000.0,
    )
    sc = ScoreResult(
        notice_id="26-1",
        total=0.6789,
        band=band,  # type: ignore[arg-type]
        criteria=[
            CriterionResult(
                id="price_realism",
                label="Réalisme du prix",
                weight=0.1,
                value=None,
                input=None,
                assessed=False,
            )
        ],
        not_assessed=["price_realism"],
        assessed_weight=0.9,
    )
    m = Match(
        "26-1",
        1,
        3.2,
        0.875,
        [Explanation("u1", "Tierce maintenance applicative", date(2024, 3, 14), 0.9)],
    )
    intel = MarketIntel(
        reference="26-1",
        ref_date=TODAY,
        buyer_siret=None,
        n_comparables=100,
        competitors=[
            Competitor(
                company_key="1",
                public_id="1",
                name="3M SERVICES",
                score=1.0,
                comparable_wins=4,
                last_win_on=date(2024, 1, 1),
                incumbent_with_buyer=True,
                new_to_buyer=False,
                sources=["u2"],
            )
        ],
        newcomer_share=Stat(value=23.4567, n=80, sources=["a"]),
        price_range=PriceRange(p10=1e5, p25=245318.4, p50=310000, p75=512777, p90=9e5, n=42),
        sme_share=Stat(value=61.0, n=70),
        bids_received=Stat(value=4.0, n=50),
        buyer_top_winner_share=Stat(value=50.0, n=6),
        company_references=Stat(value=2.0, n=100),
    )
    return bf.build(t, sc, match=m, intel=intel, today=TODAY, company_key="9")


def sparse_facts() -> bf.BriefFacts:
    t = bf.TenderInfo(
        notice_id="26-2", objet=None, buyer_name=None, deadline_on=None, estimated_value_eur=None
    )
    sc = ScoreResult(notice_id="26-2", total=None, band="REVIEW", criteria=[], assessed_weight=0)
    return bf.build(t, sc, match=None, intel=None, today=TODAY, company_key=None)


def ids(facts: bf.BriefFacts) -> dict[str, str]:
    return {f.key: f.id for f in facts.facts}


def test_french_formats() -> None:
    assert bf.fr_eur(245318.4) == "245 000 €"
    assert bf.fr_eur(4321.0) == "4 321 €"
    assert bf.fr_pct(23.4567) == "23 %"
    assert bf.fr_score(0.6789) == "0,68"
    assert bf.fr_date(date(2026, 11, 20)) == "20/11/2026"


@pytest.mark.parametrize("make", [full_facts, sparse_facts])
def test_template_always_passes_the_verifier(make: object) -> None:
    facts = make()  # type: ignore[operator]
    text = template.render(facts)
    v = verifier.verify(text, facts, max_removed=0, max_words=250)
    assert not v.fallback, v.fallback_reason
    assert v.removed == []


@pytest.mark.parametrize(
    ("sentence", "ok"),
    [
        ("Médiane 310 000 € [{p50}].", True),
        ("Médiane 310 k€ [{p50}].", True),
        ("Médiane 0,31 M€ [{p50}].", True),
        ("Médiane 310 000 € [{p50}].", True),
        ("Premier quartile 245 318 € [{p25}].", True),
        ("Médiane 300 000 € [{p50}].", False),  # wrong number
        ("Primo-titulaires : 23,5 % [{ns}].", True),
        ("Primo-titulaires : 23,4 % [{ns}].", False),  # wrong at displayed precision
        ("Primo-titulaires : 23 %.", False),  # missing citation
        ("Date limite le 20 novembre 2026 [{dl}].", True),
        ("Date limite le 21/11/2026 [{dl}].", False),
        ("Fourchette P25–P75 [{p25}].", True),  # percentile labels are not numbers
        ("3M SERVICES a remporté 4 contrats [{c1}].", True),  # numbers inside a cited text fact
        ("Médiane 310 000 € [F999].", False),  # unknown citation
        ("Le marché est ouvert.", True),  # no number, no citation needed
    ],
)
def test_sentence_checks(sentence: str, ok: bool) -> None:
    facts = full_facts()
    k = ids(facts)
    s = sentence.format(
        p50=k["price_p50"],
        p25=k["price_p25"],
        ns=k["newcomer_share"],
        dl=k["deadline"],
        c1=k["competitor_1"],
    )
    assert (verifier.check_sentence(s, facts.by_id()) is None) is ok


def test_band_cutoffs_are_citable_facts() -> None:
    """The writer explained bands with invented cut-offs: the real ones are now facts."""
    facts = full_facts()
    i = ids(facts)
    by_id = facts.by_id()
    go, review = by_id[i["band_go"]], by_id[i["band_review"]]
    assert (go.value, review.value) == (get_scorecard().bands.go, get_scorecard().bands.review)
    real = f"Seuil REVIEW : {review.display} [{review.id}], seuil GO : {go.display} [{go.id}]."
    invented = f"Le score reste sous le seuil GO de 0,99 [{go.id}]."
    assert verifier.check_sentence(real, by_id) is None
    assert verifier.check_sentence(invented, by_id) is not None
    assert i["band_go"] in template.render(facts)


def test_numbers_among_facts_separates_citation_errors_from_unsupported_numbers() -> None:
    facts = full_facts()
    score = facts.by_id()[ids(facts)["score"]].display
    assert verifier.numbers_among_facts(f"Le score est de {score}.", facts)  # uncited, but a fact
    assert not verifier.numbers_among_facts("Le score est de 0,99.", facts)
    assert verifier.numbers_among_facts("Aucun chiffre ici.", facts)


def test_failing_sentence_is_removed_not_rewritten() -> None:
    facts = full_facts()
    text = template.render(facts).replace("61 %", "64 %")
    v = verifier.verify(text, facts, max_removed=2, max_words=250)
    assert not v.fallback
    assert len(v.removed) == 1 and "64" in v.removed[0].sentence
    assert "64" not in v.text and "PME" not in v.text


def test_fallback_when_recommendation_changes_the_band() -> None:
    facts = full_facts(band="REVIEW")
    text = template.render(facts).replace("REVIEW.", "GO.", 1)
    v = verifier.verify(text, facts, max_removed=2, max_words=250)
    assert v.fallback and "recommendation" in (v.fallback_reason or "")


def test_fallback_when_too_many_sentences_fail_or_section_missing() -> None:
    facts = full_facts()
    bad = template.render(facts).replace("88 %", "90 %").replace("61 %", "60 %")
    bad = bad.replace("23 %", "20 %")
    assert verifier.verify(bad, facts, max_removed=2, max_words=250).fallback
    no_prix = template.render(facts).replace("## Prix", "## Tarifs")
    assert verifier.verify(no_prix, facts, max_removed=2, max_words=250).fallback
    assert verifier.verify(template.render(facts), facts, max_removed=2, max_words=20).fallback


def _fake(text: str, finish: str = "stop"):  # type: ignore[no-untyped-def]
    def complete(
        task: str, messages: list[dict[str, object]], *, model: str | None = None
    ) -> gateway.LLMResult:
        assert "faits" in str(messages[1]["content"])
        return gateway.LLMResult(text, model or "fake/model", 900, 300, 1200.0, 0.0048, finish, "h")

    return complete


def test_default_writer_is_the_template_and_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("the default writer must not call the model")

    monkeypatch.setattr(gateway, "complete", no_call)
    facts = full_facts()
    b = writer.write(facts)
    assert b.fallback and b.fallback_reason == "template: brief.writer" and b.model is None
    assert b.text == template.render(facts)


def test_a_named_model_is_called_even_with_the_template_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evaluation names its models: it measures them whatever the default."""
    facts = full_facts()
    monkeypatch.setattr(gateway, "complete", _fake(template.render(facts)))
    assert writer.write(facts, model="fake/model").model == "fake/model"


@pytest.mark.usefixtures("llm_writer")
def test_writer_keeps_a_verified_llm_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = full_facts()
    monkeypatch.setattr(gateway, "complete", _fake(template.render(facts)))
    b = writer.write(facts)
    assert not b.fallback and b.model == "fake/model" and b.cost_usd == 0.0048


@pytest.mark.usefixtures("llm_writer")
def test_writer_falls_back_on_unverifiable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = full_facts()
    monkeypatch.setattr(gateway, "complete", _fake("## Recommandation\nGO, sans réserve."))
    b = writer.write(facts)
    assert b.fallback and b.fallback_reason and b.fallback_reason.startswith("verifier")
    assert b.text == template.render(facts)


@pytest.mark.usefixtures("llm_writer")
def test_writer_falls_back_on_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = full_facts()
    monkeypatch.setattr(gateway, "complete", _fake(template.render(facts), finish="length"))
    assert writer.write(facts).fallback_reason == "llm_stop:length"


@pytest.mark.usefixtures("llm_writer")
def test_writer_without_llm_uses_template() -> None:
    b = writer.write(full_facts())  # opted in, but no model answers in tests
    assert b.fallback and (b.fallback_reason or "").startswith("llm_unavailable")


def test_cost_estimate_uses_configured_prices() -> None:
    assert gateway.estimate_cost("anthropic/claude-sonnet-5-5", 1_000_000, 100_000) == 3.0
    assert gateway.estimate_cost("unknown/model", 10, 10) is None


def test_withheld_price_range_says_why_and_still_verifies() -> None:
    facts = full_facts()
    facts.facts = [f for f in facts.facts if not f.key.startswith("price_p")]
    facts.price_note = UNRELIABLE_NOTE
    text = template.render(facts)
    assert UNRELIABLE_NOTE in text and "trop peu de comparables" not in text
    v = verifier.verify(text, facts, max_removed=0, max_words=250)
    assert not v.fallback and not v.removed
