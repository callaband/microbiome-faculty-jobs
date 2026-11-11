"""Listings that have ended must not show as open (jobRxiv keeps expired jobs in its feed)."""
import json

import requests

import collector.run as run
from collector import sources
from collector.http import FetchError
from test_european import env  # noqa: F401  (fixture)

RELATED = """<div class="related-job-spotlight-carousel"><div class="job-spotlight">
  <h4>Associate Professor in Microbial Ecology</h4><p>The Environmental Microbiology Section studies the
  soil microbiome and microbial ecology of pollutant degradation.</p></div></div>"""
NAV = "<nav class='main-menu'><a>For Employers</a><a>Find a Job</a><a>Log In</a></nav>"


def page(title, body, expired=False, jsonld=True):
    ld = ("" if not jsonld or expired else
          '<script type="application/ld+json">{"@context":"http://schema.org/","@type":"JobPosting","title":"%s",'
          '"description":"%s","hiringOrganization":{"@type":"Organization","name":"Example University"},'
          '"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressCountry":"DK"}}}</script>'
          % (title, body))
    main = ('<div class="job-manager-info">This listing has expired.</div>' if expired
            else f'<div class="job_description">{body}</div>')
    # Same nesting as jobRxiv: the posting sits inside "new-header" and "right-sidebar" containers.
    return (f'<html><head><title>{title} - jobRxiv</title><meta property="og:site_name" content="jobRxiv">{ld}</head>'
            f'<body><div class="fullwidth new-header wrapper">{NAV}<h1>{title}</h1>'
            f'<div class="container right-sidebar"><div class="eleven columns"><div class="single_job_listing">{main}'
            f'</div></div><aside class="widget">Recent jobs</aside>{RELATED}</div></div>'
            f'<footer>Contact Us</footer></body></html>')


LIVE = "https://jobrxiv.example/job/assistant-professor-gut-microbiome/"
QUANTUM = "https://jobrxiv.example/?post_type=job_listing&p=158449"
QUANTUM_GUID = "https://jobrxiv.example/job/assistant-professor-quantum/"
GONE = "https://jobrxiv.example/job/associate-professor-soil-microbiome/"
DESC = ("Tenure-track Assistant Professor studying the gut microbiome and host-microbe interactions in "
        "livestock. The successful candidate will build an internationally recognised research programme. ") * 2


def feed(*items):
    esc = lambda u: u.replace("&", "&amp;")  # noqa: E731
    body = "".join(f"<item><title>{t}</title><link>{esc(link)}</link><guid>{esc(guid)}</guid>"
                   f"<pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate></item>" for t, link, guid in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>{body}</channel></rss>'


class C:
    pages: dict = {}
    opened: list = []
    requests_made = 0

    def __init__(self, *a, **k):
        self.host_delay = {}

    def get(self, url, **_):
        C.opened.append(url)
        val = C.pages.get(url)
        if val is None:
            raise FetchError(f"HTTP 404 for {url}")
        if isinstance(val, Exception):
            raise val
        r = requests.Response(); r.status_code, r._content, r.encoding = 200, val.encode(), "utf-8"
        return r


def setup(env, monkeypatch, pages):  # noqa: F811
    tmp_path, site, state, cfg = env
    monkeypatch.setattr(run, "PoliteClient", C)
    C.pages, C.opened = pages, []
    cfg.write_text("""
settings: {delay_seconds: 0, refresh_days: 7, stale_days: 10}
keywords: [microbiome]
sources:
  - {id: jobrxiv, name: jobRxiv, type: rss, feeds: ["https://jobrxiv.example/feed/"], expired_link_pattern: '[?&]p=\\d+'}
""")
    return site, state, cfg


def jobs_of(site):
    return {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}


def test_expired_feed_items_and_pages_are_not_added(env, monkeypatch):  # noqa: F811
    site, state, cfg = setup(env, monkeypatch, {
        "https://jobrxiv.example/feed/": feed(
            ("Assistant Professor, Gut Microbiome", LIVE, LIVE),
            ("Assistant Professor of Neutral Atom Quantum Technologies", QUANTUM, QUANTUM_GUID),
            ("Associate Professor, Soil Microbiome", GONE, GONE)),
        LIVE: page("Assistant Professor, Gut Microbiome", DESC),
        QUANTUM: page("Assistant Professor of Neutral Atom Quantum Technologies", "", expired=True),
        GONE: page("Associate Professor, Soil Microbiome", "", expired=True),
    })
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    jobs = jobs_of(site)
    assert set(jobs) == {"Assistant Professor, Gut Microbiome"}
    assert QUANTUM not in C.opened                      # feed already says it ended: page not opened
    live = jobs["Assistant Professor, Gut Microbiome"]
    assert live["status"] == "open" and live["institution"] == "Example University"
    assert "Related" not in live["summary"] and "Log In" not in live["summary"]
    checked = json.loads((state / "checked.json").read_text())
    assert checked[GONE]["why"] == "listing expired"


def test_related_jobs_box_does_not_make_a_match():
    html = page("Assistant Professor of Neutral Atom Quantum Technologies",
                "We seek a physicist to build neutral-atom quantum processors with optical tweezers. " * 4, jsonld=False)
    d = sources.detail_from_page(html, sources.Entry("jobrxiv", QUANTUM_GUID, "Assistant Professor of Neutral Atom"))
    assert not d.expired and "optical tweezers" in d.description
    assert "microbial" not in d.description.lower() and "For Employers" not in d.description
    assert run._employer(d.employer, "jobRxiv") == ""   # the board's own name is not the employer


def test_known_job_closes_when_its_listing_expires(env, monkeypatch):  # noqa: F811
    site, state, cfg = setup(env, monkeypatch, {
        "https://jobrxiv.example/feed/": feed(("Assistant Professor, Gut Microbiome", LIVE, LIVE)),
        LIVE: page("Assistant Professor, Gut Microbiome", DESC),
    })
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    # The listing ends: the feed now links it as "?p=" but keeps its usual address as the guid.
    C.pages["https://jobrxiv.example/feed/"] = feed(
        ("Assistant Professor, Gut Microbiome", "https://jobrxiv.example/?post_type=job_listing&p=1", LIVE))
    run.run(["--sources", str(cfg), "--today", "2026-11-05"])
    job = jobs_of(site)["Assistant Professor, Gut Microbiome"]
    assert job["status"] == "closed" and job["closed_reason"] == "listing expired"


def test_job_that_left_the_feed_closes_when_its_page_says_expired(env, monkeypatch):  # noqa: F811
    site, state, cfg = setup(env, monkeypatch, {
        "https://jobrxiv.example/feed/": feed(("Assistant Professor, Gut Microbiome", LIVE, LIVE)),
        LIVE: page("Assistant Professor, Gut Microbiome", DESC),
    })
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    C.pages["https://jobrxiv.example/feed/"] = feed()            # dropped off the newest-100 feed
    run.run(["--sources", str(cfg), "--today", "2026-11-06"])
    assert jobs_of(site)["Assistant Professor, Gut Microbiome"]["status"] == "open"   # kept until re-checked
    C.pages[LIVE] = page("Assistant Professor, Gut Microbiome", "", expired=True)
    run.run(["--sources", str(cfg), "--today", "2026-11-11"])    # weekly re-check
    job = jobs_of(site)["Assistant Professor, Gut Microbiome"]
    assert job["status"] == "closed" and job["closed_reason"] == "listing expired"


def test_job_that_left_the_feed_and_cannot_be_checked_does_not_stay_open(env, monkeypatch):  # noqa: F811
    site, state, cfg = setup(env, monkeypatch, {
        "https://jobrxiv.example/feed/": feed(("Assistant Professor, Gut Microbiome", LIVE, LIVE)),
        LIVE: page("Assistant Professor, Gut Microbiome", DESC),
    })
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    C.pages["https://jobrxiv.example/feed/"] = feed()
    C.pages[LIVE] = FetchError("HTTP 403 for page")              # board refuses the re-check
    for day in ("2026-11-11", "2026-11-18", "2026-11-23"):
        run.run(["--sources", str(cfg), "--today", day])
    job = jobs_of(site)["Assistant Professor, Gut Microbiome"]
    assert job["status"] == "closed" and job["closed_reason"] == "not seen recently"


def test_removed_urls_file_takes_a_posting_off_for_good(env, monkeypatch):  # noqa: F811
    site, state, cfg = setup(env, monkeypatch, {
        "https://jobrxiv.example/feed/": feed(("Assistant Professor, Gut Microbiome", LIVE, LIVE)),
        LIVE: page("Assistant Professor, Gut Microbiome", DESC),
    })
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    assert jobs_of(site)
    (state / "removed_urls.txt").write_text(f"# wrongly matched\n{LIVE}   # not a microbiome job\n")
    monkeypatch.setattr(run, "REMOVED_FILE", state / "removed_urls.txt")
    run.run(["--sources", str(cfg), "--today", "2026-11-05"])
    run.run(["--sources", str(cfg), "--today", "2026-11-12"])
    assert jobs_of(site) == {}
