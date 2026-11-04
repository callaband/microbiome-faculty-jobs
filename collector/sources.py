"""Readers for each kind of job board.

Every reader has two steps:
  list_entries()  -> cheap feed read: what postings exist right now
  fetch_detail()  -> open one posting's page for the full description and dates
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote_plus, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .dates import parse_any
from .http import FetchError, PoliteClient
from .regions import country_code, parse_place
from .text import clean, html_to_text

log = logging.getLogger(__name__)


@dataclass
class Entry:
    """One posting as listed in a feed."""
    source_id: str
    url: str                 # canonical URL of the posting on that board
    title: str
    employer: str = ""
    location_text: str = ""
    date_posted: date | None = None


@dataclass
class Detail:
    """What we learn from opening the posting's page."""
    title: str = ""
    employer: str = ""
    description: str = ""
    city: str = ""
    region: str = ""
    country_code: str | None = None
    date_posted: date | None = None
    listing_expires: date | None = None   # when the board listing ends
    application_due: date | None = None   # employer-stated deadline field
    job_type: str = ""                    # board's job-type label, e.g. "Faculty"
    employment: str = ""                  # Full-Time / Part-Time
    salary: str = ""
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- helpers
def _strip_query(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _rss_items(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as exc:
        raise FetchError(f"feed is not valid XML ({exc})") from exc
    items = []
    for it in root.iter("item"):
        get = lambda tag: (it.findtext(tag) or "").strip()  # noqa: E731
        items.append({"title": get("title"), "link": get("link"), "description": get("description"),
                      "pubDate": get("pubDate"), "guid": get("guid")})
    return items


def _jsonld_jobposting(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                t = node.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return node
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return None


def _detail_from_jsonld(jp: dict, d: Detail) -> None:
    d.title = clean(jp.get("title")) or d.title
    d.description = html_to_text(jp.get("description")) or d.description
    org = jp.get("hiringOrganization") or {}
    if isinstance(org, dict):
        d.employer = clean(org.get("name")) or d.employer
    d.date_posted = parse_any(jp.get("datePosted")) or d.date_posted
    d.listing_expires = parse_any(jp.get("validThrough")) or d.listing_expires
    et = jp.get("employmentType")
    if isinstance(et, list):
        et = ", ".join(map(str, et))
    d.employment = re.sub(r'[\[\]"\\]', "", str(et or "")).replace("_", "-").title() or d.employment
    locs = jp.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, dict) and (addr.get("addressLocality") or addr.get("addressCountry")):
            cc = addr.get("addressCountry")
            if isinstance(cc, dict):
                cc = cc.get("name")
            d.city = clean(addr.get("addressLocality")) or d.city
            d.region = clean(addr.get("addressRegion")) or d.region
            d.country_code = country_code(clean(str(cc or ""))) or d.country_code
            break
    sal = jp.get("baseSalary")
    if isinstance(sal, dict):
        v = sal.get("value") or {}
        if isinstance(v, dict) and (v.get("minValue") or v.get("value")):
            lo, hi = v.get("minValue") or v.get("value"), v.get("maxValue")
            cur = sal.get("currency", "")
            d.salary = f"{cur} {lo}" + (f"–{hi}" if hi else "")


def _definition_list(soup: BeautifulSoup) -> dict[str, str]:
    out = {}
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                out[clean(dt.get_text(" ")).rstrip(":").lower()] = clean(dd.get_text(" "))
    return out


# ----------------------------------------------------------------------------- Madgex
class MadgexSource:
    """Science Careers, Nature Careers, Chronicle, Inside Higher Ed, THE, ..."""

    def __init__(self, cfg: dict, settings: dict, keywords: list[str], client: PoliteClient):
        self.id, self.name, self.base = cfg["id"], cfg["name"], cfg["base"].rstrip("/")
        self.max_pages = int(settings.get("max_pages", 5))
        self.keywords = cfg.get("keywords") or keywords
        self.client = client

    def list_entries(self) -> list[Entry]:
        seen: dict[str, Entry] = {}
        for kw in self.keywords:
            for page in range(1, self.max_pages + 1):
                url = f"{self.base}/jobsrss/?keywords={quote_plus(kw)}" + (f"&page={page}" if page > 1 else "")
                items = _rss_items(self.client.get(url, accept="application/rss+xml, application/xml").text)
                new = 0
                for it in items:
                    link = _strip_query(it["link"] or it["guid"])
                    if "/job/" not in link or link in seen:
                        continue
                    new += 1
                    title, employer = it["title"], ""
                    if ": " in title:
                        employer, title = title.split(": ", 1)
                    desc_lines = [ln.strip() for ln in html_to_text(it["description"]).splitlines() if ln.strip()]
                    seen[link] = Entry(self.id, link, clean(title), clean(employer),
                                       desc_lines[-1] if desc_lines else "", parse_any(it["pubDate"]))
                if len(items) < 20 or new == 0:
                    break
        return list(seen.values())

    def fetch_detail(self, entry: Entry) -> Detail:
        resp = self.client.get(entry.url)
        soup = BeautifulSoup(resp.text, "html.parser")
        d = Detail(title=entry.title, employer=entry.employer, date_posted=entry.date_posted)
        jp = _jsonld_jobposting(soup)
        if jp:
            _detail_from_jsonld(jp, d)
        facts = _definition_list(soup)
        d.employer = facts.get("employer") or d.employer
        d.salary = facts.get("salary") or d.salary
        d.job_type = facts.get("job type", "")
        d.extra = {k: v for k, v in facts.items() if k in ("discipline", "organization type", "hours", "contract type")}
        if facts.get("closing date"):
            d.listing_expires = parse_any(facts["closing date"]) or d.listing_expires
        if facts.get("hours") and not d.employment:
            d.employment = facts["hours"]
        if not d.description:
            main = soup.find(class_=re.compile("job-description|mds-edited-text")) or soup.find("main")
            d.description = html_to_text(str(main)) if main else ""
        if not (d.city or d.country_code):
            place = parse_place(facts.get("location") or entry.location_text)
            d.city, d.region, d.country_code = place["city"], place["region"], place["country_code"]
        return d


# ----------------------------------------------------------------------------- HigherEdJobs
class HigherEdJobsSource:
    def __init__(self, cfg: dict, settings: dict, keywords: list[str], client: PoliteClient):
        self.id, self.name, self.base = cfg["id"], cfg["name"], cfg["base"].rstrip("/")
        self.categories = cfg.get("categories") or {}
        self.client = client

    def list_entries(self) -> list[Entry]:
        seen: dict[str, Entry] = {}
        errors = []
        for cat_id in self.categories:
            url = f"{self.base}/rss/categoryFeed.cfm?catID={cat_id}"
            try:
                items = _rss_items(self.client.get(url, accept="application/rss+xml, text/xml").text)
            except FetchError as exc:
                errors.append(str(exc))
                if len(errors) >= 3 and not seen:
                    raise  # the whole site is refusing us; stop early
                continue
            for it in items:
                m = re.search(r"JobCode=(\d+)", it["link"] or it["guid"])
                if not m:
                    continue
                link = f"{self.base}/details.cfm?JobCode={m.group(1)}"
                if link in seen:
                    continue
                desc = clean(it["description"])
                employer, loc = desc, ""
                mm = re.match(r"^(.*)\(([^()]*)\)\s*$", desc)
                if mm:
                    employer, loc = mm.group(1).strip(), mm.group(2).strip()
                seen[link] = Entry(self.id, link, clean(it["title"]), employer, loc, parse_any(it["pubDate"]))
        if errors and not seen:
            raise FetchError(errors[0])
        return list(seen.values())

    def fetch_detail(self, entry: Entry) -> Detail:
        soup = BeautifulSoup(self.client.get(entry.url).text, "html.parser")
        d = Detail(title=entry.title, employer=entry.employer, date_posted=entry.date_posted)
        jp = _jsonld_jobposting(soup)
        if jp:
            _detail_from_jsonld(jp, d)
        desc = soup.find(id="jobDesc")
        if desc:
            d.description = html_to_text(str(desc))
        attrib = soup.find(id="jobAttrib")
        if attrib:
            text = attrib.get_text("\n")
            for label, val in re.findall(r"([A-Za-z ]+):\s*\n?\s*([^\n]+)", text):
                label, val = label.strip().lower(), val.strip()
                if label == "type":
                    d.employment = val
                elif label == "application due":
                    d.application_due = parse_any(val)
                    if not d.application_due:
                        d.extra["application_due_text"] = val
                elif label == "category":
                    d.job_type = val
        inst = soup.select_one("#jobLocation .job-inst")
        loc = soup.select_one("#jobLocation .job-loc")
        if inst:
            d.employer = clean(inst.get_text(" "))
        loc_text = clean(loc.get_text(" ")).removeprefix("in ").strip() if loc else entry.location_text
        if not (d.city or d.country_code):
            place = parse_place(loc_text)
            d.city, d.region, d.country_code = place["city"], place["region"], place["country_code"]
        return d


# ----------------------------------------------------------------------------- generic page reading
def detail_from_page(html: str, entry: Entry, deadline_from_valid_through: bool = False) -> Detail:
    """Read a job page: schema.org JobPosting data first, then the page itself."""
    soup = BeautifulSoup(html, "html.parser")
    d = Detail(title=entry.title, employer=entry.employer, date_posted=entry.date_posted)
    jp = _jsonld_jobposting(soup)
    if jp:
        _detail_from_jsonld(jp, d)
        if deadline_from_valid_through and d.listing_expires:
            # On these boards the listing ends on the application deadline.
            d.application_due = d.listing_expires
    if not d.title:
        og = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        d.title = clean(og["content"]) if og and og.get("content") else clean(h1.get_text(" ") if h1 else "")
    if not d.description:
        main = soup.find("main") or soup.find("article") or soup.body
        d.description = html_to_text(str(main)) if main else ""
    if not d.employer:
        og = soup.find("meta", property="og:site_name")
        d.employer = clean(og["content"]) if og and og.get("content") else ""
    if not (d.city or d.country_code) and entry.location_text:
        place = parse_place(entry.location_text)
        d.city, d.region, d.country_code = place["city"], place["region"], place["country_code"]
    return d


def _expand(templates: list[str], keywords: list[str]) -> list[str]:
    out = []
    for t in templates:
        if "{keyword}" in t:
            out += [t.replace("{keyword}", quote_plus(k)) for k in keywords]
        else:
            out.append(t)
    return out


class ListingSource:
    """Search-result or category pages that link to job pages carrying JobPosting data.

    config:
      base:  https://www.example.org
      urls:  paths; "{keyword}" is replaced by each search keyword, "{page}" by 1..pages
      link_pattern: regex matching a job page's path
      pages: how many result pages to read when a url has "{page}" (default 1)
      deadline_from_valid_through: true when the board ends a listing on its deadline
    """

    def __init__(self, cfg: dict, settings: dict, keywords: list[str], client: PoliteClient):
        self.id, self.name, self.base = cfg["id"], cfg["name"], cfg["base"].rstrip("/")
        self.urls = _expand(cfg["urls"], cfg.get("keywords") or keywords)
        self.link_rx = re.compile(cfg["link_pattern"])
        self.pages = int(cfg.get("pages", 1))
        self.deadline_vt = bool(cfg.get("deadline_from_valid_through", False))
        self.client = client

    def _links(self, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        found: dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].split("#")[0]
            path = urlsplit(href).path if href.startswith("http") else href.split("?")[0]
            m = self.link_rx.search(path)
            if not m:
                continue
            url = self.base + m.group(0) if not href.startswith("http") else _strip_query(href)
            text = clean(a.get_text(" "))
            text = re.sub(r"^(view details|read more|more info(?:rmation)?)\s*", "", text, flags=re.I)
            if len(text) > len(found.get(url, "")) and len(text) < 300:
                found[url] = text
            else:
                found.setdefault(url, "")
        return list(found.items())

    def list_entries(self) -> list[Entry]:
        seen: dict[str, Entry] = {}
        errors = []
        for tpl in self.urls:
            for page in range(1, (self.pages if "{page}" in tpl else 1) + 1):
                url = self.base + tpl.replace("{page}", str(page))
                try:
                    links = self._links(self.client.get(url).text)
                except FetchError as exc:
                    errors.append(str(exc))
                    break
                new = [(u, t) for u, t in links if u not in seen]
                for u, t in new:
                    seen[u] = Entry(self.id, u, t)
                if not new:
                    break
        if errors and not seen:
            raise FetchError(errors[0])
        return list(seen.values())

    def fetch_detail(self, entry: Entry) -> Detail:
        return detail_from_page(self.client.get(entry.url).text, entry, self.deadline_vt)


class RssSource:
    """A plain RSS job feed whose items link to job pages (e.g. Max Planck Society).

    The feed only holds the latest postings, so jobs that drop off it stay listed
    until their deadline (partial_listing)."""

    partial_listing = True

    def __init__(self, cfg: dict, settings: dict, keywords: list[str], client: PoliteClient):
        self.id, self.name = cfg["id"], cfg["name"]
        self.feeds = cfg["feeds"]
        self.deadline_vt = bool(cfg.get("deadline_from_valid_through", False))
        self.client = client

    def list_entries(self) -> list[Entry]:
        seen: dict[str, Entry] = {}
        for feed in self.feeds:
            for it in _rss_items(self.client.get(feed, accept="application/rss+xml, application/xml").text):
                link = (it["link"] or it["guid"]).strip()
                if link and link not in seen:
                    seen[link] = Entry(self.id, link, clean(html_to_text(it["title"])), "", "", parse_any(it["pubDate"]))
        return list(seen.values())

    def fetch_detail(self, entry: Entry) -> Detail:
        return detail_from_page(self.client.get(entry.url).text, entry, self.deadline_vt)


class EuraxessSource:
    """EURAXESS (European Commission). Its robots.txt asks robots not to run searches,
    but allows the newest-first job list and every job page (/jobs/<number>). Job
    numbers rise steadily, so each run opens the numbers it hasn't checked yet: first
    the new ones, then, within a daily budget, older ones back to `backfill_ids`.
    Progress is kept in data/euraxess_state.json, so nothing is opened twice."""

    partial_listing = True
    remember_rejects = False  # progress file already prevents re-opening

    def __init__(self, cfg: dict, settings: dict, keywords: list[str], client: PoliteClient):
        from . import STATE_DIR
        self.id, self.name, self.base = cfg["id"], cfg["name"], cfg["base"].rstrip("/")
        self.budget = int(cfg.get("max_per_run", 600))
        self.backfill = int(cfg.get("backfill_ids", 7500))   # ~30 days at ~250 new jobs a day
        self.state_file = STATE_DIR / "euraxess_state.json"
        self.client = client
        self.known_urls: set[str] = set()
        self.processed: set[int] = set()
        self.current_max = 0

    def _url(self, n: int) -> str:
        return f"{self.base}/jobs/{n}"

    def _state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def list_entries(self) -> list[Entry]:
        html = self.client.get(self.base + "/jobs/search").text
        nums = [int(n) for n in re.findall(r"/jobs/(\d{3,})\b", html)]
        if not nums:
            raise FetchError("EURAXESS job list had no job links (page layout may have changed)")
        self.current_max = cur = max(nums)
        st = self._state()
        high = int(st.get("done_high", cur))
        low = int(st.get("done_low", cur + 1))
        floor = cur - self.backfill
        forward = list(range(high + 1, cur + 1))
        backward = list(range(min(low, cur + 1) - 1, floor - 1, -1))
        plan = (forward + backward)[: self.budget]
        out = []
        for n in plan:
            url = self._url(n)
            if url in self.known_urls:
                self.processed.add(n)
                continue
            out.append(Entry(self.id, url, ""))
        return out

    def fetch_detail(self, entry: Entry) -> Detail:
        n = int(entry.url.rsplit("/", 1)[1])
        self.processed.add(n)  # counted even if the page is gone (unused or withdrawn number)
        html = self.client.get(entry.url).text
        return parse_euraxess(html, entry)

    def finish(self) -> None:
        """Save how far the walk got: the contiguous checked range around the newest jobs."""
        if not self.current_max:
            return
        st = self._state()
        high = int(st.get("done_high", self.current_max))
        low = int(st.get("done_low", self.current_max + 1))
        while high + 1 in self.processed:
            high += 1
        while low - 1 in self.processed:
            low -= 1
        floor = self.current_max - self.backfill
        state = {"done_high": high, "done_low": max(low, floor), "current_max": self.current_max,
                 "updated": date.today().isoformat()}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")


def parse_euraxess(html: str, entry: Entry) -> Detail:
    soup = BeautifulSoup(html, "html.parser")
    d = Detail()
    og = soup.find("meta", property="og:title")
    d.title = clean(og["content"]) if og and og.get("content") else ""
    facts: dict[str, str] = {}
    times: dict[str, str] = {}
    for dt in soup.select("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        key = clean(dt.get_text(" ")).lower()
        if key not in facts:
            facts[key] = clean(dd.get_text(" "))
            t = dd.find("time")
            if t and t.get("datetime"):
                times[key] = t["datetime"]
    d.employer = facts.get("organisation/company", "")
    d.country_code = country_code(facts.get("country"))
    d.city = facts.get("city", "")
    d.application_due = parse_any(times.get("application deadline") or facts.get("application deadline", "").split(" - ")[0])
    d.employment = facts.get("job status", "")
    profile = facts.get("researcher profile", "")
    positions = facts.get("positions", "")
    d.extra = {"researcher_profile": profile, "positions": positions, "contract": facts.get("type of contract", "")}
    # R3 = established researcher, R4 = leading researcher: faculty-level profiles.
    if re.search(r"\bR[34]\b", profile) and not re.search(r"phd|postdoc", positions, re.I):
        d.job_type = "Faculty"
    parts = []
    for hid in ("offer-description", "requirements", "additional-information"):
        h = soup.find(id=hid)
        if h and h.find_next_sibling():
            parts.append(html_to_text(str(h.find_next_sibling())))
    if re.fullmatch(r"\s*permanent\s*", d.extra["contract"] or "", re.I):
        parts.append("Contract type (EURAXESS): Permanent")
    d.description = "\n\n".join(p for p in parts if p)
    posted = re.search(r"Posted on:\s*([^<\n]+)", html)
    d.date_posted = parse_any(posted.group(1)) if posted else None
    return d

# ----------------------------------------------------------------------------- Submitted URLs
class SubmittedSource:
    """URLs listed in data/submitted_urls.txt (community submissions)."""

    id, name = "submitted", "Community submissions"

    def __init__(self, urls: list[str], client: PoliteClient):
        self.urls = urls
        self.client = client

    def list_entries(self) -> list[Entry]:
        return [Entry(self.id, u, "") for u in self.urls]

    def fetch_detail(self, entry: Entry) -> Detail:
        soup = BeautifulSoup(self.client.get(entry.url).text, "html.parser")
        d = Detail()
        jp = _jsonld_jobposting(soup)
        if jp:
            _detail_from_jsonld(jp, d)
        if not d.title:
            h1 = soup.find("h1")
            d.title = clean(h1.get_text(" ")) if h1 else clean(soup.title.string if soup.title else "")
        if not d.description:
            main = soup.find("main") or soup.find("article") or soup.body
            d.description = html_to_text(str(main)) if main else ""
        if not d.employer:
            og = soup.find("meta", property="og:site_name")
            d.employer = clean(og["content"]) if og and og.get("content") else urlsplit(entry.url).netloc
        return d


def build_sources(cfg: dict, client: PoliteClient, submitted: list[str]):
    settings, keywords = cfg.get("settings", {}), cfg.get("keywords", [])
    kinds = {"madgex": MadgexSource, "hej_category": HigherEdJobsSource, "listing": ListingSource,
             "rss": RssSource, "euraxess": EuraxessSource}
    out = []
    for s in cfg.get("sources", []):
        if not s.get("enabled", True):
            continue
        kind = kinds.get(s.get("type"))
        if not kind:
            log.warning("unknown source type %r for %s", s.get("type"), s.get("id"))
            continue
        out.append(kind(s, settings, keywords, client))
    if submitted:
        out.append(SubmittedSource(submitted, client))
    return out
