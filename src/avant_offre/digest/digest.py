"""Weekly digest JSON for a company (step 12).

Payload only: delivery is a Power Automate flow owned by IT (docs/POWER_AUTOMATE.md). Nothing in
this module sends a message. The HTML rendering is the no-premium-licence path: a scheduled job
writes it to a folder the flow watches.
"""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import quote

from jinja2 import Environment
from pydantic import BaseModel

from avant_offre.service import Engine, Shortlist
from avant_offre.settings import get_settings


class DigestCounts(BaseModel):
    eligible: int
    excluded: int
    go: int
    review: int
    no_go: int


class DigestItem(BaseModel):
    notice_id: str
    rank: int
    band: str
    total: float | None
    deadline_on: date | None
    buyer_name: str | None
    objet: str | None
    fit_percentile: float
    link: str


class Digest(BaseModel):
    company_key: str | None
    company_name: str
    week_start: date
    week_end: date
    generated_at: datetime
    counts: DigestCounts
    items: list[DigestItem]
    shortlist_link: str


def _company_name(engine: Engine, key: str | None) -> str:
    if key is None:
        return "Profil libre"
    row = engine.conn.execute(
        "SELECT display_name FROM company_names WHERE company_key = ?", [key]
    ).fetchone()
    return str(row[0]) if row else key


def build(engine: Engine, shortlist: Shortlist, siret: str, top: int | None = None) -> Digest:
    s = get_settings().api
    top = top or s.digest_top
    base = s.public_base_url.rstrip("/")
    bands = [i.band for i in shortlist.eligible]
    q = quote(siret)
    return Digest(
        company_key=shortlist.company_key,
        company_name=_company_name(engine, shortlist.company_key),
        week_start=shortlist.week_start,
        week_end=shortlist.week_end,
        generated_at=datetime.now().replace(microsecond=0),
        counts=DigestCounts(
            eligible=len(shortlist.eligible),
            excluded=len(shortlist.excluded),
            go=bands.count("GO"),
            review=bands.count("REVIEW"),
            no_go=bands.count("NO-GO"),
        ),
        items=[
            DigestItem(
                notice_id=i.notice_id,
                rank=i.rank,
                band=i.band,
                total=i.total,
                deadline_on=i.deadline_on,
                buyer_name=i.buyer_name,
                objet=i.objet,
                fit_percentile=i.fit_percentile,
                link=f"{base}/#/tender/{quote(i.notice_id)}?siret={q}",
            )
            for i in shortlist.eligible[:top]
        ],
        shortlist_link=f"{base}/#/?siret={q}",
    )


HTML = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Avant-Offre — {{ d.company_name }}</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;color:#1b1b1b;max-width:720px">
<h2 style="margin-bottom:4px">Avant-Offre — sélection de la semaine</h2>
<p style="color:#555;margin-top:0">{{ d.company_name }} · semaine du {{ d.week_start.strftime('%d/%m/%Y') }}</p>
<p>{{ d.counts.eligible }} avis éligibles ({{ d.counts.go }} GO, {{ d.counts.review }} à étudier,
{{ d.counts.no_go }} NO-GO) · {{ d.counts.excluded }} exclus.</p>
<table cellpadding="6" style="border-collapse:collapse;width:100%">
<tr style="background:#f2f2f2;text-align:left"><th>Avis</th><th>Acheteur</th><th>Limite</th><th>Bande</th></tr>
{% for i in d.items %}<tr style="border-top:1px solid #ddd">
<td><a href="{{ i.link }}">{{ i.objet or i.notice_id }}</a></td><td>{{ i.buyer_name or '—' }}</td>
<td>{{ i.deadline_on.strftime('%d/%m/%Y') if i.deadline_on else 'inconnue' }}</td>
<td><b style="color:{{ colors.get(i.band, '#333') }}">{{ i.band }}</b></td></tr>
{% endfor %}</table>
<p><a href="{{ d.shortlist_link }}">Voir toute la sélection</a></p>
<p style="color:#777;font-size:12px">Préparé automatiquement à partir de données publiques (DECP, BOAMP).
La décision go/no-go reste celle du comité.</p>
</body></html>
"""

_env = Environment(autoescape=True)
_html = _env.from_string(HTML)


def render_html(d: Digest) -> str:
    colors = {"GO": "#107c10", "REVIEW": "#a35f00", "NO-GO": "#a4262c"}
    return _html.render(d=d, colors=colors)
