import asyncio
import json
import re

from pharm.catalog import DOCS, load_json
from pharm.encoders import encode_text
from pharm.provider import completion


class Utf8Tokenizer:
    """Reversible conservative token budget for the small custom graph."""
    def encode(self, text):
        return list(text.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


def engine(folder, llm=completion):
    from lightrag import LightRAG
    from lightrag.utils import EmbeddingFunc, Tokenizer

    async def embed(texts, **kwargs):
        return await asyncio.to_thread(encode_text, texts)

    return LightRAG(working_dir=str(folder), llm_model_func=llm, enable_llm_cache=False,
        tokenizer=Tokenizer("utf8", Utf8Tokenizer()),
        embedding_func=EmbeddingFunc(embedding_dim=384, max_token_size=256, func=embed))


async def build_graph(catalog, chunks, db, online=False, ontology=None):
    ontology = ontology or load_json(DOCS / "ontology.json")
    rules = ontology["predicates"]
    nodes, edges = {}, []

    def add(src, predicate, tgt, locator, batch, excerpt):
        predicate = ontology.get("bindings",{}).get(predicate,predicate)
        if predicate not in rules or not src or not tgt:
            return
        left, right = rules[predicate]
        for key, kind in ((src,left),(tgt,right)):
            if key in nodes and nodes[key] != kind:
                raise ValueError(f"Conflicting ontology type for {key}")
            nodes[key] = kind
        edges.append(dict(id=f"G-{len(edges)+1:04}", src=src, predicate=predicate, tgt=tgt, locator=locator, batch=batch, text=excerpt))

    for kind,role in (("images","depicts"),("documents","documents")):
        relation = ontology.get("bindings",{}).get(role,role)
        if relation in rules:
            for asset in catalog[kind]:
                nodes[asset["id"]] = rules[relation][0]
    for a in catalog["images"]:
        add(a["batch"],"hasSample",a["sample"],a["path"],a["batch"],f"{a['sample']} belongs to {a['batch']}.")
        add(a["id"],"depicts",a["sample"],a["path"],a["batch"],a["description"])
    image_samples = {(a["batch"],a["sample"]) for a in catalog["images"]}
    for row in db.execute("SELECT * FROM lims ORDER BY id"):
        pair = (row["batch"],row["sample"])
        if pair not in image_samples:
            add(row["batch"],"hasSample",row["sample"],row["locator"],row["batch"],f"{row['sample']} belongs to {row['batch']}.")
            image_samples.add(pair)
        add(row["sample"],"hasResult",row["id"],row["locator"],row["batch"],f"{row['sample']} has a {row['test']} result recorded as {row['id']}.")
    for row in db.execute("SELECT * FROM eln ORDER BY id"):
        add(row["run"],"processes",row["batch"],row["locator"],row["batch"],row["note"])
    for chunk in chunks:
        sample, batch = chunk["sample"], chunk["batch"]
        if sample and (sample in chunk["text"] or "uploads" in catalog):
            add(chunk["document"],"documents",sample,chunk["locator"],batch,chunk["text"])
        if online:
            response = await completion(chunk["text"], "Extract a verbatim sentence describing observed tablet appearance. Respond only with JSON containing a string field named span. Use an empty string if absent.")
            span = json.loads(response)["span"]
        else:
            match = re.search(r"Visual inspection recorded a (?:chipped|intact|mottled) tablet surface\.",chunk["text"])
            span = match.group() if match else ""
        if span and span in chunk["text"]:
            add(sample,"hasObservation",f"OBS-{chunk['id']}",chunk["locator"],batch,span)
    return {"nodes":nodes,"edges":edges,"extraction":"OpenRouter supported spans" if online else "Controlled report sentence pattern"}


async def project_graph(graph, folder):
    if not graph["nodes"]:
        return
    rag = engine(folder)
    await rag.initialize_storages()
    edges = graph["edges"]
    refs = {node:e["id"] for e in edges for node in (e["src"],e["tgt"])}
    singles = [{"content":n,"source_id":"entity-"+n,"file_path":"graph.json"} for n in graph["nodes"] if n not in refs]
    try:
        await rag.ainsert_custom_kg({
            "chunks":singles+[dict(content=e["id"]+" "+e["text"],source_id=e["id"],file_path=e["locator"]) for e in edges],
            "entities":[dict(entity_name=n,entity_type=t,description=n,source_id=refs.get(n,"entity-"+n)) for n,t in graph["nodes"].items()],
            "relationships":[dict(src_id=e["src"],tgt_id=e["tgt"],keywords=e["predicate"],description=e["text"],source_id=e["id"],weight=1.0) for e in edges]
        },full_doc_id="pharm-study")
        if not await rag.chunk_entity_relation_graph.has_node(next(iter(graph["nodes"]))):
            raise ValueError("LightRAG graph import failed")
    finally:
        await rag.finalize_storages()
