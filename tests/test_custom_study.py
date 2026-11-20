import json
from contextlib import closing
from unittest.mock import patch

from rdflib import Graph
from streamlit.testing.v1 import AppTest

from pharm.catalog import DATA,DOCS,RAW,load_json
from pharm.contracts import export_rdf,import_ontology
from pharm.study import process_inputs,save_graph
from pharm.validation import read_db
from pharm.workspace import import_files


TTL = b"""@prefix : <urn:lab:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Specimen a owl:Class . :Material a owl:Class . :Specimen rdfs:subClassOf :Material .
:Finding a owl:Class . :measured a owl:ObjectProperty ; rdfs:domain :Specimen ; rdfs:range :Finding .
"""


def test_owl_xml_and_turtle_edit_roundtrip():
    xml = Graph().parse(data=TTL,format="turtle").serialize(format="xml",encoding="utf-8")
    for name,data in (("terms.ttl",TTL),("terms.owl",xml)):
        onto = import_ontology(name,data)
        assert onto["predicates"]=={"measured":["Specimen","Finding"]}
        assert onto["subclasses"]==[["Specimen","Material"]]
        onto["classes"]["Finding"]="Observed result"
        onto["subclasses"]=[]
        again=import_ontology("edited.ttl",export_rdf(onto).encode())
        assert again["classes"]["Finding"]=="Observed result"
        assert again["subclasses"]==[]


def test_uploaded_stages_and_graph_save(tmp_path):
    csv = b"id,lot,sample,test,value,unit,method,time_min,timestamp,reviewer\nR1,Lot-X,Spec-X,Dissolution,76,%,D30,30,2026-05-01T08:00:00Z,K\nR2,Lot-X,Spec-X,Dissolution,79,%,D30,30,2026-05-01T08:00:00Z,\n"
    doc = next((RAW/"reports").glob("*.docx"))
    image = DATA/"evaluation/query-chipped.png"
    raw = import_files(tmp_path/"raw",None,[("test.csv",csv),(doc.name,doc.read_bytes()),(image.name,image.read_bytes())],"LIMS","Lot-X","Spec-X")
    schema=load_json(DOCS/"feed_schemas.json")
    schema["lims"]["columns"]={"lot":"batch"}
    schema["lims"]["required"].append("reviewer")
    onto=import_ontology("study.ttl",TTL)
    onto["bindings"]={"hasResult":"measured"}
    applied=process_inputs(tmp_path,raw,schema,onto)
    with closing(read_db(applied/"study.sqlite")) as db:
        assert [tuple(r) for r in db.execute("SELECT id,status FROM audit ORDER BY id")]==[("R1","Accepted"),("R2","Quarantined")]
    graph=load_json(applied/"graph.json")
    assert graph["edges"][0]["predicate"]=="measured"
    graph["nodes"]["extra"]="Specimen"
    graph["edges"][0]["text"]="Reviewed source row R1"
    edited=save_graph(tmp_path,applied,graph)
    built=process_inputs(tmp_path,raw,schema,onto,embed=True,previous=edited)
    items=load_json(built/"items.json")
    assert any(i["kind"]=="passage" for i in items["text"])
    assert any(i["kind"]=="image" and i["sample"]=="Spec-X" for i in items["visual"])
    assert load_json(built/"graph.json")["nodes"]["extra"]=="Specimen"
    assert load_json(built/"graph.json")["edges"][0]["text"]=="Reviewed source row R1"


def test_processing_contract_controls():
    page=AppTest.from_file(DATA.parent/"app.py",default_timeout=90).run()
    page.sidebar.radio[0].set_value("Preprocess data").run()
    page.button(key="process-demo").click().run()
    next(b for b in page.button if b.label=="Use demo schema").click().run()
    page.file_uploader(key="upload-ontology").upload("lab.ttl",TTL).run()
    assert not page.exception and not page.error
    schema=json.loads(page.text_area[0].value)
    schema["lims"]["required"].append("reviewed")
    page.text_area[0].set_value(json.dumps(schema))
    next(b for b in page.button if b.label=="Save schema").click().run()
    assert not page.exception
    assert "reviewed" in load_json(page.session_state.study_workspace/"schema.json")["lims"]["required"]
    next(b for b in page.button if b.label=="Run pipeline to apply schema and ontology").click().run()
    assert not page.exception and not page.error
    assert not next(b for b in page.button if b.label=="Run pipeline to apply parse and embed").disabled


def test_reopen_local_study_and_use_it_on_all_retrieval_pages(tmp_path):
    with patch("pharm.workspace.DATA",tmp_path), patch("pharm.workspace.local_app",return_value=True):
        page=AppTest.from_file(DATA.parent/"app.py",default_timeout=90).run()
        content=b"id,batch,sample,test,value,unit,method,time_min,timestamp\nX1,Lot-X,S-X,Dissolution,62,%,D30,30,2026-03-01T08:00:00Z\n"
        page.file_uploader[0].upload("lims.csv",content).run()
        page.button(key="explore-load").click().run()
        page.sidebar.radio[0].set_value("Preprocess data").run()
        next(b for b in page.button if b.label=="Use demo schema").click().run()
        next(b for b in page.button if b.label=="Use demo ontology").click().run()
        next(b for b in page.button if b.label=="Run pipeline to apply schema and ontology").click().run()
        assert not page.error and not page.exception
        resumed=AppTest.from_file(DATA.parent/"app.py",default_timeout=90)
        resumed.query_params.update(page.query_params)
        resumed.run()
        assert resumed.session_state.study_build==page.session_state.study_build
        for route in ("Search data","Chat & Compare"):
            resumed.sidebar.radio[0].set_value(route).run()
            assert not resumed.exception
            assert resumed.selectbox[0].options==["All batches","Lot-X"]
            if route=="Search data":
                resumed.radio[0].set_value("SQL")
                resumed.text_input[0].set_value("low dissolution")
                next(b for b in resumed.button if b.label=="Search").click().run()
                assert [r["id"] for r in resumed.session_state.search_result[1]]==["SQL-X1"]
