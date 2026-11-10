"""Decide whether a posting is a microbiome faculty job, and label rank, tenure and domains."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from . import CONFIG_DIR


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    with open(CONFIG_DIR / "taxonomy.yaml", encoding="utf-8") as fh:
        tx = yaml.safe_load(fh)
    comp = lambda pats: [re.compile(p, re.IGNORECASE) for p in pats]  # noqa: E731
    tx["_micro"] = comp(tx["microbiome_terms"])
    tx["_faculty"] = comp(tx["faculty_title_patterns"])
    tx["_exclude"] = comp(tx["exclude_title_patterns"])
    tx["_domains"] = {k: comp(v["patterns"]) for k, v in tx["domains"].items()}
    return tx


# --------------------------------------------------------------------------- relevance
@dataclass
class Relevance:
    keep: bool
    reason: str
    terms: list[str] = field(default_factory=list)


def is_faculty_title(title: str, board_job_type: str = "") -> tuple[bool, str]:
    tx = taxonomy()
    for rx in tx["_exclude"]:
        if rx.search(title):
            return False, f"title looks like a non-faculty role ({rx.pattern})"
    if any(rx.search(title) for rx in tx["_faculty"]):
        return True, ""
    if re.search(r"\bfaculty\b", board_job_type, re.I):
        return True, ""
    return False, "title is not a faculty rank"


def microbiome_terms(text: str) -> list[str]:
    tx = taxonomy()
    hits = []
    for rx in tx["_micro"]:
        m = rx.search(text)
        if m:
            hits.append(m.group(0).lower())
    return sorted(set(hits))


def relevance(title: str, description: str, board_job_type: str = "", employment: str = "") -> Relevance:
    ok, why = is_faculty_title(title, board_job_type)
    if not ok:
        return Relevance(False, why)
    if re.search(r"part[\s\-]?time", employment or "", re.I) and not re.search(r"full", employment or "", re.I):
        return Relevance(False, "part-time")
    terms = microbiome_terms(f"{title}\n{description}")
    if not terms:
        return Relevance(False, "no microbiome terms in the posting")
    return Relevance(True, "", terms)


# --------------------------------------------------------------------------- domains
def domains(title: str, description: str) -> list[str]:
    tx = taxonomy()
    text = f"{title}\n{title}\n{description}"  # title counts double
    mins = tx.get("min_hits", {})
    out = []
    for key, pats in tx["_domains"].items():
        hits = sum(1 for rx in pats if rx.search(text))
        need = mins.get(key, mins.get("default", 1))
        # A domain named in the title always counts.
        if hits >= need or (hits and any(rx.search(title) for rx in pats)):
            out.append(key)
    specific = [d for d in out if d != "fundamental"]
    return specific or (["fundamental"] if "fundamental" in out else ["fundamental"])


# --------------------------------------------------------------------------- method flags
@lru_cache(maxsize=1)
def _method_rules() -> dict:
    tx = taxonomy()
    rules = {}
    for key, spec in (tx.get("method_flags") or {}).items():
        rules[key] = {
            "label": spec.get("label", key),
            "patterns": [re.compile(p, re.I) for p in spec.get("patterns", [])],
            "layers": {name: re.compile(p, re.I) for name, p in (spec.get("layers") or {}).items()},
        }
    return rules


def _evidence(text: str, rx: re.Pattern) -> str:
    m = rx.search(text)
    if not m:
        return ""
    start = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start()) + 1, 0)
    end_candidates = [i for i in (text.find("\n", m.end()), text.find(". ", m.end())) if i != -1]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return snippet if len(snippet) <= 240 else snippet[:239].rstrip() + "…"


def methods(title: str, description: str) -> dict:
    """Method flags for a posting: {"flags": [...], "omics_layers": [...], "evidence": {flag: sentence}}."""
    text = f"{title}\n{description}"
    out = {"flags": [], "omics_layers": [], "evidence": {}}
    for key, rule in _method_rules().items():
        hit = next((rx for rx in rule["patterns"] if rx.search(text)), None)
        layers = [name for name, rx in rule["layers"].items() if rx.search(text)]
        if rule["layers"]:
            out["omics_layers"] = layers
        if hit is None and len(layers) >= 2:
            hit = rule["layers"][layers[0]]
            out["evidence"][key] = "Mentions " + ", ".join(layers)
        elif hit is not None:
            out["evidence"][key] = _evidence(text, hit)
        if hit is not None:
            out["flags"].append(key)
    return out


def method_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in _method_rules().items()}


# --------------------------------------------------------------------------- rank
RANKS = ["assistant", "associate", "full", "open", "lecturer", "investigator"]
RANK_LABELS = {
    "assistant": "Assistant",
    "associate": "Associate",
    "full": "Full",
    "open": "Open rank",
    "lecturer": "Lecturer / Reader",
    "investigator": "Investigator / Group leader",
    "unspecified": "Rank not stated",
}

_OPEN = re.compile(
    r"\bopen[\s\-]rank|\b(?:any|all) (?:academic )?(?:ranks?|levels?)\b|\brank (?:is )?open\b|\bat any level\b"
    r"|\brank (?:will be )?(?:commensurate|dependent|based) (?:with|on|upon)\b|\brank and salary (?:are )?commensurate\b"
    r"|\brank (?:to be )?determined\b",
    re.IGNORECASE,
)
_PROF = re.compile(r"\bprof(?:essor\w*|\.)", re.I)
_ASSIST = re.compile(r"\b(?:assistant|asst)\b", re.I)
_ASSOC = re.compile(r"\b(?:associate|assoc)\b", re.I)
_FULL = re.compile(r"\bfull\b|\b(?:w3|distinguished|endowed|named)\s+(?:professor|chair)", re.I)
# "Professor" on its own (not "Assistant Professor", "Research Professor", ...).
_BARE_PROF = re.compile(
    r"(?<![a-z])(?<!assistant )(?<!associate )(?<!adjunct )(?<!research )(?<!clinical )(?<!teaching )"
    r"(?<!visiting )(?<!asst\. )(?<!assoc\. )(?<!asst )(?<!assoc )(?<!full )professor\b(?!\s+of\s+(?:practice|instruction|teaching))",
    re.I,
)
_LECT = re.compile(r"\b(?:senior\s+)?lecturer\b|\breader\b", re.I)
_INVEST = re.compile(
    r"\bgroup leader\b|\bprincipal investigator\b|\binvestigator\b|\bjunior research group\b|\b(?:assistant|associate|full) member\b",
    re.I,
)
_DESC_RANK = {
    "assistant": re.compile(r"\b(?:assistant|asst\.?)\s+professor", re.I),
    "associate": re.compile(r"\b(?:associate|assoc\.?)\s+professor", re.I),
    "full": re.compile(r"\bfull\s+professor|\brank of (?:full )?professor\b|\b(?:associate|assistant) or (?:full )?professor\b", re.I),
}


# European titles (German, Dutch, Nordic, French, Southern European).
_EU_RANK = {
    "assistant": re.compile(r"\bjunior\s?professur\w*|\buniversitair docent\b|助教|助理教授|조교수", re.I),
    "associate": re.compile(
        r"\buniversitair hoofddocent\b|(?<!universitair )(?<!hoofd)\bdocent\b|\bma[iî]tre de conf[ée]rences\b|准教授|副教授|부교수"
        r"|\bprofess(?:eur|ore) associ[ée]\w*|\bprofesor(?:a)? (?:titular|agregad[oa]|associad[oa])\b", re.I),
    "full": re.compile(
        r"\bhoogleraar\b|\bprofesseur des universit\w*|\bprofessore ordinario\b|(?<![准副理])教授(?!会)|(?<![부조])교수"
        r"|\bprofesor(?:a)? catedr[áa]tic[oa]\b", re.I),
    "lecturer": re.compile(r"\b\w*lektor(?:at)?\b|講師|讲师|강사", re.I),
    "investigator": re.compile(
        r"\bcharg[ée]e? de recherche\b|\bdirect(?:eur|rice) de recherche\b|\bnachwuchsgruppenleit\w*", re.I),
}
_PROFESSUR = re.compile(r"\bprofessur\b|\bprofessorship\b", re.I)
# German professorship grades count only on professor posts (a "Group Leader (W2)" is a group leader).
_W_GRADE = {"assistant": re.compile(r"\bW\s?1\b", re.I), "associate": re.compile(r"\bW\s?2\b", re.I),
            "full": re.compile(r"\bW\s?3\b", re.I)}
_ANY_PROF = re.compile(r"profess|\bprof\.", re.I)


def ranks(title: str, description: str) -> list[str]:
    found: set[str] = set()
    t = title
    for key, rx in _EU_RANK.items():
        if rx.search(t):
            found.add(key)
    if _ANY_PROF.search(t) and not _INVEST.search(t):
        for key, rx in _W_GRADE.items():
            if rx.search(t):
                found.add(key)
    # A German "Professur" or a "Professorship" with no grade or level named: a professor post.
    if _PROFESSUR.search(t) and not (found & {"assistant", "associate", "full"}) \
            and not _ASSIST.search(t) and not _ASSOC.search(t):
        found.add("full")
    if _OPEN.search(t):
        found.add("open")
    if _PROF.search(t) or "open" in found:
        if _ASSIST.search(t):
            found.add("assistant")
        if _ASSOC.search(t):
            found.add("associate")
        if _FULL.search(t) or _BARE_PROF.search(t):
            found.add("full")
    if _LECT.search(t):
        found.add("lecturer")
    if _INVEST.search(t) and not (found - {"open"}):
        found.add("investigator")
    if not (found - {"investigator"}):
        # Title says only e.g. "Faculty Position in Microbiome Science":
        # read the rank from the opening of the description.
        head = description[:3000]
        if _OPEN.search(head):
            found.add("open")
        for key, rx in _DESC_RANK.items():
            if rx.search(head):
                found.add(key)
    if {"assistant", "associate", "full"} <= found:
        found.add("open")
    out = [r for r in RANKS if r in found]
    return out or ["unspecified"]


def rank_label(rs: list[str]) -> str:
    if rs == ["unspecified"]:
        return RANK_LABELS["unspecified"]
    if "open" in rs:
        return "Open rank"
    return " / ".join(RANK_LABELS[r] for r in rs)


# --------------------------------------------------------------------------- tenure
_NON_TT = re.compile(
    r"\bnon[\s\-]*tenure[\s\-]*(?:track|eligible|stream|line)?\b|\bnot\s+(?:a\s+)?tenure[\s\-]*(?:track|eligible)\b"
    r"|\bnon[\s\-]?tenured\b|\bteaching[\s\-](?:track|stream)\b|\bteaching (?:assistant |associate )?professor\b"
    r"|\bprofessor of (?:practice|instruction|teaching)\b|\bclinical (?:assistant |associate )?professor\b"
    r"|\bresearch (?:assistant |associate )?professor\b|\bfixed[\s\-]term\b|\bterm[\s\-]limited\b"
    r"|\b(?:one|two|three|1|2|3)[\s\-]year (?:renewable )?(?:appointment|contract|position)\b|\binstructional faculty\b"
    r"|テニュアトラック以外|任期あり|任期付|有期雇用|비정년",
    re.I,
)
_TT = re.compile(r"\btenure[\s\-]*(?:track|stream|eligible|line|system)\b|\btenure[\s\-]accruing\b"
                 r"|テニュアトラック(?!以外)|预聘|長聘|长聘|정년\s?트랙", re.I)
_TENURED = re.compile(
    r"\btenured\b|\bwith tenure\b|\btenure (?:at|upon|on) (?:the )?(?:time of )?(?:hire|appointment)\b|\btenure (?:may|can|will) be (?:granted|considered|available)",
    re.I,
)
_PERMANENT = re.compile(
    r"\bpermanent (?:academic |faculty )?(?:position|post|appointment|contract|role|faculty)\b|\bcontinuing (?:position|appointment|role)\b"
    r"|\bopen[\s\-]ended (?:contract|position|appointment)\b|\bindefinite (?:contract|appointment)\b|\blifetime (?:position|appointment)\b"
    r"|\bunbefristet\w*|\bvaste aanstelling\b|\bvast dienstverband\b|\bpermanent (?:full[\s\-]time )?(?:employment|staff)\b"
    r"|\bcontract type[^.\n]{0,15}:\s*permanent\b|任期なし|任期の定めなし|無期雇用|终身教职|정년\s?보장",
    re.I,
)
TENURE_LABELS = {
    "tenure-track": "Tenure-track",
    "tenured": "Tenured",
    "permanent": "Permanent / continuing",
    "non-tenure-track": "Non-tenure-track",
    "unspecified": "Tenure not stated",
}


def tenure(title: str, description: str) -> list[str]:
    text = f"{title}\n{description}"
    out = []
    non = bool(_NON_TT.search(text))
    scrubbed = _NON_TT.sub(" ", text)
    if _TT.search(scrubbed):
        out.append("tenure-track")
    if _TENURED.search(_NON_TT.sub(" ", scrubbed)):
        out.append("tenured")
    if _PERMANENT.search(text):
        out.append("permanent")
    # A clinical/research/teaching title is non-tenure-track even if the boilerplate
    # mentions the university's tenure system.
    if non and (_NON_TT.search(title) or not out):
        out.append("non-tenure-track")
    return out or ["unspecified"]


def tenure_label(ts: list[str]) -> str:
    if ts == ["unspecified"]:
        return TENURE_LABELS["unspecified"]
    if "non-tenure-track" in ts and len(ts) > 1:
        return "Mixed — see posting"
    return " or ".join(TENURE_LABELS[t] for t in ts)
