from datetime import date

import pytest

from collector.classify import domains, rank_label, ranks, relevance, tenure, tenure_label
from collector.dates import find_dates
from collector.regions import parse_place


@pytest.mark.parametrize("title,expected", [
    ("Assistant Professor of Plant Pathology", "Assistant"),
    ("Associate Professor Or Assistant Professor in Clinical Microbiology", "Assistant / Associate"),
    ("Microbiology & Immunology/HCI Asst, Assoc, Professor - Rank Dependent on Qualifications", "Open rank"),
    ("Assistant/Associate/Full Professor of Animal Science", "Open rank"),
    ("Open Rank Faculty Position in Microbiome Science", "Open rank"),
    ("Professor of Microbiology", "Full"),
    ("Senior Lecturer in Environmental Microbiology", "Lecturer / Reader"),
    ("Group Leader - Host-Microbe Interactions", "Investigator / Group leader"),
])
def test_rank(title, expected):
    assert rank_label(ranks(title, "")) == expected


def test_rank_from_description():
    assert rank_label(ranks("Faculty Position in Gut Microbiome",
                            "We invite applications at the rank of Associate Professor.")) == "Associate"


@pytest.mark.parametrize("text,expected", [
    ("a tenure-track Assistant Professor position", "Tenure-track"),
    ("This is a non-tenure-track position.", "Non-tenure-track"),
    ("considered for a tenure-track or tenured appointment", "Tenure-track or Tenured"),
    ("This is a permanent position.", "Permanent / continuing"),
    ("Nothing here.", "Tenure not stated"),
])
def test_tenure(text, expected):
    assert tenure_label(tenure("Assistant Professor", text)) == expected


def test_research_professor_is_non_tenure_track():
    assert "non-tenure-track" in tenure("Research Assistant Professor", "Our university has a tenure system.")


def test_relevance():
    assert not relevance("Postdoctoral Associate", "gut microbiome").keep
    assert not relevance("Assistant Professor of Biology", "cell biology").keep
    assert relevance("Assistant Professor of Biology", "the gut microbiota of fish").keep


def test_domains():
    d = domains("Assistant Professor", "microbiome of farmed fish in aquaculture and marine coral reefs")
    assert "aquaculture" in d and "ocean" in d
    assert domains("Assistant Professor", "microbial ecology") == ["fundamental"]


def test_dates():
    text = ("We invite applications.\nReview of applications will begin November 1, 2026 and continue "
            "until the position is filled. The deadline is January 15, 2027.")
    f = find_dates(text, date(2026, 10, 1))
    assert f.review_date == date(2026, 11, 1)
    assert f.deadline == date(2027, 1, 15)
    assert f.until_filled


def test_dates_full_consideration_before_cue():
    f = find_dates("Applications received by 30 November 2026 will receive full consideration.", date(2026, 9, 1))
    assert f.review_date == date(2026, 11, 30)


def test_dates_without_year():
    f = find_dates("Screening begins Dec. 5.", date(2026, 10, 1))
    assert f.review_date == date(2026, 12, 5)


@pytest.mark.parametrize("raw,city,cc", [
    ("Wilmington, NC", "Wilmington", "US"),
    ("Doha, Qatar", "Doha", "QA"),
    ("Luxembourg (LU)", "", "LU"),
    ("Salt Lake City, Utah", "Salt Lake City", "US"),
    ("Montréal, Quebec, Canada", "Montréal", "CA"),
])
def test_parse_place(raw, city, cc):
    p = parse_place(raw)
    assert p["city"] == city and p["country_code"] == cc
