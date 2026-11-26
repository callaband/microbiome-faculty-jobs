"""Fixes for boards that changed or failed (Nov 2026): robots.txt that can't be read, a site
that keeps failing, jobs.ac.uk's sitemap, and HigherEdJobs' keyword search."""
import json

import pytest
import requests

import collector.run as run
from collector import http, sources
from collector.http import FetchError, PoliteClient
from test_european import env  # noqa: F401  (fixture)


def resp(status, body="", headers=None):
    r = requests.Response()
    r.status_code, r._content, r.encoding = status, body.encode(), "utf-8"
    r.headers.update(headers or {})
    return r


class Session:
    """Stands in for requests.Session: answers by URL, counts calls."""

    def __init__(self, answers):
        self.answers, self.calls, self.headers = answers, [], {"User-Agent": "test"}

    def get(self, url, **_):
        self.calls.append(url)
        a = self.answers.get(url, self.answers.get("*"))
        if isinstance(a, Exception):
            raise a
        return a


def client(answers):
    c = PoliteClient(delay_seconds=0)
    c.session = Session(answers)
    return c


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


@pytest.mark.parametrize("robots", [resp(503), resp(500), resp(429), resp(403),
                                    requests.Timeout("slow"), requests.ConnectionError("down")])
def test_unreadable_robots_txt_means_stay_out(robots):
    # RFC 9309: if robots.txt can't be read because of a server error or no answer, assume
    # everything is disallowed (this let EURAXESS job pages be read on Nov 24).
    c = client({"https://ex.org/robots.txt": robots, "*": resp(200, "page")})
    with pytest.raises(FetchError, match="robots.txt"):
        c.get("https://ex.org/jobs/1")
    assert c.session.calls == ["https://ex.org/robots.txt"]


def test_missing_robots_txt_allows_everything():
    c = client({"https://ex.org/robots.txt": resp(404), "*": resp(200, "page")})
    assert c.get("https://ex.org/jobs/1").text == "page"


def test_euraxess_rules_now_disallow_job_pages():
    rules = "User-agent: *\nDisallow: /*?\nAllow: /jobs\nDisallow: /jobs/*\n"
    c = client({"https://euraxess.example/robots.txt": resp(200, rules), "*": resp(200, "x")})
    assert c.allowed("https://euraxess.example/jobs")
    assert not c.allowed("https://euraxess.example/jobs/search")
    assert not c.allowed("https://euraxess.example/jobs/123456")


def test_a_failing_site_is_left_alone_after_a_few_tries():
    # jobs.ac.uk answered 503 to every search for 24 minutes on Nov 25.
    c = client({"https://ex.org/robots.txt": resp(404), "*": resp(503)})
    for i in range(6):
        with pytest.raises(FetchError):
            c.get(f"https://ex.org/search?q={i}")
    page_calls = [u for u in c.session.calls if "search" in u]
    assert len(page_calls) == 3 * 2          # 3 pages, each tried twice, then no more requests
    with pytest.raises(FetchError, match="kept failing"):
        c.get("https://ex.org/other")


def test_a_site_that_recovers_is_not_written_off():
    answers = {"https://ex.org/robots.txt": resp(404), "*": resp(503)}
    c = client(answers)
    for i in range(2):
        with pytest.raises(FetchError):
            c.get(f"https://ex.org/a{i}")
    answers["*"] = resp(200, "ok")
    assert c.get("https://ex.org/b").text == "ok"
    answers["*"] = resp(503)
    with pytest.raises(FetchError, match="HTTP 503"):
        c.get("https://ex.org/c")            # count started again after the success


# ---------------------------------------------------------------- jobs.ac.uk sitemap
SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://jobs.example/</loc></url>
<url><loc>https://jobs.example/job/DTM143/lecturer-in-zoology-or-animal-science</loc></url>
<url><loc>https://jobs.example/job/DTS994/autocad-technician</loc></url>
<url><loc>https://jobs.example/job/DTQ524/phd-studentship-seagrass-microbiomes</loc></url>
<url><loc>https://jobs.example/job/DTR364/lecturer-environmental-studies</loc></url>
</urlset>"""


def jobpage(title, desc, org="University of Example", until="2027-01-03"):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": title, "description": desc,
          "validThrough": f"{until}T00:00:00+00:00", "hiringOrganization": {"@type": "Organization", "name": org},
          "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Exeter",
                                                          "addressCountry": "GB"}}}
    return f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body><h1>{title}</h1></body></html>'


class Fake:
    pages: dict = {}
    opened: list = []
    requests_made = 0

    def __init__(self, *a, **k):
        self.host_delay = {}

    def get(self, url, **_):
        Fake.opened.append(url)
        v = Fake.pages.get(url)
        if v is None:
            raise FetchError(f"HTTP 404 for {url}")
        return resp(200, v)


def test_jobs_ac_uk_sitemap_finds_jobs_its_title_search_misses(env, monkeypatch):  # noqa: F811
    tmp_path, site, state, cfg = env
    monkeypatch.setattr(run, "PoliteClient", Fake)
    Fake.opened = []
    Fake.pages = {
        "https://jobs.example/sitemap.xml": SITEMAP,
        "https://jobs.example/job/DTM143/lecturer-in-zoology-or-animal-science": jobpage(
            "Lecturer in Zoology or Animal Science",
            "Research on host–microbiome interactions in farmed animals is particularly welcome. " * 3),
        "https://jobs.example/job/DTR364/lecturer-environmental-studies": jobpage(
            "Lecturer, Environmental Studies", "Teach environmental policy and governance. " * 5),
    }
    cfg.write_text("""
settings: {delay_seconds: 0}
keywords: [microbiome]
sources:
  - {id: jobs_ac_uk, name: jobs.ac.uk, type: sitemap, base: https://jobs.example, sitemap: /sitemap.xml,
     link_pattern: '/job/[A-Z0-9]{5,}/[a-z0-9\\-]+', deadline_from_valid_through: true}
""")
    run.run(["--sources", str(cfg), "--today", "2026-11-26"])
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
    assert set(jobs) == {"Lecturer in Zoology or Animal Science"}
    assert jobs["Lecturer in Zoology or Animal Science"]["deadline"] == "2027-01-03"
    opened = [u for u in Fake.opened if "/job/" in u]
    assert not any("technician" in u or "phd" in u for u in opened)   # only faculty-looking titles opened
    # Next day: no job page is opened again; a job gone from the sitemap stops being "seen".
    Fake.opened = []
    run.run(["--sources", str(cfg), "--today", "2026-11-27"])
    assert [u for u in Fake.opened if "/job/" in u] == []


# ---------------------------------------------------------------- HigherEdJobs search
def card(code, title, inst, loc):
    return (f'<div class="job-card-body"><h3 class="job-card-title"><a href="details.cfm?JobCode={code}&amp;Title=x">'
            f'{title}</a></h3><div class="job-card-inst">{inst}</div><div class="job-card-meta"><span>{loc}</span>'
            f'</div></div>')


SEARCH = "https://www.higheredjobs.com/search/advanced_action.cfm?OnlyTitle=0&Keyword={kw}&SortBy=1&NumJobs=100&Page=1"


def test_higheredjobs_search_without_opening_job_pages(env, monkeypatch):  # noqa: F811
    tmp_path, site, state, cfg = env
    monkeypatch.setattr(run, "PoliteClient", Fake)
    Fake.opened = []
    Fake.pages = {
        SEARCH.format(kw="microbiome"): "<html><body>" + card(
            "179627815", "Assistant/Associate Professor of Microbiome Studies", "Example State University",
            "Logan, UT") + card("179600001", "Postdoctoral Scholar (Gut Lab)", "Example University", "Davis, CA") + "</body></html>",
        SEARCH.format(kw="rhizosphere"): "<html><body>" + card(
            "179600002", "Assistant Professor Of Soil-plant-water Interactions", "Example A&amp;M University",
            "College Station, TX") + card("179627815", "Assistant/Associate Professor of Microbiome Studies",
                                         "Example State University", "Logan, UT") + "</body></html>",
        "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=49": """<?xml version="1.0"?><rss><channel>
            <item><title>Assistant Professor Of Soil-plant-water Interactions</title>
            <link>https://www.higheredjobs.com/details.cfm?JobCode=179600002</link>
            <description>Example A&amp;M University (College Station, TX)</description>
            <pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>""",
    }
    cfg.write_text("""
settings: {delay_seconds: 0}
keywords: [microbiome, rhizosphere]
sources:
  - {id: higheredjobs, name: HigherEdJobs, type: hej_category, base: https://www.higheredjobs.com,
     open_pages: false, categories: {49: Plant and Soil Science}}
""")
    run.run(["--sources", str(cfg), "--today", "2026-11-26"])
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
    assert set(jobs) == {"Assistant/Associate Professor of Microbiome Studies",
                         "Assistant Professor Of Soil-plant-water Interactions"}
    assert not any("details.cfm" in u for u in Fake.opened)          # job pages never requested
    soil = jobs["Assistant Professor Of Soil-plant-water Interactions"]
    assert soil["date_posted"] == "2026-11-16" and soil["institution"] == "Example A&M University"
    assert soil["details_unavailable"] and soil["search_terms"] == ["rhizosphere"]
    micro = jobs["Assistant/Associate Professor of Microbiome Studies"]
    assert micro["search_terms"] == ["microbiome", "rhizosphere"] and micro["location"]["region"] == "Utah"
    # Later runs don't try to re-read these pages either.
    Fake.opened = []
    run.run(["--sources", str(cfg), "--today", "2026-12-04"])
    assert not any("details.cfm" in u for u in Fake.opened)
    assert json.loads((site / "jobs.json").read_text())[0]["institution"]


def test_higheredjobs_search_page_parser():
    html = card("1", "Assistant Professor", "U", "Boston, MA")
    c = type("C", (), {"get": lambda self, url, **k: resp(200, html), "host_delay": {}})()
    src = sources.HigherEdJobsSource({"id": "higheredjobs", "name": "HEJ", "base": "https://www.higheredjobs.com"},
                                     {}, ["microbiome"], c)
    (e,) = src.list_entries()
    assert e.url.endswith("JobCode=1") and e.employer == "U" and e.location_text == "Boston, MA"
