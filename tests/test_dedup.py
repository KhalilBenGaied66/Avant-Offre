"""Step 2 — notice deduplication rules."""

from __future__ import annotations

from datetime import date

from avant_offre.transform.dedup import NoticeKey, find_duplicates

D = date(2026, 11, 20)


def test_same_notice_id() -> None:
    a = NoticeKey("26-1", "Ville", "Nettoyage", D, date(2026, 10, 1))
    dups = find_duplicates([a, a])
    assert [(d.notice_id, d.reason) for d in dups] == [("26-1", "same_notice_id")]


def test_same_procedure_keeps_latest() -> None:
    old = NoticeKey("26-1", "Ville", "Nettoyage", D, date(2026, 10, 1), folder_id="P-9")
    fix = NoticeKey(
        "26-2", "Ville", "Nettoyage (rectificatif)", D, date(2026, 10, 5), folder_id="P-9"
    )
    dups = find_duplicates([old, fix])
    assert [(d.notice_id, d.kept_id, d.reason) for d in dups] == [
        ("26-1", "26-2", "same_procedure_id")
    ]


def test_buyer_title_deadline_rule() -> None:
    a = NoticeKey(
        "A", "VILLE DE TESTVILLE", "Nettoyage des locaux administratifs", D, date(2026, 10, 1)
    )
    b = NoticeKey(
        "B", "Ville de Testville", "nettoyage des locaux administratifs.", D, date(2026, 10, 2)
    )
    dups = find_duplicates([a, b], threshold=92)
    assert [(d.notice_id, d.kept_id, d.reason) for d in dups] == [
        ("A", "B", "buyer_title_deadline")
    ]


def test_rule_requires_same_deadline_and_similar_title() -> None:
    a = NoticeKey("A", "Ville", "Nettoyage des locaux", D, date(2026, 10, 1))
    other_deadline = NoticeKey(
        "B", "Ville", "Nettoyage des locaux", date(2026, 12, 1), date(2026, 10, 2)
    )
    other_title = NoticeKey("C", "Ville", "Travaux de voirie", D, date(2026, 10, 3))
    assert find_duplicates([a, other_deadline, other_title], threshold=92) == []
