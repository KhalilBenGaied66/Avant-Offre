"""Microsoft Teams Adaptive Card payload for the weekly digest.

Card schema version 1.4: the version the Teams "Post card in a chat or channel" action of Power
Automate renders on every Teams client. The elements used here are modelled with pydantic,
``extra="forbid"`` and the schema's enumerations, so an invalid property or value fails at build
time (the official JSON schema could not be fetched from this environment; see docs/MCP.md and
docs/POWER_AUTOMATE.md).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from avant_offre.digest.digest import Digest

CARD_VERSION: Literal["1.4"] = "1.4"
SCHEMA_URL = "http://adaptivecards.io/schemas/adaptive-card.json"
TEAMS_MAX_BYTES = 28_000  # Teams message size limit (approx. 28 KB)

Color = Literal["Default", "Dark", "Light", "Accent", "Good", "Warning", "Attention"]
Size = Literal["Default", "Small", "Medium", "Large", "ExtraLarge"]
Weight = Literal["Default", "Lighter", "Bolder"]
Spacing = Literal["None", "Small", "Default", "Medium", "Large", "ExtraLarge", "Padding"]
ContainerStyle = Literal["default", "emphasis", "good", "attention", "warning", "accent"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TextBlock(_Strict):
    type: Literal["TextBlock"] = "TextBlock"
    text: str
    size: Size | None = None
    weight: Weight | None = None
    color: Color | None = None
    isSubtle: bool | None = None
    wrap: bool | None = None
    spacing: Spacing | None = None
    maxLines: int | None = None


class Fact(_Strict):
    title: str
    value: str


class FactSet(_Strict):
    type: Literal["FactSet"] = "FactSet"
    facts: list[Fact]
    spacing: Spacing | None = None


class ActionOpenUrl(_Strict):
    type: Literal["Action.OpenUrl"] = "Action.OpenUrl"
    title: str | None = None
    url: str


class Column(_Strict):
    type: Literal["Column"] = "Column"
    width: str | None = None
    items: list[Element]
    verticalContentAlignment: Literal["Top", "Center", "Bottom"] | None = None


class ColumnSet(_Strict):
    type: Literal["ColumnSet"] = "ColumnSet"
    columns: list[Column]
    spacing: Spacing | None = None


class Container(_Strict):
    type: Literal["Container"] = "Container"
    items: list[Element]
    style: ContainerStyle | None = None
    separator: bool | None = None
    spacing: Spacing | None = None
    selectAction: ActionOpenUrl | None = None


Element = Annotated[TextBlock | FactSet | ColumnSet | Container, Field(discriminator="type")]


class AdaptiveCard(_Strict):
    schema_: str = Field(SCHEMA_URL, alias="$schema")
    type: Literal["AdaptiveCard"] = "AdaptiveCard"
    version: Literal["1.4"] = CARD_VERSION
    body: list[Element]
    actions: list[ActionOpenUrl] = Field(default_factory=list)
    lang: str | None = "fr"


Column.model_rebuild()
Container.model_rebuild()

BAND_COLOR: dict[str, Color] = {"GO": "Good", "REVIEW": "Warning", "NO-GO": "Attention"}


def build(d: Digest) -> dict[str, Any]:
    body: list[Any] = [
        TextBlock(
            text="Avant-Offre — sélection de la semaine", size="Large", weight="Bolder", wrap=True
        ),
        TextBlock(
            text=f"{d.company_name} · semaine du {d.week_start:%d/%m/%Y}",
            isSubtle=True,
            wrap=True,
            spacing="None",
        ),
        FactSet(
            facts=[
                Fact(title="Avis éligibles", value=str(d.counts.eligible)),
                Fact(
                    title=f"GO / À étudier / NO-GO (parmi les {d.counts.scored} premiers)",
                    value=f"{d.counts.go} / {d.counts.review} / {d.counts.no_go}",
                ),
                Fact(title="Avis exclus", value=str(d.counts.excluded)),
            ]
        ),
    ]
    for item in d.items:
        deadline = f"{item.deadline_on:%d/%m/%Y}" if item.deadline_on else "inconnue"
        body.append(
            Container(
                separator=True,
                spacing="Medium",
                selectAction=ActionOpenUrl(title="Ouvrir", url=item.link),
                items=[
                    ColumnSet(
                        columns=[
                            Column(
                                width="auto",
                                verticalContentAlignment="Center",
                                items=[
                                    TextBlock(
                                        text=item.band or "—",
                                        weight="Bolder",
                                        color=BAND_COLOR.get(item.band or "", "Default"),
                                    ),
                                ],
                            ),
                            Column(
                                width="stretch",
                                items=[
                                    TextBlock(
                                        text=item.objet or item.notice_id,
                                        weight="Bolder",
                                        wrap=True,
                                        maxLines=2,
                                    ),
                                    TextBlock(
                                        text=f"{item.buyer_name or '—'} · limite {deadline}",
                                        isSubtle=True,
                                        wrap=True,
                                        spacing="None",
                                    ),
                                ],
                            ),
                        ]
                    )
                ],
            )
        )
    card = AdaptiveCard(
        body=body,
        actions=[ActionOpenUrl(title="Voir toute la sélection", url=d.shortlist_link)],
    )
    return card.model_dump(by_alias=True, exclude_none=True)


def teams_message(card: dict[str, Any]) -> dict[str, Any]:
    """Envelope for a Teams Workflows webhook (Power Automate can post the card directly)."""
    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }
