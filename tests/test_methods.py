import json

from collector.classify import methods
import collector.run as run
from test_european import env  # noqa: F401  (fixture)


def test_bioinformatics_and_multiomics():
    m = methods("Assistant Professor, Microbiome Data Science",
                "We seek a computational biologist who applies machine learning to metagenomic and metabolomic data.")
    assert m["flags"] == ["bioinformatics", "multi_omics"]
    assert m["omics_layers"] == ["metagenomics", "metabolomics"]
    assert "machine learning" in m["evidence"]["bioinformatics"]


def test_multiomics_named_or_two_layers():
    assert methods("Associate Professor", "Expertise in multi-omics integration is welcome.")["flags"] == ["multi_omics"]
    assert methods("Professor", "Single-cell RNA-seq of the gut epithelium and proteomics.")["flags"] == ["multi_omics"]
    assert methods("Professor", "Metagenomics of soil communities.")["flags"] == []   # one layer only


def test_no_flags_and_other_languages():
    assert methods("Professor of Soil Ecology", "Field studies of soil fungi and plant growth.")["flags"] == []
    assert methods("W2-Professur", "Erfahrung in Bioinformatik und Metagenomik")["flags"] == ["bioinformatics"]
    assert methods("助教の公募", "バイオインフォマティクス解析")["flags"] == ["bioinformatics"]


def test_flags_on_collected_jobs_and_backfill(env):  # noqa: F811
    tmp_path, site, state, cfg = env
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
    assert all("methods" in j for j in jobs.values())
    # An older record without flags gets them from its title and summary when it can't be re-read.
    raw = json.loads((site / "jobs.json").read_text())
    for j in raw:
        j.pop("methods"), j.pop("omics_layers"), j.pop("method_evidence")
        j["summary"] = "Our lab integrates multi-omics data. " + j["summary"]
    (site / "jobs.json").write_text(json.dumps(raw))
    cfg.write_text("settings: {delay_seconds: 0}\nkeywords: [microbiome]\nsources: []\n")
    run.run(["--sources", str(cfg), "--today", "2026-11-05"])
    assert all("multi_omics" in j["methods"] for j in json.loads((site / "jobs.json").read_text()))
    meta = json.loads((site / "meta.json").read_text())
    assert meta["method_labels"] == {"bioinformatics": "Bioinformatics", "multi_omics": "Multi-omics"}
