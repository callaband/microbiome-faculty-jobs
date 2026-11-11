import json

from collector.classify import methods
import collector.run as run
from test_european import env  # noqa: F401  (fixture)


def test_bioinformatics_and_multiomics():
    m = methods("Assistant Professor, Microbiome Data Science",
                "We seek a computational biologist who applies machine learning to metagenomic and metabolomic data.")
    assert m["flags"] == ["bioinformatics", "multi_omics"]
    assert m["basis"] == {"bioinformatics": "stated", "multi_omics": "suggested"}
    assert m["omics_layers"] == ["metagenomics", "metabolomics"]
    assert "machine learning" in m["evidence"]["bioinformatics"]


def test_multiomics_named_or_two_layers():
    m = methods("Associate Professor", "Expertise in multi-omics integration is welcome.")
    assert m["basis"] == {"bioinformatics": "suggested", "multi_omics": "stated"}
    m = methods("Professor", "Single-cell RNA-seq of the gut epithelium and proteomics.")
    assert m["basis"] == {"bioinformatics": "suggested", "multi_omics": "suggested"}
    m = methods("Professor", "Metagenomics of soil communities.")          # one layer: not multi-omics,
    assert m["flags"] == ["bioinformatics"] and m["basis"] == {"bioinformatics": "suggested"}  # but implies bioinformatics


def test_suggested_by_wording():
    cases = {
        "Group Leader - Food-Microbiome Modelling and Host-Microbe Interactions": ["bioinformatics"],
        "Faculty position in infectious disease modeling or computational epidemiology": ["bioinformatics"],
        "Assistant Professor in Artificial Intelligence for Animal Improvement. Genomics, data analytics": ["bioinformatics"],
        "Open Rank Professor (Nutrigenomics)": ["bioinformatics"],
        "Research using approaches such as omics, biochemistry and mathematical modelling": ["bioinformatics", "multi_omics"],
        "We use omics approaches to study the coral holobiont.": ["bioinformatics", "multi_omics"],
        "16S rRNA amplicon sequencing of rumen communities": ["bioinformatics"],
    }
    for text, flags in cases.items():
        m = methods("Professor", text)
        assert m["flags"] == flags, text
        assert set(m["basis"].values()) == {"suggested"}, text


def test_not_suggested_by_unrelated_words():
    for text in ("Teaching economics of agriculture; ergonomic lab design.",
                 "Mentor students and serve as a role model.",
                 "Teach introductory microbiology and lead the animal models core."):
        assert methods("Professor of Microbiology", text)["flags"] == [], text


def test_no_flags_and_other_languages():
    assert methods("Professor of Soil Ecology", "Field studies of soil fungi and plant growth.")["flags"] == []
    assert methods("W2-Professur", "Erfahrung in Bioinformatik und Metagenomik")["flags"] == ["bioinformatics"]
    assert methods("准教授", "腸内細菌叢のメタゲノム解析")["basis"] == {"bioinformatics": "suggested"}
    assert methods("助教の公募", "バイオインフォマティクス解析")["flags"] == ["bioinformatics"]


def test_flags_on_collected_jobs_and_backfill(env):  # noqa: F811
    tmp_path, site, state, cfg = env
    run.run(["--sources", str(cfg), "--today", "2026-11-04"])
    jobs = {j["title"]: j for j in json.loads((site / "jobs.json").read_text())}
    assert all("methods" in j for j in jobs.values())
    # An older record without flags gets them from its title and summary when it can't be re-read.
    raw = json.loads((site / "jobs.json").read_text())
    for j in raw:
        for k in ("methods", "method_basis", "omics_layers", "method_evidence", "methods_version"):
            j.pop(k)
        j["summary"] = "Our lab integrates multi-omics data. " + j["summary"]
    (site / "jobs.json").write_text(json.dumps(raw))
    cfg.write_text("settings: {delay_seconds: 0}\nkeywords: [microbiome]\nsources: []\n")
    run.run(["--sources", str(cfg), "--today", "2026-11-05"])
    assert all("multi_omics" in j["methods"] for j in json.loads((site / "jobs.json").read_text()))
    meta = json.loads((site / "meta.json").read_text())
    assert meta["method_labels"] == {"bioinformatics": "Bioinformatics", "multi_omics": "Multi-omics"}
