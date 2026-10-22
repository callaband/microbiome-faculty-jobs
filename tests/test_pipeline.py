"""End-to-end run against fictional fixtures (no network)."""

import json
from pathlib import Path

import requests

import collector.geo as geo
import collector.institutions as inst
import collector.run as run
from collector.http import FetchError

FIX = Path(__file__).parent / "fixtures"
ROUTES = {
    "https://board.example/jobsrss/?keywords=microbiome": "madgex_rss.xml",
    "https://board.example/job/1001/assistant-professor-soil/": "madgex_job_1001.html",
    "https://board.example/job/1002/group-leader-marine/": "madgex_job_1002.html",
    "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=51": "hej_rss.xml",
    "https://www.higheredjobs.com/details.cfm?JobCode=2001": "hej_job_2001.html",
    "https://www.higheredjobs.com/details.cfm?JobCode=2002": "hej_job_2002.html",
    "https://www.higheredjobs.com/details.cfm?JobCode=2004": "hej_job_2004.html",
}


class FakeClient:
    requests_made = 0
    opened: list = []

    def __init__(self, *a, **k):
        FakeClient.opened = []

    def get(self, url, **_):
        FakeClient.opened.append(url)
        if url not in ROUTES:
            raise FetchError(f"HTTP 404 for {url}")
        r = requests.Response()
        r.status_code, r._content, r.encoding = 200, (FIX / ROUTES[url]).read_bytes(), "utf-8"
        return r


def test_pipeline(tmp_path, monkeypatch):
    site, state = tmp_path / "docs" / "data", tmp_path / "data"
    for name, val in {"JOBS_FILE": site / "jobs.json", "META_FILE": site / "meta.json",
                      "CSV_FILE": site / "jobs.csv", "FEED_FILE": tmp_path / "docs" / "feed.xml",
                      "CHECKED_FILE": state / "checked.json", "SUBMITTED_FILE": state / "none.txt",
                      "SITE_DATA_DIR": site}.items():
        monkeypatch.setattr(run, name, val)
    monkeypatch.setattr(geo, "CACHE_FILE", state / "geocache.json")
    monkeypatch.setattr(inst, "DIRECTORY_FILE", FIX / "institutions.json")
    monkeypatch.setattr(run, "PoliteClient", FakeClient)
    monkeypatch.setenv("OFFLINE", "1")
    cfg = tmp_path / "sources.yaml"
    cfg.write_text("""
settings: {delay_seconds: 0, max_pages: 1}
keywords: [microbiome]
sources:
  - {id: board, name: Example Board, type: madgex, base: https://board.example}
  - {id: higheredjobs, name: HigherEdJobs, type: hej_category, base: https://www.higheredjobs.com, categories: {51: Animal Science}}
""")
    assert run.run(["--sources", str(cfg), "--today", "2026-10-22"]) == 0
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}

    assert set(jobs) == {
        "Assistant Professor of Soil Microbial Ecology",
        "Group Leader - Marine Holobionts",
        "Open Rank Professor - Animal Microbiome and One Health",
        "Clinical Assistant Professor - Veterinary Microbiology",
    }
    # Postdoc and farm manager pages are never opened.
    assert not any("1003" in u or "2003" in u for u in FakeClient.opened)

    soil = jobs["Assistant Professor of Soil Microbial Ecology"]
    assert soil["rank_label"] == "Assistant" and soil["tenure_label"] == "Tenure-track"
    assert {"soil", "agriculture"} <= set(soil["domains"])
    assert soil["review_date"] == "2026-11-01" and soil["priority"] == "soon"
    assert soil["location"]["country_code"] == "US"
    assert soil["inst_types"] == ["r1", "landgrant"] and soil["control"] == "Public"
    assert soil["effort"] == {"research": 60, "teaching": 40} and soil["effort_focus"] == "research"
    assert soil["location"]["lat"] == 40.57  # campus coordinates from the directory

    marine = jobs["Group Leader - Marine Holobionts"]
    assert marine["location"]["country"] == "France" and marine["location"]["world_region"] == "Europe"
    assert "ocean" in marine["domains"] and marine["tenure_label"] == "Permanent / continuing"
    assert marine["review_date"] == "2026-11-30" and marine["deadline"] == "2027-01-15"

    animal = jobs["Open Rank Professor - Animal Microbiome and One Health"]
    assert animal["rank_label"] == "Open rank" and animal["priority"] == "low"
    assert "animal_health" in animal["domains"] and animal["deadline"] == "2027-01-15"
    assert animal["inst_types"] == ["r1", "landgrant", "med_school", "vet_school"] and animal["effort_focus"] == "unstated"

    vet = jobs["Clinical Assistant Professor - Veterinary Microbiology"]
    assert vet["tenure_label"] == "Non-tenure-track" and vet["location"]["country_code"] == "QA"
    assert vet["inst_types"] == ["international"] and vet["teaching_load"] == "3-3"
    assert marine["inst_types"] == ["international", "institute"]

    meta = json.loads((site / "meta.json").read_text())
    assert meta["counts"]["open"] == 4 and all(s["ok"] for s in meta["sources"])
    assert (tmp_path / "docs" / "feed.xml").read_text().count("<entry>") == 4
