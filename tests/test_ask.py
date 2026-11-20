import itertools
import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from pharm.answers import Investigation, answer, collect, supported_answer
from pharm.catalog import DATA
from pharm.prepare import active
from pharm.provider import ProviderUnavailable
from pharm.retrieval import OPENING, SOURCES


def test_seven_source_masks():
    req = Investigation(OPENING,batch="B-001")
    for size in (1,2,3):
        for subset in itertools.combinations(SOURCES,size):
            records = collect(active(),req,subset)
            assert {r["source"] for r in records} == set(subset)
            assert len(records)==len({r["id"] for r in records})


async def cited_response(prompt, **kwargs):
    items = json.loads(prompt)["evidence"]
    return json.dumps({"claims":[{"text":items[0]["text"],"citations":[items[0]["id"]]}],"gaps":[]})


def test_lightrag_synthesis():
    result = answer(active(),Investigation("low dissolution"),["SQL"],llm=cited_response)
    assert not result["error"],result["error"]
    assert "72.5%" in result["claims"][0]["text"]
    with pytest.raises(ProviderUnavailable):
        supported_answer('{"claims":[{"text":"Missing","citations":["unknown"]}]}', result["records"])
    with pytest.raises(ProviderUnavailable):
        supported_answer(json.dumps({"claims":[{"text":"The result was 55%.","citations":[result["records"][0]["id"]]}]}),result["records"])


def test_ask_page():
    with patch("pharm.answers.completion", cited_response),patch("pharm.answers.settings",return_value=("demo","test-model")):
        page = AppTest.from_file(DATA.parent/"app.py", default_timeout=60).run()
        page.sidebar.radio[0].set_value("Ask a question").run()
        page.multiselect[0].set_value(["SQL"])
        page.button(key="ask-demo-image").click().run()
        assert page.session_state["ask-demo-selected"]
        next(b for b in page.button if b.label=="Generate answer").click().run()
        assert not page.exception and not page.warning
        assert page.session_state.ask_result["claims"][0]["citations"][0].startswith("SQL-")
        page.multiselect[0].set_value([]).run()
        assert next(b for b in page.button if b.label=="Generate answer").disabled
