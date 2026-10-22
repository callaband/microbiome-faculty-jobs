"""Text helpers."""

from __future__ import annotations

import html
import re
import unicodedata

from bs4 import BeautifulSoup

_WS = re.compile(r"[ \t\r\f\v ]+")


def html_to_text(markup: str | None) -> str:
    """HTML -> readable plain text, keeping paragraph breaks as newlines."""
    if not markup:
        return ""
    # Some feeds double-escape HTML.
    if "&lt;" in markup and "<" not in markup:
        markup = html.unescape(markup)
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        block.insert_before("\n")
        block.insert_after("\n")
    text = soup.get_text()
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def clean(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", html.unescape(s)).strip()


def norm_tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    stop = {"of", "in", "and", "the", "for", "a", "an", "at", "or", "to", "position", "faculty", "department"}
    return {t for t in s.split() if t and t not in stop}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def excerpt(text: str, limit: int = 420) -> str:
    """A short opening excerpt (we link to the full posting rather than copy it)."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    cut = cut[: cut.rfind(" ")] if " " in cut else cut
    return cut.rstrip(",;:") + "…"


def sentences(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p and p.strip()]
