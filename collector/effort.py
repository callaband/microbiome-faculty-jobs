"""Find the stated effort split (research / teaching / extension / service / clinical)
and teaching load in posting text.

Examples it understands:
  "60% research and 40% teaching"           "research (70%), teaching (30%)"
  "a 75/25 research/teaching appointment"     "50% Research, 30% Teaching, 20% Extension"
  "teaching load of two courses per year"     "a 2-2 teaching load"   "3/3 load"
"""

from __future__ import annotations

import re

from .text import sentences

AREAS = {
    "research": r"research",
    "teaching": r"teaching|instruction(?:al)?|education",
    "extension": r"extension|outreach|engagement",
    "service": r"service|administration|administrative",
    "clinical": r"clinical|patient care",
}
ORDER = ["research", "teaching", "extension", "clinical", "service"]
_AREA_RX = "|".join(f"(?P<{k}>{v})" for k, v in AREAS.items())

_PCT = r"(\d{1,3}(?:\.\d)?)\s*(?:%|percent\b)"
# "60% research", "60 percent of time devoted to research", "60% effort in teaching"
_NUM_FIRST = re.compile(
    _PCT + r"\s*(?:(?:of|time|effort|appointment|fte|assignment|is|will be|devoted|dedicated|allocated|"
    r"assigned|to|for|in|on|toward|towards|an?|the|their|\(|\))\s*){0,6}(" + "|".join(AREAS.values()) + r")",
    re.I,
)
# "research (60%)", "research: 60%", "research - 60%", "research effort of 60%"
_AREA_FIRST = re.compile(
    r"\b(" + "|".join(AREAS.values()) + r")\b\s*(?:effort|time|responsibilit(?:y|ies)|appointment)?\s*"
    r"(?:\(|:|–|-|—|of|at|=)?\s*" + _PCT,
    re.I,
)
# "75/25 research/teaching", "70:30 research and teaching", "a 60-40 research-teaching split"
_RATIO = re.compile(
    r"\b(\d{1,3})\s*[/:\-–]\s*(\d{1,3})(?:\s*[/:\-–]\s*(\d{1,3}))?\s*(?:%\s*)?(?:split\s+)?(?:between\s+)?"
    r"(" + "|".join(AREAS.values()) + r")\s*(?:/|and|-|–|,)\s*(" + "|".join(AREAS.values()) + r")"
    r"(?:\s*(?:/|and|-|–|,)\s*(" + "|".join(AREAS.values()) + r"))?",
    re.I,
)
_LOAD = re.compile(
    r"\b(\d)\s*[-/:]\s*(\d)(?:\s*[-/:]\s*(\d))?\s+(?:teaching|course)\s+load\b"
    r"|\b(?:teaching|course)\s+load\s+(?:of|is|will be)?\s*(?:a\s+)?(\d)\s*[-/:]\s*(\d)\b"
    r"|\b(?:teaching|course)\s+load\s+(?:of|is|will be|will include|includes|consists of)\s+((?:one|two|three|four|five|six|\d)\s+"
    r"(?:\w+\s+){0,3}?(?:courses?|classes|sections|lectures)(?:\s+(?:per|each|a)\s+(?:semester|year|term|quarter|academic year))?)",
    re.I,
)


_CONTEXT = re.compile(r"effort|appointment|\btime\b|\bfte\b|responsibilit|devot|dedicat|assignment|allocat|distribution|split",
                      re.I)


def _area(word: str) -> str | None:
    for key, rx in AREAS.items():
        if re.fullmatch(rx, word.strip(), re.I):
            return key
    return None


def find_effort(text: str) -> dict:
    """Returns {"split": {"research": 60, "teaching": 40}, "label": "...", "text": evidence,
    "teaching_load": "2-2"} — empty values when the posting doesn't say."""
    split: dict[str, float] = {}
    evidence = ""
    for sent in sentences(text):
        if len(sent) > 700 or not re.search(r"\d", sent):
            continue
        found: dict[str, float] = {}
        for m in _RATIO.finditer(sent):
            nums = [m.group(i) for i in (1, 2, 3) if m.group(i)]
            areas = [_area(m.group(i)) for i in (4, 5, 6) if m.group(i)]
            if len(nums) == len(areas) and abs(sum(map(float, nums)) - 100) <= 1:
                for n, a in zip(nums, areas):
                    if a:
                        found.setdefault(a, float(n))
        for m in _NUM_FIRST.finditer(sent):
            a = _area(m.group(2))
            if a:
                found.setdefault(a, float(m.group(1)))
        for m in _AREA_FIRST.finditer(sent):
            a = _area(m.group(1))
            if a:
                found.setdefault(a, float(m.group(2)))
        found = {a: v for a, v in found.items() if 0 < v <= 100}
        # A real split names research or teaching, doesn't exceed 100%, and either gives two
        # areas or is clearly about the appointment ("top 10% for research funding" is not).
        if found and len(found) == 1 and not _CONTEXT.search(sent):
            continue
        if found and ("research" in found or "teaching" in found) and sum(found.values()) <= 101:
            if len(found) > len(split):
                split, evidence = found, sent
    load = ""
    m = _LOAD.search(text)
    if m:
        if m.group(1):
            load = "-".join(g for g in (m.group(1), m.group(2), m.group(3)) if g)
        elif m.group(4):
            load = f"{m.group(4)}-{m.group(5)}"
        elif m.group(6):
            load = m.group(6).lower()
    label = " · ".join(f"{_fmt(split[a])}% {a}" for a in ORDER if a in split)
    return {
        "split": {a: _num(split[a]) for a in ORDER if a in split},
        "label": label,
        "text": _short(evidence),
        "teaching_load": load,
        "focus": _focus(split),
    }


def _focus(split: dict) -> str:
    r, t = split.get("research"), split.get("teaching")
    if r is None and t is None:
        return "unstated"
    if r is not None and r >= 60:
        return "research"
    if t is not None and t >= 60:
        return "teaching"
    if (r or 0) + (t or 0) < 50:
        return "other"  # mostly extension / clinical
    return "balanced"


def _num(v: float):
    return int(v) if v == int(v) else v


def _fmt(v: float) -> str:
    return str(_num(v))


def _short(s: str, limit: int = 260) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"
