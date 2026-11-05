"""Non-English postings: language detection, translation, JREC-IN, and weekly back-off."""

import json

import pytest
import requests

import collector.run as run
import collector.translate as tr
from collector.classify import rank_label, ranks
from collector.http import FetchError
from collector.sources import Entry, parse_jrecin
from test_european import env  # noqa: F401  (fixture)
from test_european import PAGES, Client

JREC_PAGE = """<html><body><header>JREC-IN</header><main>
<h2>求人公募情報閲覧</h2>
<div>募集中</div><div>更新日 : 2026年10月13日</div><div>募集終了日 : 2026年12月25日</div>
<div>勤務地 :</div><div>関東 - 東京都</div>
<div>公開開始日 : 2026年10月13日</div>
<div>口腔微生物学講座 助教の公募</div><div>D126999001</div><div>私立大学</div><div>例示医科大学</div>
<div>業務内容</div><div>口腔マイクロバイオームと全身免疫系の相互作用を研究する。学部生の講義を担当する。</div>
<div>職種</div><div>助教相当</div>
<div>雇用形態</div><div>正職員・正社員</div>
<div>契約期間</div><div>任期あり テニュアトラック以外</div>
<div>応募方法</div><div>電子メール応募</div><div>連絡先</div><div>example(at)example.ac.jp</div>
</main></body></html>"""


def test_detect():
    assert tr.detect("口腔微生物学講座助教の公募") == "ja"
    assert tr.detect("微生物组研究副教授招聘") == "zh"
    assert tr.detect("마이크로바이옴 연구 조교수 채용") == "ko"
    assert tr.detect("Assistant Professor of Microbiology") == "en"
    assert tr.detect("Assistant Professor, Microbiome Science. The department invites applications for a tenure-track position.") == "en"
    assert tr.detect("Die Universität sucht eine Professorin oder einen Professor für Mikrobiomforschung. Die Stelle ist unbefristet.") in ("de", "en")


def test_parse_jrecin():
    d = parse_jrecin(JREC_PAGE, Entry("jrecin", "https://j.example/seek/SeekJorDetail?id=D126999001", ""))
    assert d.title == "口腔微生物学講座 助教の公募" and d.employer == "例示医科大学"
    assert d.country_code == "JP" and d.region == "東京都"
    assert str(d.application_due) == "2026-12-25" and str(d.date_posted) == "2026-10-13"
    assert d.extra["rank_hint"] == "助教相当" and d.job_type == "Faculty"
    assert "マイクロバイオーム" in d.description and "連絡先" not in d.description  # contact details left out
    assert rank_label(ranks(d.title + " " + d.extra["rank_hint"], "")) == "Assistant"


class FakeProvider:
    name = "Test translator"
    calls = 0

    def translate(self, texts, src):
        FakeProvider.calls += 1
        table = {"口腔微生物学講座 助教の公募": "Recruitment of an Assistant Professor, Department of Oral Microbiology"}
        return [table.get(t, "We study how the oral microbiome interacts with the immune system. "
                             "Lecturing undergraduates. Fixed-term, not tenure-track.") for t in texts]


@pytest.fixture
def jrec_env(env, monkeypatch):  # noqa: F811
    tmp_path, site, state, cfg = env
    monkeypatch.setattr(tr, "CACHE_FILE", state / "translations.json")
    monkeypatch.delenv("MFJ_NO_TRANSLATION", raising=False)
    monkeypatch.setattr(tr, "Argos", lambda: FakeProvider())
    FakeProvider.calls = 0
    search = "https://j.example/seek/SeekJorSearch?fn=0&keyword_and=%E3%83%9E%E3%82%A4%E3%82%AF%E3%83%AD%E3%83%90%E3%82%A4%E3%82%AA%E3%83%BC%E3%83%A0"
    PAGES[search] = ('<a href="SeekJorDetail?id=D126999001">口腔微生物学講座 助教の公募</a>'
                     '<a href="SeekJorDetail?id=D126999002">ポスドク研究員募集</a>')
    PAGES["https://j.example/seek/SeekJorDetail?id=D126999001"] = JREC_PAGE
    cfg.write_text("""
settings: {delay_seconds: 0}
keywords: [microbiome]
sources:
  - {id: jrecin, name: JREC-IN Portal, type: jrecin, base: "https://j.example", keywords: ["マイクロバイオーム"]}
""")
    yield tmp_path, site, state, cfg
    for k in [k for k in PAGES if k.startswith("https://j.example")]:
        PAGES.pop(k)


def test_japanese_posting_is_translated_and_marked(jrec_env):
    tmp_path, site, state, cfg = jrec_env
    assert run.run(["--sources", str(cfg), "--today", "2026-11-04"]) == 0
    [job] = json.loads((site / "jobs.json").read_text())
    assert job["title"] == "Recruitment of an Assistant Professor, Department of Oral Microbiology"
    assert job["original_title"] == "口腔微生物学講座 助教の公募"
    assert job["translated"] == {"from": "ja", "language": "Japanese", "by": "Test translator"}
    assert job["summary"].startswith("We study how the oral microbiome")
    assert job["rank_label"] == "Assistant" and job["tenure_label"] == "Non-tenure-track"
    assert job["deadline"] == "2026-12-25" and job["location"]["country"] == "Japan"
    assert not any("D126999002" in u for u in Client.opened)  # postdoc title never opened
    # The translation is cached: a later re-check doesn't translate again.
    calls = FakeProvider.calls
    run.run(["--sources", str(cfg), "--today", "2026-11-12"])
    assert FakeProvider.calls == calls


def test_without_translation_posting_is_kept_in_original_language(jrec_env, monkeypatch):
    tmp_path, site, state, cfg = jrec_env
    monkeypatch.setenv("MFJ_NO_TRANSLATION", "1")
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    [job] = json.loads((site / "jobs.json").read_text())
    assert job["title"] == "口腔微生物学講座 助教の公募" and job["translated"] is None and job["language"] == "ja"
    assert job["rank_label"] == "Assistant"


def test_refusing_source_backs_off_to_weekly(env, monkeypatch):  # noqa: F811
    tmp_path, site, state, cfg = env
    real_get = Client.get

    def refuse_euraxess(self, url, **kw):
        if "euraxess" in url:
            Client.opened.append(url)
            raise FetchError("HTTP 403 for " + url)
        return real_get(self, url, **kw)

    monkeypatch.setattr(Client, "get", refuse_euraxess)
    for day in ("2026-11-04", "2026-11-05", "2026-11-06"):
        run.run(["--sources", str(cfg), "--today", day])
    meta = {s["id"]: s for s in json.loads((site / "meta.json").read_text())["sources"]}
    assert meta["euraxess"]["fail_days"] == 3
    run.run(["--sources", str(cfg), "--today", "2026-11-07"])            # skipped: tried 1 day ago
    assert not any("euraxess" in u for u in Client.opened)
    meta = {s["id"]: s for s in json.loads((site / "meta.json").read_text())["sources"]}
    assert "next try Nov 13" in meta["euraxess"]["note"]
    run.run(["--sources", str(cfg), "--today", "2026-11-13"])            # a week later: tried again
    assert any("euraxess" in u for u in Client.opened)
