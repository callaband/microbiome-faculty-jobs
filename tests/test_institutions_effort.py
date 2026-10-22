import json
from pathlib import Path

from collector.effort import find_effort
from collector.institutions import Classifier, classify

ROWS = json.loads((Path(__file__).parent / "fixtures" / "institutions.json").read_text())["institutions"]
CLF = Classifier(ROWS)


def kinds(employer, region, cc="US", city="", desc=""):
    return classify(employer, {"region": region, "country_code": cc, "city": city}, desc, CLF)["types"]


def test_r1_landgrant_by_alias_and_city():
    assert kinds("Example A&M University", "Texas", city="College Station") == ["r1", "landgrant", "med_school"]


def test_department_name_falls_back_to_description():
    t = kinds("Department of Soil Science", "Colorado", desc="Join Example State University in Fort Collins.")
    assert t == ["r1", "landgrant"]


def test_employer_with_department_suffix():
    assert kinds("Example State University Department of Microbiology", "CO")[0] == "r1"


def test_hbcu_and_womens_and_ivy():
    assert "hbcu" in kinds("Example Agricultural and Technical State University", "North Carolina")
    assert kinds("Smith College", "Massachusetts") == ["baccalaureate", "womens"]
    assert "ivy" in kinds("Yale University", "Connecticut")


def test_state_pinned_list_entry():
    # Wheaton College in Illinois is not the historically women's Wheaton (Massachusetts).
    assert "womens" not in kinds("Wheaton College", "Illinois")


def test_pui_masters():
    assert kinds("Example Comprehensive University", "Iowa") == ["masters"]


def test_international_and_institute():
    assert kinds("Institut Exemple de Recherche", "", cc="FR") == ["international", "institute"]
    assert kinds("Some Unlisted College", "Ohio") == ["unknown"]


def test_effort_variants():
    assert find_effort("The appointment is 60% research and 40% teaching.")["split"] == {"research": 60, "teaching": 40}
    assert find_effort("Responsibilities: research (70%), teaching (30%).")["focus"] == "research"
    assert find_effort("a 75/25 research/teaching appointment")["split"] == {"research": 75, "teaching": 25}
    assert find_effort("Appointment: 50% Research, 30% Teaching, 20% Extension.")["label"] == \
        "50% research · 30% teaching · 20% extension"
    assert find_effort("We rank in the top 10% for research funding.")["label"] == ""
    assert find_effort("The position carries a 3-3 teaching load.")["teaching_load"] == "3-3"
    assert find_effort("Nothing about effort.")["focus"] == "unstated"
