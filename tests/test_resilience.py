"""A slow, failing or broken source must not stop the run or lose what other sources found."""

import json

import pytest

import collector.run as run
import collector.sources as sources
from collector.http import FetchError
from test_european import PAGES, Client, env  # noqa: F401  (fixture)


class DeadSiteSource:
    """Lists 30 jobs whose pages always time out."""
    def __init__(self, cfg, settings, keywords, client):
        self.id, self.name, self.cfg = cfg["id"], cfg["name"], cfg
        self.calls = 0

    def list_entries(self):
        return [sources.Entry(self.id, f"https://dead.example/job/{i}", "Assistant Professor of Microbiome Science")
                for i in range(30)]

    def fetch_detail(self, entry):
        DeadSiteSource.calls = getattr(DeadSiteSource, "calls", 0) + 1
        raise FetchError("timed out to dead.example (ReadTimeout)")


class BrokenSource(DeadSiteSource):
    def list_entries(self):
        raise ValueError("unexpected page layout")


def write_cfg(cfg_path, extra_settings="", extra_sources=""):
    cfg_path.write_text(f"""
settings: {{delay_seconds: 0{extra_settings}}}
keywords: [microbiome]
sources:
{extra_sources}
  - {{id: jobs_ac_uk, name: jobs.ac.uk, type: listing, base: "https://www.jobs.ac.uk",
     urls: ["/search/?keywords={{keyword}}&sortOrder=1&pageSize=100"], link_pattern: '/job/[A-Z0-9]{{5,}}/[a-z0-9\\\\-]+'}}
""")


@pytest.fixture
def kinds(monkeypatch):
    orig = sources.build_sources

    def build(cfg, client, submitted):
        out = []
        for s in cfg["sources"]:
            if s["type"] == "dead":
                out.append(DeadSiteSource(s, {}, [], client))
            elif s["type"] == "broken":
                out.append(BrokenSource(s, {}, [], client))
            else:
                out += orig({**cfg, "sources": [s]}, client, [])
        return out
    monkeypatch.setattr(run, "build_sources", build)


def test_dead_site_is_stopped_and_others_still_saved(env, kinds):
    tmp_path, site, state, cfg = env
    DeadSiteSource.calls = 0
    write_cfg(cfg, extra_sources="  - {id: dead, name: Dead board, type: dead}\n  - {id: broken, name: Broken board, type: broken}")
    assert run.run(["--sources", str(cfg), "--today", "2026-11-04"]) == 0
    meta = {s["id"]: s for s in json.loads((site / "meta.json").read_text())["sources"]}
    assert DeadSiteSource.calls == 8                              # stopped after 8 failures in a row
    assert not meta["dead"]["ok"] and "8 failed requests in a row" in meta["dead"]["error"]
    assert not meta["broken"]["ok"] and meta["broken"]["error"].startswith("internal error")
    assert meta["jobs_ac_uk"]["ok"]                               # later sources still ran
    titles = {j["title"] for j in json.loads((site / "jobs.json").read_text())}
    assert "Lecturer in Microbiome Science" in titles


def test_source_time_limit_pauses_and_run_finishes(env, kinds):
    tmp_path, site, state, cfg = env
    write_cfg(cfg, extra_settings=", source_minutes: 0.000000001")
    assert run.run(["--sources", str(cfg), "--today", "2026-11-04"]) == 0
    meta = {s["id"]: s for s in json.loads((site / "meta.json").read_text())["sources"]}
    assert meta["jobs_ac_uk"]["ok"] and "time limit" in meta["jobs_ac_uk"]["note"]
