"""What kind of institution is hiring?

US institutions are matched to the federal IPEDS directory (U.S. Department of
Education, National Center for Education Statistics), which gives:
  - the Carnegie basic classification (R1, R2, doctoral/professional,
    master's, baccalaureate, special focus, associate's)
  - official flags: HBCU, tribal college, land-grant, grants a medical degree
  - whether it awards the Doctor of Veterinary Medicine (from IPEDS completions)
  - public / private, and campus coordinates
Ivy League and women's / historically women's colleges come from
config/institution_lists.yaml.

The directory is downloaded once and cached in data/institutions.json
(refreshed about once a year).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from datetime import date
from functools import lru_cache

import requests
import yaml

from . import CONFIG_DIR, STATE_DIR
from .http import _user_agent
from .regions import US_STATES

log = logging.getLogger(__name__)
DIRECTORY_FILE = STATE_DIR / "institutions.json"
IPEDS_URL = "https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip"
# Completions by program: used to find institutions that award the DVM
# (CIP 51.2401 Veterinary Medicine, award level 17 = doctor's degree, professional practice).
COMPLETIONS_URL = "https://nces.ed.gov/ipeds/datacenter/data/C{year}_A.zip"
VET_CIP = "51.2401"
REFRESH_DAYS = 300
DIRECTORY_VERSION = 2  # bump to force a re-download when new fields are added

# Carnegie basic classification (2018 and 2021 editions share these codes).
CARNEGIE = {
    15: ("r1", "R1: Doctoral – very high research activity"),
    16: ("r2", "R2: Doctoral – high research activity"),
    17: ("doctoral", "Doctoral/professional university"),
    18: ("masters", "Master's college/university (larger programs)"),
    19: ("masters", "Master's college/university (medium programs)"),
    20: ("masters", "Master's college/university (smaller programs)"),
    21: ("baccalaureate", "Baccalaureate college – arts & sciences"),
    22: ("baccalaureate", "Baccalaureate college – diverse fields"),
    23: ("baccalaureate", "Baccalaureate/associate's college"),
    24: ("special", "Special focus – faith-related"),
    25: ("medical", "Special focus – medical school/center"),
    26: ("special", "Special focus – other health professions"),
    27: ("special", "Special focus – engineering/technology"),
    28: ("special", "Special focus – other technology"),
    29: ("special", "Special focus – business"),
    30: ("special", "Special focus – arts, music & design"),
    31: ("special", "Special focus – law"),
    32: ("special", "Special focus – other"),
    33: ("tribal", "Tribal college/university"),
}
for _c in range(1, 15):
    CARNEGIE[_c] = ("associate", "Associate's / two-year college")

TYPE_LABELS = {
    "r1": "R1",
    "r2": "R2",
    "doctoral": "Doctoral/professional",
    "masters": "PUI – master's",
    "baccalaureate": "PUI – baccalaureate",
    "medical": "Medical school/center",
    "special": "Special-focus institution",
    "associate": "Community/two-year college",
    "ivy": "Ivy League",
    "hbcu": "HBCU",
    "womens": "Women's/historically women's college",
    "tribal": "Tribal college",
    "landgrant": "Land-grant",
    "med_school": "Has a medical school",
    "vet_school": "Has a veterinary school",
    "institute": "Research institute/hospital",
    "international": "Outside the US",
    "unknown": "Type not identified",
}
PUI_TYPES = {"masters", "baccalaureate"}


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[’'`]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(the|at|campus|main)\b", " ", s)
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\buniv\b", "university", s)
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------------------- directory
def _read_zip_csv(session: requests.Session, url: str) -> str | None:
    try:
        r = session.get(url, timeout=180)
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            return None
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        name = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))[-1]  # prefer *_rv.csv
        return zf.read(name).decode("latin-1")
    except (requests.RequestException, zipfile.BadZipFile, IndexError) as exc:
        log.warning("IPEDS %s: %s", url, exc)
        return None


def vet_unitids(raw_csv: str) -> set[str]:
    """Institutions with at least one DVM graduate in an IPEDS completions (C_A) file."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    cols = {c.strip().upper(): c for c in reader.fieldnames or []}
    cip, lvl, tot, uid = (cols.get(k) for k in ("CIPCODE", "AWLEVEL", "CTOTALT", "UNITID"))
    out = set()
    if not (cip and uid):
        return out
    for row in reader:
        if (row.get(cip) or "").strip().strip('"') != VET_CIP:
            continue
        if lvl and (row.get(lvl) or "").strip() not in ("17", "9"):  # 9 = pre-2010 "first-professional"
            continue
        try:
            if tot and int(row.get(tot) or 0) <= 0:
                continue
        except ValueError:
            continue
        out.add((row.get(uid) or "").strip())
    return out


def _download(years: list[int]) -> list[dict]:
    session = requests.Session()
    session.headers["User-Agent"] = _user_agent()
    for year in years:
        raw = _read_zip_csv(session, IPEDS_URL.format(year=year))
        if not raw:
            continue
        rows = []
        reader = csv.DictReader(io.StringIO(raw))
        cols = {c.strip().upper(): c for c in reader.fieldnames or []}
        basic_col = next((cols[c] for c in ("C21BASIC", "C18BASIC", "C15BASIC") if c in cols), None)

        def g(row, col, default=""):
            return (row.get(cols.get(col, col)) or default).strip()

        for row in reader:
            try:
                basic = int(row.get(basic_col) or -2) if basic_col else -2
            except ValueError:
                basic = -2
            if basic <= 0:
                continue  # not a degree-granting, classified institution
            rows.append({
                "id": g(row, "UNITID"),
                "name": g(row, "INSTNM"),
                "aliases": [a.strip() for a in re.split(r"[|;,]", g(row, "IALIAS")) if len(a.strip()) > 2][:8],
                "city": g(row, "CITY"),
                "state": g(row, "STABBR"),
                "basic": basic,
                "hbcu": g(row, "HBCU") == "1",
                "tribal": g(row, "TRIBAL") == "1",
                "landgrant": g(row, "LANDGRNT") == "1",
                "medical": g(row, "MEDICAL") == "1",
                "control": {"1": "Public", "2": "Private nonprofit", "3": "Private for-profit"}.get(g(row, "CONTROL"), ""),
                "lat": float(g(row, "LATITUDE") or 0) or None,
                "lon": float(g(row, "LONGITUD") or 0) or None,
            })
        if rows:
            log.info("IPEDS directory %s: %d institutions (%s)", year, len(rows), basic_col)
            vets, vet_source = set(), "not available"
            for cy in (year, year - 1):
                comp = _read_zip_csv(session, COMPLETIONS_URL.format(year=cy))
                if comp:
                    vets = vet_unitids(comp)
                    if vets:
                        vet_source = f"IPEDS C{cy}_A (CIP {VET_CIP})"
                        break
            for r in rows:
                r["vetmed"] = r["id"] in vets
            log.info("veterinary schools: %d (%s)", len(vets), vet_source)
            return [{"source": f"IPEDS HD{year}", "classification": basic_col, "vet_source": vet_source,
                     "version": DIRECTORY_VERSION, "fetched": date.today().isoformat()}] + rows
    return []


def load_directory(offline: bool = False) -> tuple[dict, list[dict]]:
    info, rows = {}, []
    if DIRECTORY_FILE.exists():
        data = json.loads(DIRECTORY_FILE.read_text(encoding="utf-8"))
        info, rows = data.get("info", {}), data.get("institutions", [])
    stale = (not rows or info.get("version", 1) < DIRECTORY_VERSION
             or (date.today() - date.fromisoformat(info.get("fetched", "2000-01-01"))).days > REFRESH_DAYS)
    if stale and not offline:
        this_year = date.today().year
        got = _download([this_year - 1, this_year - 2, this_year - 3])
        if got:
            info, rows = got[0], got[1:]
            DIRECTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            DIRECTORY_FILE.write_text(json.dumps({"info": info, "institutions": rows}, separators=(",", ":")),
                                      encoding="utf-8")
    return info, rows


@lru_cache(maxsize=1)
def _lists() -> dict[str, set[tuple[str, str]]]:
    """{group: {(normalised name, state or "")}}. Entries may end in "| ST" to pin a state."""
    data = yaml.safe_load((CONFIG_DIR / "institution_lists.yaml").read_text(encoding="utf-8"))
    out = {}
    for key, names in data.items():
        entries = set()
        for n in names:
            name, _, st = n.partition("|")
            entries.add((_norm(name), st.strip().upper()))
        out[key] = entries
    return out


# ----------------------------------------------------------------------------- matching
_STATE_ABBR = {v.lower(): k for k, v in US_STATES.items()}
_INSTITUTE = re.compile(r"\b(institute|instituut|institut|center|centre|laborator(?:y|ies)|hospital|clinic|foundation|"
                        r"research council|national lab|agency|ministry)\b", re.I)
_UNIVERSITY = re.compile(r"\b(universit\w*|college|school of medicine|polytechnic|école|ecole|hochschule)\b", re.I)


class Classifier:
    def __init__(self, rows: list[dict]):
        self.by_state: dict[str, list[tuple[str, dict]]] = {}
        for r in rows:
            for n in {r["name"], *r.get("aliases", [])}:
                nn = _norm(n)
                if len(nn) >= 4:
                    self.by_state.setdefault(r["state"], []).append((nn, r))
        self.available = bool(rows)

    def match(self, employer: str, state: str | None, city: str = "", description: str = "") -> dict | None:
        pools = [self.by_state.get(state, [])] if state else list(self.by_state.values())
        emp = _norm(employer or "")
        city_n = _norm(city or "")
        best, best_score = None, 0.0
        if emp:
            etoks = set(emp.split())
            for pool in pools:
                for nn, r in pool:
                    if nn == emp:
                        score = 1.0
                    elif re.search(rf"\b{re.escape(nn)}\b", emp) and len(nn.split()) >= 2:
                        score = 0.85 + min(len(nn), 60) / 1000   # "university of utah department of pathology"
                    elif re.search(rf"\b{re.escape(emp)}\b", nn) and city_n and _norm(r["city"]) == city_n:
                        score = 0.8                               # "texas a and m university" ~ "... college station"
                    else:
                        ntoks = set(nn.split())
                        score = len(etoks & ntoks) / len(etoks | ntoks) if ntoks else 0
                        if city_n and _norm(r["city"]) == city_n:
                            score += 0.1
                    if score > best_score:
                        best, best_score = r, score
        if best_score >= 0.8:
            return best
        # Employer is a department or unit: look for an institution name in the posting text.
        if description and state:
            text = " " + _norm(description[:5000]) + " "
            found = None
            for nn, r in self.by_state.get(state, []):
                if len(nn.split()) >= 2 and len(nn) >= 12 and f" {nn} " in text:
                    if not found or len(nn) > len(found[0]):
                        found = (nn, r)
            if found:
                return found[1]
        return None


def classify(employer: str, location: dict, description: str, clf: Classifier | None) -> dict:
    """Returns {"types": [...], "carnegie": "...", "control": "...", "matched_name": "...", "lat"/"lon"}."""
    lists = _lists()
    out: dict = {"types": [], "carnegie": "", "control": "", "matched_name": ""}
    cc = location.get("country_code")
    region = (location.get("region") or "").strip()
    state = region.upper() if region.upper() in US_STATES else _STATE_ABBR.get(region.lower())
    emp_n = _norm(employer or "")

    def listed(key: str, *names: str, st: str | None = None) -> bool:
        for name, pinned in lists.get(key, set()):
            if name in names and (not pinned or pinned == (st or state or "")):
                return True
        return False

    if cc and cc != "US":
        out["types"] = ["international"]
        if _INSTITUTE.search(employer or "") and not _UNIVERSITY.search(employer or ""):
            out["types"].append("institute")
        return out

    rec = clf.match(employer, state, location.get("city", ""), description) if clf and clf.available else None
    if rec:
        names = [_norm(rec["name"]), *(_norm(a) for a in rec.get("aliases", []))]
        kind, label = CARNEGIE.get(rec["basic"], ("unknown", ""))
        types = [kind]
        if listed("ivy_league", *names, st=rec["state"]):
            types.append("ivy")
        if rec["hbcu"]:
            types.append("hbcu")
        if listed("womens_colleges", *names, st=rec["state"]):
            types.append("womens")
        if rec["tribal"] and "tribal" not in types:
            types.append("tribal")
        if rec["landgrant"]:
            types.append("landgrant")
        if rec["medical"] and kind != "medical":
            types.append("med_school")
        if rec.get("vetmed") or listed("vet_schools", *names, st=rec["state"]):
            types.append("vet_school")
        out.update(types=types, carnegie=label, control=rec["control"], matched_name=rec["name"],
                   lat=rec.get("lat"), lon=rec.get("lon"))
        return out

    # No directory match: still use the lists and the employer name.
    types = []
    if listed("ivy_league", emp_n):
        types.append("ivy")
    if listed("womens_colleges", emp_n):
        types.append("womens")
    if listed("vet_schools", emp_n):
        types.append("vet_school")
    if _INSTITUTE.search(employer or "") and not _UNIVERSITY.search(employer or ""):
        types.append("institute")
    out["types"] = types or ["unknown"]
    return out
