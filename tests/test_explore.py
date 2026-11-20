import hashlib
from streamlit.testing.v1 import AppTest
from pharm.catalog import DATA, RAW, load_json, rows


def test_manifest_and_inventory():
    catalog = load_json(RAW / "catalog.json")
    assert len(catalog["images"]) == 40 and len(catalog["documents"]) == 6
    assert [len(rows(f)) for f in ("eln","lims","sensor")] == [20,80,2401]
    for path, checksum in load_json(DATA / "manifest.json").items():
        assert hashlib.sha256((RAW / path).read_bytes()).hexdigest() == checksum


def test_raw_page():
    page = AppTest.from_file(DATA.parent / "app.py", default_timeout=30).run()
    assert not page.exception
    assert page.title[0].value == "Explore raw data"
    assert not page.dataframe
    page.button(key="explore-demo").click().run()
    assert len(page.dataframe[0].value) == 4
    page.selectbox[0].select("B-020")
    page.radio[0 if page.radio[0].label == "Export" else 1].set_value("Sensor").run()
    assert not page.exception
    assert len(page.dataframe[0].value) == 120
    assert page.info[0].value == "This batch has no standalone lab report."


def test_upload_then_switch_to_demo():
    page = AppTest.from_file(DATA.parent/"app.py", default_timeout=30).run()
    page.file_uploader[0].upload("lims.csv", b"id,batch,test\nR1,Lot-X,Assay\n").run()
    page.button(key="explore-load").click().run()
    assert not page.exception
    assert list(page.dataframe[0].value.batch)==["Lot-X"]
    page.button(key="explore-demo").click().run()
    assert len(page.dataframe[0].value)==4

