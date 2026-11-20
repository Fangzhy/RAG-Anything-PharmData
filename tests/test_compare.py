import json
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from pharm.answers import Investigation
from pharm.catalog import DATA, load_json
from pharm.compare import compare, evidence_sets
from pharm.prepare import active
from pharm.provider import ProviderUnavailable
from pharm.retrieval import OPENING, SOURCES


async def summarize(prompt, **kwargs):
    items = json.loads(prompt)["evidence"]
    chosen = [items[0]]
    if any(r["source"] == "Vector" for r in items):
        chosen.append(next(r for r in items if r["source"]=="Vector" and "chipped" in r["text"]))
    return json.dumps({"claims":[dict(text=r["text"],citations=[r["id"]]) for r in chosen],"gaps":[]})


def test_exact_source_diff_and_missing_result():
    with patch("pharm.answers.completion",summarize),patch("pharm.answers.settings",return_value=("test","free-model")):
        result = compare(active(),Investigation(OPENING),["SQL"],SOURCES)
        panels = result["panels"]
        assert not any(p["error"] for p in panels)
        shared, left, right = evidence_sets(panels)
        assert shared and not left and right
        assert all(x.startswith("SQL-") for x in shared)
        assert any("chipped" in c["text"] for c in panels[1]["claims"])
        missing = load_json(DATA/"evaluation/expected.json")["lims"]["quarantined"][0].removesuffix("-D30")
        panels = compare(active(),Investigation(f"dissolution for {missing}"),["SQL"],["SQL"])["panels"]
        assert all(p["gaps"] and not p["claims"] for p in panels)


def test_page_preserves_success_and_retries_failed_side():
    calls = []
    async def fail_once(prompt,**kwargs):
        calls.append(prompt)
        if len(calls) == 2:
            raise ProviderUnavailable("OpenRouter returned HTTP 429. Retrieved evidence is available.")
        return await summarize(prompt,**kwargs)

    with patch("pharm.answers.completion",fail_once),patch("pharm.answers.settings",return_value=("test","free-model")):
        page = AppTest.from_file(DATA.parent/"app.py",default_timeout=90).run()
        page.sidebar.radio[0].set_value("Chat & Compare").run()
        question = "Which batches had low dissolution and chipped tablets?"
        page.text_input[0].set_value(question)
        page.toggle[0].set_value(True).run()
        assert page.text_input[0].value == question
        assert [s.label for s in page.multiselect] == ["Left sources", "Right sources"]
        page.button(key="compare-demo-image").click().run()
        next(b for b in page.button if b.label=="Run comparison").click().run()
        assert page.session_state.comparison["request"].image==(DATA/"evaluation/query-chipped.png").read_bytes()
        assert not page.exception and len(calls)==2
        first, second = page.session_state.comparison["panels"]
        assert first["claims"] and second["error"] and second["records"]
        page.button(key="retry-1").click().run()
        assert not page.exception
        retried = page.session_state.comparison["panels"]
        assert retried[0]==first and retried[1]["claims"] and len(calls)==3
