"""Find review-start dates, application deadlines and 'open until filled' in posting text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from dateutil import parser as dparser

from .text import sentences

_MONTH = (
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_ORD = r"(?:st|nd|rd|th)?"
DATE_RE = re.compile(
    rf"""(
        {_MONTH}\s+\d{{1,2}}{_ORD},?\s+\d{{4}}        # November 15, 2026
      | \d{{1,2}}{_ORD}\s+(?:of\s+)?{_MONTH},?\s+\d{{4}}  # 15 November 2026
      | \d{{4}}-\d{{1,2}}-\d{{1,2}}                 # 2026-11-15
      | \d{{1,2}}/\d{{1,2}}/\d{{2,4}}                # 11/15/2026
      | {_MONTH}\s+\d{{1,2}}{_ORD}(?![\d,]*\s*\d{{4}}) # November 15 (no year)
      | \d{{1,2}}{_ORD}\s+(?:of\s+)?{_MONTH}(?!,?\s*\d{{4}}) # 15 November (no year)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

REVIEW_CUES = re.compile(
    r"review (?:of (?:the )?(?:applications?|applicants|candidates|materials|files)\s+)?(?:will\s+|is\s+expected\s+to\s+)?(?:begin|start|commence)s?"
    r"|(?:begin|start|commence)\s+(?:the\s+)?review(?:ing)?"
    r"|(?:first|initial|priority)\s+(?:review|screening|consideration|deadline|date)"
    r"|full\s+consideration"
    r"|screening (?:of applications )?(?:will )?(?:begin|start)s?"
    r"|evaluation of applications (?:will )?(?:begin|start)s?"
    r"|applications? (?:will be )?reviewed (?:starting|beginning)",
    re.IGNORECASE,
)

DEADLINE_CUES = re.compile(
    r"deadline|closing date|close[sd]? on|closes|applications? (?:are |is )?due|due (?:date|by)"
    r"|no later than|must be (?:received|submitted)|apply by|submit(?:ted)? by|last date",
    re.IGNORECASE,
)

UNTIL_FILLED = re.compile(
    r"until (?:the )?(?:position|positions|post|search|vacancy|role|job) (?:is |are |has been )?(?:filled|closed)|until filled",
    re.IGNORECASE,
)


@dataclass
class DateFindings:
    review_date: date | None = None
    review_text: str = ""
    deadline: date | None = None
    deadline_text: str = ""
    until_filled: bool = False
    all_review_dates: list[date] = field(default_factory=list)


def _parse_one(raw: str, anchor: date) -> date | None:
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw.strip().rstrip("."), flags=re.I)
    raw = raw.replace(" of ", " ")
    has_year = bool(re.search(r"\d{4}|\d{1,2}/\d{1,2}/\d{2}", raw))
    try:
        dt = dparser.parse(raw, default=datetime(anchor.year, 1, 1), fuzzy=False, dayfirst=False)
    except (ValueError, OverflowError):
        return None
    d = dt.date()
    if not has_year:
        # "November 15" with no year: take the first such date not long before the anchor.
        if d < anchor - timedelta(days=45):
            d = d.replace(year=d.year + 1)
    if not (anchor.year - 2 <= d.year <= anchor.year + 3):
        return None
    return d


def _short(s: str, limit: int = 260) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def find_dates(text: str, anchor: date) -> DateFindings:
    """`anchor` is the date the posting was published (or first seen)."""
    f = DateFindings()
    f.until_filled = bool(UNTIL_FILLED.search(text))
    review_hits: list[tuple[date, str]] = []
    deadline_hits: list[tuple[date, str]] = []
    for sent in sentences(text):
        if len(sent) > 600:
            continue  # boilerplate paragraphs, not date statements
        found = [_parse_one(m.group(0), anchor) for m in DATE_RE.finditer(sent)]
        found = [d for d in found if d]
        if not found:
            continue
        if REVIEW_CUES.search(sent):
            review_hits += [(d, sent) for d in found]
        elif DEADLINE_CUES.search(sent):
            deadline_hits += [(d, sent) for d in found]
    if review_hits:
        review_hits.sort()
        f.review_date, f.review_text = review_hits[0][0], _short(review_hits[0][1])
        f.all_review_dates = sorted({d for d, _ in review_hits})
    if deadline_hits:
        deadline_hits.sort()
        f.deadline, f.deadline_text = deadline_hits[-1][0], _short(deadline_hits[-1][1])
    return f


def parse_any(raw: str | None) -> date | None:
    """Parse a structured date field (ISO timestamp, RFC 822, 11/23/2026...)."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw.lower() in {"open until filled", "until filled", "n/a", "none"}:
        return None
    try:
        return dparser.parse(raw, fuzzy=True, ignoretz=True).date()
    except (ValueError, OverflowError):
        return None
