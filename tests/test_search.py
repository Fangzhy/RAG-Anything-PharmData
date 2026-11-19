from streamlit.testing.v1 import AppTest

from pharm.catalog import DATA
from pharm.prepare import active
from pharm.retrieval import graph_search, sql_search, vector_search


def test_modalities_and_endpoints():
    folder = active()
    image = (DATA / "evaluation/query-chipped.png").read_bytes()
    matches = vector_search(folder,"",image)
    assert any(x["kind"]=="image" and "chipped" in x["text"] for x in matches)
    assert any(x["kind"] in ("note","passage") for x in matches)
    for weight,channels in [(1,{"text"}),(0,{"visual"}),(.5,{"text","visual"})]:
        hits = vector_search(folder,"chipped tablet",image,"B-001",weight)
        assert {x["batch"] for x in hits} == {"B-001"}
        assert {c for x in hits for c in x["channel"].split(" + ") if c != "linked by sample"} == channels
    assert any(x["kind"]=="passage" for x in vector_search(folder,"temperature excursion",batch="B-001",weight=1))


def test_structured_paths():
    assert {x["batch"] for x in sql_search(active(),"Which batches had low dissolution?")} == {"B-001"}
    assert all(r["batch"]=="B-001" for r in graph_search(active(),"chipped",batch="B-001"))
    assert any("hasObservation" in r["text"] for r in graph_search(active(),"chipped",batch="B-001"))
    assert sql_search(active(),"press force in B-001")[0]["kind"]=="interval"


def test_search_page():
    page = AppTest.from_file(DATA.parent/"app.py",default_timeout=60).run()
    page.sidebar.radio[0].set_value("Search evidence").run()
    page.radio[0].set_value("SQL")
    page.text_input[0].set_value("low dissolution")
    page.button[0].click().run()
    assert not page.exception
    assert any("72.5%" in x.value for x in page.markdown)
    page.radio[0].set_value("Graph")
    page.text_input[0].set_value("inspection of B-001")
    page.button[0].click().run()
    assert not page.exception
    assert any("hasObservation" in x.value for x in page.markdown)
