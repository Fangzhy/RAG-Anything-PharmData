# Batch investigation

A four-page Streamlit demo for investigating a fictional tablet study. Start with **Explore data** to trace batch B-001 across the notebook, lab results, press historian, inspection reports, and images. **Preprocess data** exposes the validation ledger, Docling output, and ontology-backed graph. **Search data** accepts text, an image, or both. **Chat & Compare** opens in Chat mode for one cited answer. Turn on the toggle above the source controls to compare two selections side by side using the same question and image.

## Run locally

Use Python 3.12 from the project directory. On Windows with an existing project environment, run the following commands in PowerShell. For a fresh checkout, first create the environment with `py -3.12 -m venv .venv`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The committed study opens immediately. Semantic queries load two pinned Hugging Face model checkpoints on first use, approximately 700 MB combined. The encoders run locally on CPU. For generation, set `OPENROUTER_API_KEY` (or `OPEN_ROUTER_API`) and `OPENROUTER_MODEL` in the local `.env`. Select a free model ending in `:free` or use `openrouter/free`. The app sends the question and retrieved evidence to OpenRouter. Uploaded image pixels stay in the local image encoder. The search page works independently of OpenRouter.

## Study files

| Location | Contents |
| --- | --- |
| `docs/` | Feed requirements, unit rules, study criteria, relational schema, entity types, and permitted graph predicates |
| `data/raw/` | Original CSV exports, six PDF/Word reports, forty PNG inspections, and the asset catalog |
| `data/evaluation/` | Expected correction and quarantine IDs and a held-out query image used by tests |
| `data/prepared/` | Active build pointer, accepted SQLite tables and validation ledger, Docling JSON/Markdown, normalized vectors, directed evidence graph, and persisted LightRAG projection |

Try **LIMS → Quarantined** on the processing page. Of 80 LIMS records, 64 are valid on arrival, 12 have a documented unit correction, and four lack a measured value. Those four remain available for review and are excluded from numeric retrieval. For comparison, run the opening question with SQL on the left and all three sources on the right. Expand the citations to see which panel retrieved the inspection images.

The local vector index stores normalized MiniLM and OpenCLIP embeddings in separate NumPy arrays. The text and visual rankings are fused by sample. The graph view uses the directed assertions and source locators from the same build that populates LightRAG's local graph. LightRAG synthesizes the evidence packet through its retrieval-bypass mode so each source selector controls the evidence shown to the model.

## Work with your own files

On **Explore data**, click **Use Demo Data** or upload UTF-8 CSV exports, inspection images, PDFs and DOCX reports. The first upload starts a separate study. Subsequent uploads append to it. For attachments, enter batch/sample IDs when known. The same selection appears on **Preprocess data**.

Expand **Preprocess data from raw files**, load the demo contracts or upload your own, edit, and save. The schema format follows `docs/feed_schemas.json`. A feed can include `"columns": {"Lot Number": "batch"}` to map an incoming header and can add required fields such as `reviewer`. The audit preserves both the source and mapped records. Measurement values, identifiers and timestamp integrity still apply to the curated SQLite tables.

The ontology editor accepts app JSON, Turtle, N-Triples, and OWL serialized as RDF/XML or Turtle. It exposes named classes, named subclass relationships, and object predicates with domain and range. Use the extraction bindings table to connect lab relationships such as `hasResult` to your ontology. Download the JSON to reuse both the ontology and its mappings, or export Turtle for RDF tools. The app uses explicit mappings and does not run an OWL reasoner.

**Run pipeline to apply schema and ontology** builds the validation ledger, SQLite tables, and typed graph. **Run pipeline to apply parse and embed** processes the selected reports and image pixels and adds document-derived evidence. The knowledge graph supports editing nodes and edges, validating their types, and saving a new graph for retrieval. Builds and uploaded originals are stored under the ignored `data/workspaces/` directory. On localhost, bookmark the study URL after saving to reopen the selection and edits. On a hosted instance each browser session has its own workspace. Search data and both Chat & Compare modes use the selected build and offer the held-out tablet photo through **Use demo image**.

## Regenerate and test

```powershell
.\.venv\Scripts\python.exe -m pharm.generate
.\.venv\Scripts\python.exe -m pharm.prepare
.\.venv\Scripts\python.exe -m pytest -q
```

The generator writes the fixed synthetic investigation under `data`. The builder validates source checksums, prepares a new study directory and publishes its pointer after all stages succeed. Its default extraction matches the controlled observation sentences in the generated reports. To use OpenRouter for span extraction instead, run `python -m pharm.prepare --online` with the project interpreter. The processing page also exposes this choice. The automated tests use a controlled generation callback to check citations and provider failures. The multimodal tests run both real local encoders.

## Streamlit Community Cloud

Choose the repository branch containing the four pages, `app.py` as the entry point, and Python 3.12. Community Cloud installs `requirements.txt` for serving. The committed prepared study supplies SQLite, document previews, and both indexes on a fresh restart. Set the top-level `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` values in Community Cloud secrets. The runtime includes Docling for uploaded reports and RDFLib for ontology files. [App dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies) · [Secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)

Verify a cold start by opening B-001, tracing a corrected and a quarantined row, uploading `data/evaluation/query-chipped.png`, and running the default comparison. One local Windows comparison with both encoders peaked at approximately 1.8 GiB of process memory. Check cloud memory and latency on the deployed instance. [Community Cloud resource limits](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
