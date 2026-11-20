import hashlib
import json

import pandas as pd
import streamlit as st

from pharm.catalog import DOCS, load_json, save_json
from pharm.contracts import DEMO, export_rdf, import_ontology, validate_ontology, validate_schema
from pharm.study import contracts, save_graph
from pharm.workspace import home, persist


def diagram(nodes,edges):
    quote = lambda value: json.dumps(str(value),ensure_ascii=False)
    lines = ["digraph study {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fillcolor="#edf3f0"];']
    lines.extend(f"{quote(n)} [label={quote(n)}];" for n in nodes)
    lines.extend(f"{quote(s)} -> {quote(t)} [label={quote(p)}];" for s,p,t in edges)
    st.graphviz_chart("\n".join(lines+["}"]),width="stretch")


def grid(key,columns,records):
    frame = pd.DataFrame(records,columns=columns).fillna("").astype(str)
    return st.data_editor(frame,key=key,num_rows="dynamic",hide_index=True,width="stretch",
        column_config={k:st.column_config.TextColumn(k) for k in columns}).fillna("").to_dict("records")


def keyed(rows,key,value):
    out = {}
    for row in rows:
        name = row[key].strip()
        if not name or name in out:
            raise ValueError(f"Each {key} must be nonempty and unique.")
        out[name] = value(row)
    return out


def store_contract(kind,value):
    save_json(home()/(kind+".json"),value)
    persist()
    st.session_state[kind+"_revision"] = st.session_state.get(kind+"_revision",0)+1


def load_demo(kind):
    path = DOCS/("feed_schemas.json" if kind=="schema" else "ontology.json")
    store_contract(kind,load_json(path))


def contract_upload(kind,extensions):
    uploaded = st.file_uploader("Upload "+kind,type=extensions,key="upload-"+kind)
    if uploaded:
        token = hashlib.sha256(uploaded.getvalue()).hexdigest()
        if token!=st.session_state.get("loaded-"+kind):
            try:
                data = uploaded.getvalue()
                value = validate_schema(json.loads(data)) if kind=="schema" else import_ontology(uploaded.name,data)
                store_contract(kind,value)
                st.session_state["loaded-"+kind] = token
            except Exception as exc:
                st.error(f"Could not load {kind}. {exc}")
    else:
        st.session_state.pop("loaded-"+kind,None)


def schema_editor():
    path = home()/"schema.json"
    if not path.exists():
        return None
    value = load_json(path)
    rev = str(st.session_state.get("schema_revision",0))
    st.caption("Edit required fields, unit mappings, corrections and criteria. A feed’s optional columns object maps uploaded headers to canonical fields.")
    source = st.text_area("Schema (JSON)",json.dumps(value,indent=2),height=280,key="schema-text-"+rev)
    if st.button("Save schema"):
        try:
            value = validate_schema(json.loads(source))
            store_contract("schema",value)
            st.success("Schema saved.")
        except (TypeError,ValueError,AttributeError) as exc:
            st.error(str(exc))
    st.download_button("Download saved schema",json.dumps(value,indent=2),"schema.json")
    return value


def ontology_editor():
    path = home()/"ontology.json"
    if not path.exists():
        return None
    value = load_json(path)
    rev = str(st.session_state.get("ontology_revision",0))
    hierarchy = value.get("subclasses",[])
    diagram(value["classes"],[(s,p,t) for p,(s,t) in value["predicates"].items()]+[(s,"subclass of",t) for s,t in hierarchy])
    st.caption("Add or remove rows to edit the named classes and relationships. Bind each source relation to a predicate to use it during preprocessing.")
    classes = grid("classes-"+rev,["Class","Label"],[{"Class":k,"Label":v} for k,v in value["classes"].items()])
    preds = grid("predicates-"+rev,["Predicate","Domain","Range"],[dict(Predicate=k,Domain=s,Range=t) for k,(s,t) in value["predicates"].items()])
    parents = grid("hierarchy-"+rev,["Subclass","Parent"],[{"Subclass":s,"Parent":p} for s,p in hierarchy])
    mapping = {role:value.get("bindings",{}).get(role,role if role in value["predicates"] else "") for role in DEMO["predicates"]}
    bindings = st.data_editor(pd.DataFrame([{"Source relation":k,"Predicate":v} for k,v in mapping.items()]),disabled=["Source relation"],hide_index=True,key="bindings-"+rev)
    if st.button("Save ontology"):
        try:
            candidate = dict(value,classes=keyed(classes,"Class",lambda r:r["Label"]),
                predicates=keyed(preds,"Predicate",lambda r:[r["Domain"],r["Range"]]),subclasses=[[r["Subclass"],r["Parent"]] for r in parents],
                bindings=dict(zip(bindings["Source relation"],bindings["Predicate"].fillna(""))))
            value = validate_ontology(candidate)
            store_contract("ontology",value)
            st.success("Ontology saved.")
        except (KeyError,TypeError,ValueError) as exc:
            st.error(str(exc))
    st.download_button("Download saved ontology (Turtle)",export_rdf(value),"ontology.ttl")
    st.download_button("Download ontology and extraction bindings",json.dumps(value,indent=2),"ontology.json")
    return value


def graph_editor(folder,select_build):
    graph = load_json(folder/"graph.json")
    st.caption(f"{len(graph['nodes'])} entities · {len(graph['edges'])} cited relationships · {graph['extraction']}")
    entities = list(graph["nodes"])
    if len(entities)>35:
        focus = st.selectbox("Visualize neighbors of",entities)
        shown = [e for e in graph["edges"] if focus in (e["src"],e["tgt"])]
        nodes = {focus}|{n for e in shown for n in (e["src"],e["tgt"])}
    else:
        nodes,shown = entities,graph["edges"]
    diagram(nodes,[(e["src"],e["predicate"],e["tgt"]) for e in shown])
    with st.expander("Edit knowledge graph"):
        st.caption("Edit entities and relationships together. Each relationship needs a source locator and a supporting assertion.")
        nodes = grid("nodes-"+folder.name,["id","class"],[{"id":k,"class":v} for k,v in graph["nodes"].items()])
        edges = grid("edges-"+folder.name,["id","src","predicate","tgt","batch","text","locator"],graph["edges"])
        if st.button("Save knowledge graph"):
            try:
                changed = dict(graph,nodes=keyed(nodes,"id",lambda r:r["class"]),edges=edges)
                with st.spinner("Saving directed graph and LightRAG projection…"):
                    select_build(save_graph(home(),folder,changed))
                st.rerun()
            except (ValueError,OSError,RuntimeError) as exc:
                st.error(str(exc))
    st.download_button("Download knowledge graph",json.dumps(graph,indent=2),"knowledge-graph.json")
