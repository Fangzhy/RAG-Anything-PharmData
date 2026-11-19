import json
from contextlib import closing

from streamlit.testing.v1 import AppTest

from pharm.catalog import DATA, load_json
from pharm.prepare import active
from pharm.validation import FEEDS, load_database, read_db


def test_double_validation_and_quarantine(tmp_path):
    expected = load_json(DATA / "evaluation/expected.json")
    for path in (tmp_path / "replay.sqlite", active() / "study.sqlite"):
        if not path.exists():
            load_database(path)
        with closing(read_db(path)) as db:
            for feed in FEEDS:
                for status in ("corrected","quarantined"):
                    actual = db.execute("SELECT * FROM audit WHERE feed=? AND status=?", (feed,status.title())).fetchall()
                    assert {r["id"] for r in actual} == set(expected[feed][status])
                    for r in actual:
                        assert json.loads(r["initial_errors"])
                        assert bool(json.loads(r["final_errors"])) == (status == "quarantined")
                        if status == "quarantined":
                            assert not db.execute(f"SELECT 1 FROM {feed} WHERE locator=?", (r["locator"],)).fetchone()
                assert db.execute(f"SELECT COUNT(*) FROM {feed}").fetchone()[0] == db.execute("SELECT COUNT(*) FROM audit WHERE feed=? AND status IN ('Accepted','Corrected')",(feed,)).fetchone()[0]
            assert db.execute("SELECT count(*) FROM audit WHERE status='Duplicate'").fetchone()[0] == 1
            assert [r[0] for r in db.execute("SELECT DISTINCT batch FROM lims WHERE method='D30' AND value<80")] == ["B-001"]


def test_processing_page():
    page = AppTest.from_file(DATA.parent / "app.py", default_timeout=60).run()
    page.sidebar.radio[0].set_value("Process data").run()
    assert not page.exception
    page.selectbox[0].select("lims").run()
    page.radio[0].set_value("Quarantined").run()
    assert not page.exception
    assert any("excluded" in item.value for item in page.info)
    assert [m.value for m in page.metric] == ["64","12","4","0"]
    assert len(page.dataframe[0].value) > 100
