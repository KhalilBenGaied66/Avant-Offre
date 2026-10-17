"""Numeric and citation verifier for briefs. No AI.

1. Split the brief into sections (``## Heading``) and sentences.
2. Parse numbers in French formats: ``1 234,56 €``, ``30 %``, ``45 k€``, ``1,2 M€``, dates
   ``15/11/2026`` or ``15 novembre 2026``, with regular, no-break or narrow no-break spaces.
   Percentile labels (P10…P90) and citations ``[F3]`` are not numbers.
3. Every number must match a cited fact of the same kind: equal to the fact's display, or equal
   to the fact's value at the precision written in the brief. Plain numbers may also appear
   inside the display of a cited text fact.
4. A sentence with a number must cite at least one fact holding it; unknown fact ids fail.
A failing sentence is removed, never rewritten. The brief falls back to the deterministic
template when the recommendation sentence fails (or does not repeat the scorecard band), when
a section is missing, when it is too long, or when more than ``brief.max_removed`` sentences fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from avant_offre.brief.facts import BriefFacts, Fact

SECTIONS = ("Recommandation", "Pourquoi", "Concurrence", "Prix", "Points à vérifier")
SPACE = "[   ]"
MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "décembre": 12,
}  # fmt: skip

CITATION = re.compile(r"\[(F\d+(?:\s*[,;]\s*F\d+)*)\]")
PERCENTILE_LABEL = re.compile(r"\bP\d{2}\b")
NUM = rf"(\d{{1,3}}(?:{SPACE}\d{{3}})+|\d+)(?:,(\d+))?"
DATE_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DATE_WORDS = re.compile(
    r"\b(\d{1,2})(?:er)?" + SPACE + r"+(" + "|".join(MONTHS) + r")" + SPACE + r"+(\d{4})\b",
    re.IGNORECASE,
)
EUR = re.compile(NUM + SPACE + r"*(k€|M€|€|keur|meur|euros?)", re.IGNORECASE)
PCT = re.compile(NUM + SPACE + r"*(%|pour" + SPACE + "?cent)", re.IGNORECASE)
PLAIN = re.compile(r"(?<![\w,])" + NUM + r"(?![\w])")
BANDS = {
    "GO": re.compile(r"(?<![-\w])GO\b"),
    "REVIEW": re.compile(r"\bREVIEW\b"),
    "NO-GO": re.compile(r"\bNO-GO\b"),
}
KIND_OF_UNIT = {
    "EUR": "eur",
    "%": "pct",
    "date": "date",
    "count": "plain",
    "days": "plain",
    "score": "plain",
    "code": "plain",
}


@dataclass(frozen=True)
class Number:
    kind: str  # eur | pct | date | plain
    value: float
    precision: float  # half of the last written unit, in the value's unit
    raw: str


def _to_float(int_part: str, dec_part: str | None) -> tuple[float, int]:
    digits = re.sub(SPACE, "", int_part)
    decimals = len(dec_part) if dec_part else 0
    return float(f"{digits}.{dec_part}" if dec_part else digits), decimals


def _ordinal(y: int, m: int, d: int) -> float:
    """Date as an ordinal; an impossible date never matches a fact (-1)."""
    try:
        return float(date(y, m, d).toordinal())
    except ValueError:
        return -1.0


def parse_numbers(sentence: str) -> list[Number]:
    """Numbers of a sentence, citations and percentile labels removed."""
    text = CITATION.sub(" ", sentence)
    text = PERCENTILE_LABEL.sub(" ", text)
    out: list[Number] = []

    def blank(m: re.Match[str]) -> str:
        return " " * (m.end() - m.start())

    for m in DATE_NUMERIC.finditer(text):
        out.append(
            Number(
                "date", _ordinal(int(m.group(3)), int(m.group(2)), int(m.group(1))), 0.5, m.group(0)
            )
        )
    text = DATE_NUMERIC.sub(blank, text)
    for m in DATE_WORDS.finditer(text):
        month = MONTHS[m.group(2).lower()]
        out.append(
            Number("date", _ordinal(int(m.group(3)), month, int(m.group(1))), 0.5, m.group(0))
        )
    text = DATE_WORDS.sub(blank, text)
    for m in EUR.finditer(text):
        v, decimals = _to_float(m.group(1), m.group(2))
        unit = m.group(3).lower()
        scale = 1e6 if unit in ("m€", "meur") else 1e3 if unit in ("k€", "keur") else 1.0
        out.append(Number("eur", v * scale, 0.5 * scale * 10**-decimals, m.group(0)))
    text = EUR.sub(blank, text)
    for m in PCT.finditer(text):
        v, decimals = _to_float(m.group(1), m.group(2))
        out.append(Number("pct", v, 0.5 * 10**-decimals, m.group(0)))
    text = PCT.sub(blank, text)
    for m in PLAIN.finditer(text):
        v, decimals = _to_float(m.group(1), m.group(2))
        out.append(Number("plain", v, 0.5 * 10**-decimals, m.group(0)))
    return out


def _display_numbers(fact: Fact) -> list[Number]:
    return parse_numbers(fact.display)


def _fact_number(fact: Fact) -> Number | None:
    kind = KIND_OF_UNIT.get(fact.unit)
    if kind is None or fact.value is None:
        return None
    if kind == "date":
        return Number("date", float(date.fromisoformat(str(fact.value)).toordinal()), 0.5, "")
    try:
        return Number(kind, float(fact.value), 0.0, "")
    except (TypeError, ValueError):
        return None


def number_matches(n: Number, fact: Fact) -> bool:
    eps = 1e-9
    if fact.unit in ("text", "band"):
        return n.kind in ("plain", "date") and any(
            d.kind == n.kind and abs(d.value - n.value) <= eps for d in _display_numbers(fact)
        )
    fn = _fact_number(fact)
    if fn is None or fn.kind != n.kind:
        return False
    if any(d.kind == n.kind and abs(d.value - n.value) <= eps for d in _display_numbers(fact)):
        return True
    return abs(fn.value - n.value) <= n.precision + eps * max(1.0, abs(fn.value))


# Why sentences fail, without the sentence-specific details (evaluation report).
REASON_KINDS = {
    "unknown citation": "cites a fact id that does not exist",
    "number without citation": "number without citation",
    "matches no cited fact": "number matches no cited fact",
    "grid says": "recommendation contradicts the grid",
}


def reason_kind(reason: str) -> str:
    return next((kind for key, kind in REASON_KINDS.items() if key in reason), reason)


@dataclass
class Removed:
    section: str
    sentence: str
    reason: str


@dataclass
class Verification:
    text: str
    removed: list[Removed] = field(default_factory=list)
    fallback: bool = False
    fallback_reason: str | None = None
    words: int = 0


def split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s*(.+?)\s*:?\s*$", line) or re.match(
            r"^\*\*(.+?)\*\*\s*:?\s*$", line
        )
        if heading and heading.group(1).strip() in SECTIONS:
            current = []
            sections.append((heading.group(1).strip(), current))
            continue
        if current is None:
            current = []
            sections.append(("", current))
        body = re.sub(r"^[-*•]\s+", "", line)
        # Quoted titles (« … ») may contain periods: protect them from the sentence split.
        body = re.sub(r"«[^»]*»", lambda m: m.group(0).replace(".", "\x00"), body)
        current.extend(
            s.replace("\x00", ".") for s in re.split(r"(?<=[.!?])\s+(?=\S)", body) if s.strip()
        )
    return sections


def check_sentence(sentence: str, facts: dict[str, Fact]) -> str | None:
    """Reason the sentence fails, or None."""
    cited: list[str] = []
    for group in CITATION.findall(sentence):
        cited += [c.strip() for c in re.split(r"[,;]", group)]
    unknown = [c for c in cited if c not in facts]
    if unknown:
        return f"unknown citation {unknown}"
    numbers = parse_numbers(sentence)
    if numbers and not cited:
        return "number without citation"
    for n in numbers:
        if not any(number_matches(n, facts[c]) for c in cited):
            return f"number {n.raw!r} matches no cited fact"
    return None


def numbers_among_facts(sentence: str, facts: BriefFacts) -> bool:
    """Every number of the sentence equals some fact, citations ignored. For a removed sentence,
    True means a citation error (missing or wrong), False a number the facts do not hold."""
    return all(any(number_matches(n, f) for f in facts.facts) for n in parse_numbers(sentence))


def verify(text: str, facts: BriefFacts, *, max_removed: int, max_words: int) -> Verification:
    by_id = facts.by_id()
    sections = split_sections(text)
    names = [name for name, _ in sections]
    missing = [s for s in SECTIONS if s not in names]
    result = Verification(text=text, words=len(re.findall(r"\w+", CITATION.sub("", text))))
    if missing:
        return Verification(
            text, fallback=True, fallback_reason=f"missing sections {missing}", words=result.words
        )
    if result.words > max_words:
        return Verification(
            text,
            fallback=True,
            fallback_reason=f"{result.words} words > {max_words}",
            words=result.words,
        )
    kept_lines: list[str] = []
    for name, sentences in sections:
        if not name:
            continue  # text outside the five sections is dropped
        kept: list[str] = []
        for i, sentence in enumerate(sentences):
            reason = check_sentence(sentence, by_id)
            if name == "Recommandation" and i == 0:
                bands = [b for b, rx in BANDS.items() if rx.search(sentence)]
                if bands != [facts.band]:
                    reason = (
                        reason
                        or f"recommendation states {bands or 'no band'}, grid says {facts.band}"
                    )
                if reason:
                    result.removed.append(Removed(name, sentence, reason))
                    result.fallback = True
                    result.fallback_reason = f"recommendation failed: {reason}"
                    return result
            if reason:
                result.removed.append(Removed(name, sentence, reason))
            else:
                kept.append(sentence)
        kept_lines += [
            f"## {name}",
            *(f"- {s}" if name != "Recommandation" else s for s in kept),
            "",
        ]
    if len(result.removed) > max_removed:
        result.fallback = True
        result.fallback_reason = f"{len(result.removed)} sentences removed > {max_removed}"
    result.text = "\n".join(kept_lines).strip() + "\n"
    return result
