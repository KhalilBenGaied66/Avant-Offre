"""Deterministic Jinja2 brief used as fallback.

Same five sections and citation rule as the LLM brief; every number is a fact display followed
by its citation, so the template always passes the verifier (tested).
"""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined

from avant_offre.brief.facts import BriefFacts

TEMPLATE = """\
## Recommandation
{{ band }}.{% if f.score %} Score de la grille : {{ f.score.display }} [{{ f.score.id }}].{% endif %}
{%- if f.hard_stops %} Critère d'arrêt : {{ f.hard_stops.display }} [{{ f.hard_stops.id }}].{% endif %}

## Pourquoi
{%- if f.fit %}
- Adéquation au profil : {{ f.fit.display }} des avis de la semaine font moins bien [{{ f.fit.id }}].
{%- endif %}
{%- if f.closest_win %}
- Contrat passé le plus proche : {{ f.closest_win.display }} [{{ f.closest_win.id }}].
{%- endif %}
{%- if f.references %}
- Références similaires parmi les contrats comparables : {{ f.references.display }} [{{ f.references.id }}].
{%- endif %}
{%- if not (f.fit or f.closest_win or f.references) %}
- Aucun historique exploitable pour cette entreprise.
{%- endif %}

## Concurrence
{%- if competitors %}
{%- for c in competitors %}
- {{ c.display }} [{{ c.id }}].
{%- endfor %}
{%- else %}
- Aucun concurrent identifiable dans les contrats comparables.
{%- endif %}
{%- if f.newcomer_share %}
- Primo-titulaires : {{ f.newcomer_share.display }} des contrats comparables [{{ f.newcomer_share.id }}], sur {{ f.newcomer_n.display }} contrats [{{ f.newcomer_n.id }}].
{%- endif %}
{%- if f.buyer_top_share %}
- Premier titulaire de l'acheteur : {{ f.buyer_top_share.display }} de ses contrats comparables [{{ f.buyer_top_share.id }}].
{%- endif %}

## Prix
{%- if f.price_p50 %}
- Fourchette P25–P75 des comparables : {{ f.price_p25.display }} à {{ f.price_p75.display }}, médiane {{ f.price_p50.display }} [{{ f.price_p25.id }}, {{ f.price_p75.id }}, {{ f.price_p50.id }}], sur {{ f.price_n.display }} contrats [{{ f.price_n.id }}].
{%- else %}
- Fourchette de prix non évaluée : trop peu de comparables avec un prix exploitable{% if f.price_n %}, {{ f.price_n.display }} [{{ f.price_n.id }}]{% endif %}.
{%- endif %}
{%- if f.estimated_value %}
- Montant estimé dans l'avis : {{ f.estimated_value.display }} [{{ f.estimated_value.id }}].
{%- endif %}
- Les accords-cadres sont exclus des prix : leur montant est un plafond.

## Points à vérifier
{%- if f.deadline %}
- Date limite : {{ f.deadline.display }} [{{ f.deadline.id }}], soit {{ f.days_left.display }} jours [{{ f.days_left.id }}].
{%- endif %}
{%- if f.not_assessed %}
- Critères non évalués : {{ f.not_assessed.display }} [{{ f.not_assessed.id }}].
{%- endif %}
{%- if f.sme_share %}
- Part des PME parmi les titulaires comparables : {{ f.sme_share.display }} [{{ f.sme_share.id }}].
{%- endif %}
{%- if f.bids_median %}
- Offres reçues, médiane des comparables : {{ f.bids_median.display }} [{{ f.bids_median.id }}].
{%- endif %}
"""

_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)  # noqa: S701 - Markdown, not HTML
_template = _env.from_string(TEMPLATE)


def render(facts: BriefFacts) -> str:
    by_key = facts.by_key()

    class _F(dict[str, object]):
        def __getattr__(self, name: str) -> object:
            return self.get(name)

    competitors = [by_key[k] for k in sorted(by_key) if k.startswith("competitor_")]
    return _template.render(band=facts.band, f=_F(by_key), competitors=competitors)
