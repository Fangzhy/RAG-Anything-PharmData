"""Import and validate the editable contracts used by the study pipeline."""
import json
from collections import Counter
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from pharm.catalog import DOCS, load_json

DEMO = load_json(DOCS/"ontology.json")
FEEDS = ("eln","lims","sensor")


def string_map(value):
    return isinstance(value,dict) and all(isinstance(k,str) and k.strip() and isinstance(v,str) for k,v in value.items())


def validate_schema(schema):
    if not isinstance(schema,dict) or not isinstance(schema.get("version"),str):
        raise ValueError("Include a schema version string.")
    for feed in FEEDS:
        rule = schema.get(feed,{})
        fields = rule.get("required") if isinstance(rule,dict) else None
        if not isinstance(fields,list) or not all(isinstance(k,str) and k.strip() for k in fields) or len(fields)!=len(set(fields)):
            raise ValueError(f"{feed}.required must be a list of distinct field names.")
        if not string_map(rule.get("columns",{})) or (feed!="eln" and not string_map(rule.get("units"))):
            raise ValueError(f"Check the {feed} column and unit mappings.")
        correction = schema.get("corrections",{}).get(feed,{})
        if correction and (not isinstance(correction,dict) or not isinstance(correction.get("field"),str) or not string_map(correction.get("aliases",{}))):
            raise ValueError(f"Invalid correction rule for {feed}.")
    criteria = schema.get("criteria")
    if not isinstance(criteria,dict) or not all(isinstance(r,dict) and r.get("method")==key and isinstance(r.get("test"),str) and isinstance(r.get("unit"),str) and isinstance(r.get("time_min"),(int,float)) and (r.get("lower_bound") is None or isinstance(r["lower_bound"],(int,float))) for key,r in criteria.items()):
        raise ValueError("Criteria need a method matching the key, test, unit, numeric time_min and optional numeric lower_bound.")
    return schema


def validate_ontology(onto):
    if not isinstance(onto,dict) or not string_map(onto.get("classes")) or not onto["classes"]:
        raise ValueError("Define at least one named ontology class.")
    predicates = onto.get("predicates")
    if not isinstance(predicates,dict):
        raise ValueError("Define a predicates object.")
    for name,ends in predicates.items():
        if not name.strip() or not isinstance(ends,list) or len(ends)!=2 or any(e not in onto["classes"] for e in ends):
            raise ValueError(f"{name} requires two declared endpoint classes.")
    for pair in onto.get("subclasses",[]):
        if not isinstance(pair,list) or len(pair)!=2 or any(n not in onto["classes"] for n in pair):
            raise ValueError("Subclass relationships need two declared classes.")
    for role,name in onto.get("bindings",{}).items():
        if role not in DEMO["predicates"] or (name and name not in predicates):
            raise ValueError(f"Unknown extraction binding for {role}.")
    return onto


def import_ontology(name,content):
    suffix = Path(name).suffix.lower()
    if suffix==".json":
        return validate_ontology(json.loads(content))
    if b"<!ENTITY" in content.upper() or b"<!DOCTYPE" in content.upper():
        raise ValueError("Upload RDF without XML entity or document-type declarations.")
    fmt = "nt" if suffix==".nt" else "xml" if suffix in (".xml",".rdf",".owl") and content.lstrip().startswith(b"<") and b"xmlns" in content[:4096] else "turtle"
    graph = Graph()
    graph.parse(data=content,format=fmt,publicID="urn:uploaded:")
    classes = {s for t in (OWL.Class,RDFS.Class) for s in graph.subjects(RDF.type,t) if isinstance(s,URIRef)}
    hierarchy = [(child,parent) for child,parent in graph.subject_objects(RDFS.subClassOf) if isinstance(child,URIRef) and isinstance(parent,URIRef)]
    classes.update(n for pair in hierarchy for n in pair)
    properties = {p for p in graph.subjects(RDF.type,OWL.ObjectProperty) if isinstance(p,URIRef)}
    properties.update(p for p in graph.subjects(RDFS.domain,None) if isinstance(p,URIRef) and (p,RDF.type,OWL.DatatypeProperty) not in graph)
    endpoints = {}
    for p in sorted(properties,key=str):
        ends = [list(graph.objects(p,term)) for term in (RDFS.domain,RDFS.range)]
        if any(len(values)>1 or any(not isinstance(x,URIRef) for x in values) for values in ends):
            continue  # Preserve complex restrictions in the RDF graph.
        endpoints[p] = [v[0] if v else OWL.Thing for v in ends]
        classes.update(endpoints[p])
    def local(uri):
        return str(uri).rsplit("#",1)[-1].rsplit("/",1)[-1].rsplit(":",1)[-1] or str(uri)
    identifiers = sorted(classes|set(endpoints),key=str)
    labels = {u:local(u) for u in identifiers}
    counts = Counter(labels.values())
    labels = {u:(v if counts[v]==1 else str(u)) for u,v in labels.items()}
    onto = dict(version="uploaded",classes={labels[u]:str(graph.value(u,RDFS.label) or labels[u]) for u in sorted(classes,key=str)},
        predicates={labels[p]:[labels[x] for x in ends] for p,ends in endpoints.items()},uris={v:str(u) for u,v in labels.items()},
        subclasses=[[labels[c],labels[p]] for c,p in hierarchy],rdf_source=graph.serialize(format="turtle"))
    return validate_ontology(onto)


def export_rdf(onto):
    graph = Graph()
    if onto.get("rdf_source"):
        graph.parse(data=onto["rdf_source"],format="turtle")
    from urllib.parse import quote
    def uri(key):
        return URIRef(onto.get("uris",{}).get(key,onto.get("namespace","urn:pharm-study:")+quote(key,safe="")))
    for key,iri in onto.get("uris",{}).items():
        term = URIRef(iri)
        if key not in onto["classes"] and key not in onto["predicates"]:
            graph.remove((term,None,None))
            graph.remove((None,None,term))
    for child,parent in list(graph.subject_objects(RDFS.subClassOf)):
        if isinstance(child,URIRef) and isinstance(parent,URIRef):
            graph.remove((child,RDFS.subClassOf,parent))
    for child,parent in onto.get("subclasses",[]):
        graph.add((uri(child),RDFS.subClassOf,uri(parent)))
    for name,label in onto["classes"].items():
        term = uri(name)
        graph.add((term,RDF.type,OWL.Class))
        graph.set((term,RDFS.label,Literal(label)))
    for name,(src,tgt) in onto["predicates"].items():
        term = uri(name)
        graph.add((term,RDF.type,OWL.ObjectProperty))
        graph.set((term,RDFS.domain,uri(src)))
        graph.set((term,RDFS.range,uri(tgt)))
    return graph.serialize(format="turtle")
