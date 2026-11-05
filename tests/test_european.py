"""European sources and labels, run end to end on fictional pages (no network)."""

import json
from datetime import date

import pytest
import requests

import collector.geo as geo
import collector.institutions as inst
import collector.run as run
import collector.sources as sources
from collector.classify import rank_label, ranks, relevance, tenure, tenure_label
from collector.dates import find_dates
from collector.http import FetchError
from test_pipeline import FIX


def jsonld(title, desc, org, city, country, posted="2026-10-20", valid="2026-12-15"):
    data = {"@context": "https://schema.org/", "@type": "JobPosting", "title": title, "description": desc,
            "datePosted": posted + "T00:00:00Z", "validThrough": valid + "T23:59:00Z",
            "hiringOrganization": {"@type": "Organization", "name": org},
            "jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": city,
                                                            "addressCountry": country}}]}
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body><h1>{title}</h1></body></html>'


def euraxess_page(title, profile, positions, desc, country="Germany", city="Freiburg", contract="Permanent",
                  org="Example University of Freiburg", deadline="2027-01-10T22:59:59+00:00"):
    return f'''<html><head><meta property="og:title" content="{title}"></head><body><main>
<div>Posted on: 3 November 2026</div>
<h2 id="job-information">Job Information</h2>
<dl><dt>Organisation/Company</dt><dd><div>{org}</div></dd>
<dt>Researcher Profile</dt><dd><div><div>{profile}</div></div></dd>
<dt>Positions</dt><dd><div>{positions}</div></dd>
<dt>Application Deadline</dt><dd><div><time datetime="{deadline}">10 Jan 2027 - 23:59 (Europe/Berlin)</time></div></dd>
<dt>Country</dt><dd><div>{country}</div></dd>
<dt>Type of Contract</dt><dd><div>{contract}</div></dd>
<dt>Job Status</dt><dd><div>Full-time</div></dd></dl>
<h2 id="offer-description">Offer Description</h2><div><p>{desc}</p></div>
<h2 id="work-locations">Work Location(s)</h2><dl><dt>City</dt><dd>{city}</dd></dl>
</main></body></html>'''


PAGES = {
    # jobs.ac.uk search page and jobs
    "https://www.jobs.ac.uk/search/?keywords=microbiome&sortOrder=1&pageSize=100": """<html><body>
      <a href="/job/ABC123/lecturer-in-microbiome-science">Lecturer in Microbiome Science</a>
      <a href="/job/ABC124/phd-studentship-gut-microbiome">PhD Studentship: Gut Microbiome</a>
      <a href="/job/ABC125/senior-lecturer-in-plant-microbiology">Senior Lecturer in Plant Microbiology</a></body></html>""",
    "https://www.jobs.ac.uk/job/ABC123/lecturer-in-microbiome-science": jsonld(
        "Lecturer in Microbiome Science",
        "<p>The School of Biosciences seeks a Lecturer (permanent, full time) in host-microbiome interactions in "
        "livestock and human health. The appointment is 60% research and 40% teaching.</p>",
        "Example University of Leeds", "Leeds", "United Kingdom"),
    "https://www.jobs.ac.uk/job/ABC125/senior-lecturer-in-plant-microbiology": jsonld(
        "Senior Lecturer in Plant Microbiology", "<p>Teaching plant pathology and crop protection.</p>",
        "Example University", "Norwich", "United Kingdom"),
    # Max Planck feed
    "https://feeds.example/jobs.rss": """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
      <item><title>Max Planck Research Group Leader (W2) (m/f/d) | Microbial symbioses</title>
        <link>https://www.mpg.de/111/group-leader-symbiosis</link><pubDate>Mon, 02 Nov 2026 10:00:00 +0100</pubDate></item>
      <item><title>PhD Student (m/f/d) | Gut microbiota</title>
        <link>https://www.mpg.de/112/phd-gut</link><pubDate>Mon, 02 Nov 2026 10:00:00 +0100</pubDate></item>
      </channel></rss>""",
    "https://www.mpg.de/111/group-leader-symbiosis": jsonld(
        "Max Planck Research Group Leader (W2) (m/f/d) | Microbial symbioses",
        "<p>The Example Max Planck Institute for Marine Microbiology invites applications for an independent "
        "research group studying the microbiome of corals and sponges (holobionts).</p>",
        "Example Max Planck Institute for Marine Microbiology", "Bremen", "DE"),
    # EURAXESS: newest-first list and numbered job pages
    "https://euraxess.example/jobs/search": '<a href="/jobs/1005">A</a><a href="/jobs/1004">B</a>',
    "https://euraxess.example/jobs/1005": euraxess_page(
        "W3-Professur für Mikrobiomforschung", "Leading Researcher (R4)", "Professor Positions",
        "Die Universität sucht eine Persönlichkeit, die das Mikrobiom des Darms erforscht. Die Stelle ist unbefristet."),
    "https://euraxess.example/jobs/1004": euraxess_page(
        "Doctoral researcher in microbiome science", "First Stage Researcher (R1)", "PhD Positions",
        "PhD project on the gut microbiome."),
    "https://euraxess.example/jobs/1002": euraxess_page(
        "Tenure-track Assistant Professor in Soil Microbial Ecology", "Recognised Researcher (R2)", "Research Positions",
        "We study rhizosphere microbial communities and soil health in agriculture.", country="Netherlands",
        city="Wageningen", org="Example Wageningen University", contract="Temporary"),
    # page 1003 does not exist (404): an unused job number
}


class Client:
    opened: list = []
    requests_made = 0

    def __init__(self, *a, **k):
        Client.opened = []

    def get(self, url, **_):
        Client.opened.append(url)
        if url not in PAGES:
            raise FetchError(f"HTTP 404 for {url}")
        r = requests.Response()
        r.status_code, r._content, r.encoding = 200, PAGES[url].encode(), "utf-8"
        return r


@pytest.fixture
def env(tmp_path, monkeypatch):
    site, state = tmp_path / "docs" / "data", tmp_path / "data"
    for name, val in {"JOBS_FILE": site / "jobs.json", "META_FILE": site / "meta.json",
                      "CSV_FILE": site / "jobs.csv", "FEED_FILE": tmp_path / "docs" / "feed.xml",
                      "CHECKED_FILE": state / "checked.json", "SUBMITTED_FILE": state / "none.txt",
                      "SITE_DATA_DIR": site}.items():
        monkeypatch.setattr(run, name, val)
    monkeypatch.setattr(geo, "CACHE_FILE", state / "geocache.json")
    monkeypatch.setattr(inst, "DIRECTORY_FILE", FIX / "institutions.json")
    monkeypatch.setattr("collector.translate.CACHE_FILE", state / "translations.json")
    monkeypatch.setattr("collector.STATE_DIR", state)
    monkeypatch.setattr(run, "PoliteClient", Client)
    monkeypatch.setenv("OFFLINE", "1")
    cfg = tmp_path / "sources.yaml"
    cfg.write_text("""
settings: {delay_seconds: 0}
keywords: [microbiome]
sources:
  - {id: jobs_ac_uk, name: jobs.ac.uk, type: listing, base: "https://www.jobs.ac.uk",
     urls: ["/search/?keywords={keyword}&sortOrder=1&pageSize=100"], link_pattern: '/job/[A-Z0-9]{5,}/[a-z0-9\\-]+',
     deadline_from_valid_through: true}
  - {id: maxplanck, name: Max Planck Society, type: rss, feeds: ["https://feeds.example/jobs.rss"]}
  - {id: euraxess, name: EURAXESS, type: euraxess, base: "https://euraxess.example", max_per_run: 50, backfill_ids: 4}
""")
    return tmp_path, site, state, cfg


def test_european_sources_end_to_end(env):
    tmp_path, site, state, cfg = env
    assert run.run(["--sources", str(cfg), "--today", "2026-11-04"]) == 0
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
    assert set(jobs) == {
        "Lecturer in Microbiome Science",
        "Max Planck Research Group Leader (W2) (m/f/d) | Microbial symbioses",
        "W3-Professur für Mikrobiomforschung",
        "Tenure-track Assistant Professor in Soil Microbial Ecology",
    }
    # PhD pages are never opened; the plant microbiology lecturer has no microbiome terms.
    assert not any("phd" in u for u in Client.opened)

    uk = jobs["Lecturer in Microbiome Science"]
    assert uk["location"]["country"] == "United Kingdom" and uk["deadline"] == "2026-12-15"
    assert uk["rank_label"] == "Lecturer / Reader" and uk["effort"] == {"research": 60, "teaching": 40}

    mpg = jobs["Max Planck Research Group Leader (W2) (m/f/d) | Microbial symbioses"]
    assert mpg["rank_label"] == "Investigator / Group leader" and "ocean" in mpg["domains"]
    assert "institute" in mpg["inst_types"]

    de = jobs["W3-Professur für Mikrobiomforschung"]
    assert de["rank_label"] == "Full" and de["tenure_label"] == "Permanent / continuing"
    assert de["deadline"] == "2027-01-10" and de["location"]["country"] == "Germany"

    nl = jobs["Tenure-track Assistant Professor in Soil Microbial Ecology"]
    assert nl["rank_label"] == "Assistant" and nl["tenure_label"] == "Tenure-track" and "soil" in nl["domains"]

    # EURAXESS walk: numbers 1001..1005 checked (backfill 4 below the newest), progress saved.
    st = json.loads((state / "euraxess_state.json").read_text())
    assert st["done_high"] == 1005 and st["done_low"] == 1001
    meta = json.loads((site / "meta.json").read_text())
    assert all(s["ok"] for s in meta["sources"])


def test_euraxess_second_run_opens_only_new_numbers(env):
    tmp_path, site, state, cfg = env
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    PAGES["https://euraxess.example/jobs/search"] = '<a href="/jobs/1006">new</a>'
    PAGES["https://euraxess.example/jobs/1006"] = euraxess_page(
        "Postdoc in microbiome analysis", "Recognised Researcher (R2)", "Postdoc Positions", "Gut microbiome.")
    try:
        run.run(["--sources", str(cfg), "--today", "2026-11-05"])
        opened = [u for u in Client.opened if u.startswith("https://euraxess.example/jobs/1")]
        assert opened == ["https://euraxess.example/jobs/1006"]
        assert json.loads((state / "euraxess_state.json").read_text())["done_high"] == 1006
    finally:
        PAGES["https://euraxess.example/jobs/search"] = '<a href="/jobs/1005">A</a><a href="/jobs/1004">B</a>'
        PAGES.pop("https://euraxess.example/jobs/1006")


def test_withdrawn_feed_job_closes(env):
    tmp_path, site, state, cfg = env
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    saved = PAGES.pop("https://www.mpg.de/111/group-leader-symbiosis")
    feed = PAGES["https://feeds.example/jobs.rss"]
    PAGES["https://feeds.example/jobs.rss"] = feed.split("<item>")[0] + "</channel></rss>"
    try:
        run.run(["--sources", str(cfg), "--today", "2026-11-12"])  # a week later: re-check, page gone
        jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
        g = jobs["Max Planck Research Group Leader (W2) (m/f/d) | Microbial symbioses"]
        assert g["status"] == "closed" and g["closed_reason"] == "listing removed"
    finally:
        PAGES["https://www.mpg.de/111/group-leader-symbiosis"] = saved
        PAGES["https://feeds.example/jobs.rss"] = feed


@pytest.mark.parametrize("title,label", [
    ("W3-Professur für Mikrobiologie", "Full"),
    ("W2/W3-Professur Mikrobiom", "Associate / Full"),
    ("Juniorprofessur (W1) für Mikrobiomforschung", "Assistant"),
    ("Universitair Docent Microbiome & Health", "Assistant"),
    ("Universitair Hoofddocent Microbiële Ecologie", "Associate"),
    ("Hoogleraar Medische Microbiologie", "Full"),
    ("Maître de conférences en microbiologie", "Associate"),
    ("Universitetslektor i mikrobiologi", "Lecturer / Reader"),
    ("Max Planck Research Group Leader (w2) (m/f/d)", "Investigator / Group leader"),
    ("Chargé de recherche – microbiote intestinal", "Investigator / Group leader"),
])
def test_european_ranks(title, label):
    assert rank_label(ranks(title, "")) == label


@pytest.mark.parametrize("title", ["Doktorand (m/w/d) Mikrobiom", "Wissenschaftlicher Mitarbeiter (m/w/d) Mikrobiom",
                                   "AIOS Medische Microbiologie", "University Assistant Postdoctoral, Microbiology"])
def test_european_non_faculty_excluded(title):
    assert not relevance(title, "Mikrobiom").keep


def test_other_language_terms_and_dates():
    assert relevance("Professeur en microbiologie", "Étude du microbiote intestinal").keep
    assert relevance("Universitair Docent", "onderzoek naar het microbioom").keep
    assert tenure_label(tenure("Professur", "Die Stelle ist unbefristet.")) == "Permanent / continuing"
    assert find_dates("Bewerbungsfrist: 15.12.2026.", date(2026, 11, 4)).deadline == date(2026, 12, 15)


def test_euraxess_refused_pages_are_retried(env, monkeypatch):
    tmp_path, site, state, cfg = env
    real_get = Client.get

    def refusing(self, url, **kw):
        if url == "https://euraxess.example/jobs/1002":
            Client.opened.append(url)
            raise FetchError("HTTP 403 for " + url)
        return real_get(self, url, **kw)

    monkeypatch.setattr(Client, "get", refusing)
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    st = json.loads((state / "euraxess_state.json").read_text())
    assert st["done_low"] == 1003  # 1003 (404) counts as checked; 1002 (403) doesn't
    monkeypatch.setattr(Client, "get", real_get)
    run.run(["--sources", str(cfg), "--today", "2026-11-05"])
    assert "https://euraxess.example/jobs/1002" in Client.opened
    titles = {j["title"] for j in json.loads((site / "jobs.json").read_text())}
    assert "Tenure-track Assistant Professor in Soil Microbial Ecology" in titles


def test_per_site_delay_from_config():
    from collector.http import PoliteClient
    c = PoliteClient(delay_seconds=1.5)
    sources.build_sources({"settings": {}, "keywords": [], "sources": [
        {"id": "e", "name": "E", "type": "euraxess", "base": "https://euraxess.example", "delay_seconds": 5}]}, c, [])
    assert c.host_delay == {"euraxess.example": 5.0}


def test_fems_style_feed_takes_employer_from_title(monkeypatch):
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
      <item><title>Assistant Professor in Microbial Ecology &#8211; Example University of Ghent</title>
        <link>https://fems.example/opportunities/ap-microbial-ecology/</link><pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate></item>
      </channel></rss>"""
    page = """<html><head><meta property="og:title" content="Assistant Professor in Microbial Ecology – Example University of Ghent">
      <meta property="og:site_name" content="FEMS"></head><body><main><p>Tenure-track post studying the gut microbiome
      of farmed fish in aquaculture.</p></main></body></html>"""
    pages = {"https://fems.example/feed/": feed, "https://fems.example/opportunities/ap-microbial-ecology/": page}

    class C:
        def get(self, url, **_):
            r = requests.Response(); r.status_code, r._content, r.encoding = 200, pages[url].encode(), "utf-8"
            return r

    src = sources.RssSource({"id": "fems", "name": "FEMS", "feeds": ["https://fems.example/feed/"],
                             "employer_from_title": True}, {}, [], C())
    [e] = src.list_entries()
    assert e.title == "Assistant Professor in Microbial Ecology – Example University of Ghent"
    d = src.fetch_detail(e)
    assert d.employer == "Example University of Ghent"
    assert relevance(d.title, d.description).keep
