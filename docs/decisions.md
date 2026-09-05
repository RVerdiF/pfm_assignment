# Architectural Decision Records (ADRs)

Key architectural decisions recorded as lightweight ADRs.

---

## 1. Ingestion uses Polars, never Pandas

- **Context:** Ingestion reads raw Excel sheets and writes them to DuckDB.
- **Decision:** All ingestion code (`ingestion/load_excel.py`) and EDA use Polars (`pl.read_excel`, Arrow-backed DataFrames). Pandas is not used in the data path.
- **Consequences:** High-performance columnar reads with a direct Arrow bridge into DuckDB.

---

## 2. Fully null rows are preserved (no `dropna`)

- **Context:** The source workbook defines its own extent; some interior rows are empty.
- **Decision:** Sheets are ingested with `drop_empty_rows=False` without row filtering. Empty interior rows are preserved as source records.
- **Consequences:** Downstream dbt models handle null records explicitly rather than relying on silent ingestion drops.

---

## 3. Sample exact click-ID matching vs. production identity contract

- **Context:** TrackNow orders carry `click_id`; PostHog sessions carry `gclid`, `fbclid`, and `click_id_from_url`. The sample file is an anonymized extract without cross-system identifier overlap.
- **Decision:** Sample attribution strictly enforces exact `click_id` equality without fuzzy matching. In production, a documented identity contract must capture ad click IDs at landing, persist with PostHog sessions, and propagate into TrackNow (`affiliate_session_id`).
- **Consequences:** Sample attribution is auditable and deterministic. Unmatched rows are classified by `int_unmatched_conversions`.

---

## 4. Local DuckDB as the analytical warehouse

- **Context:** The project requires a reproducible, serverless analytical warehouse.
- **Decision:** DuckDB (`warehouse/pfm.duckdb`) is the warehouse. Raw data lands in the `raw` schema; dbt builds staging, intermediate, and mart layers on top.
- **Consequences:** Zero-infrastructure local execution. The `.duckdb` file is gitignored and recreated on demand.

---

## 5. Development workflow: feature branches and PRs

- **Context:** Maintain quality and auditability across all code and documentation changes.
- **Decision:** All modifications follow isolated branch -> review -> pull request -> merge to `main`. Direct commits to `main` are avoided.
- **Consequences:** Traceable Git history and consistent peer/owner reviews.

---

## 6. Language standard: 100% English

- **Context:** Repository maintenance in international data engineering environments.
- **Decision:** All code, dbt models, comments, tests, and documentation are in English.
- **Consequences:** Consistent, grep-friendly codebase.

---

## 7. Streamlit auto-bootstrap on missing warehouse

- **Context:** The Streamlit app must run cleanly on fresh checkouts or Streamlit Community Cloud without prior manual pipeline execution.
- **Decision:** On startup, the app verifies the warehouse and required relations (marts + `int_unmatched_conversions`). If missing, it runs `ingestion/load_excel.py` and `dbt build` automatically before opening the connection in read-only mode.
- **Consequences:** Seamless first-run experience on fresh hosting environments.

---

## 8. Streamlit consumer reads diagnostic intermediate view

- **Context:** Card 2 requires explaining unmatched conversions (`missing_click_id`, `click_id_not_found`, `outside_posthog_sample_window`, `multiple_candidates`).
- **Decision:** The Streamlit app is permitted to read the pre-aggregated `intermediate.int_unmatched_conversions` view as a read-only diagnostic relation. It never re-implements attribution or business joins in Python.
- **Consequences:** Single source of truth for attribution diagnostics without duplicate logic in the UI layer.

---

## 9. Walkthrough narrative self-contained in Streamlit

- **Context:** Card 3 requires an end-to-end walkthrough accessible without external documentation.
- **Decision:** The Streamlit app embeds narrative context, interactive architecture diagrams, live mart metrics, and methodology explanations directly alongside charts.
- **Consequences:** Fully self-contained deliverable where text and numbers reconcile with live dbt marts.

---

## 10. Streamlit Community Cloud deploy uses requirements.txt

- **Context:** Streamlit Community Cloud misinterprets root `pyproject.toml` as a Poetry package.
- **Decision:** The deployment environment uses a pinned `requirements.txt`. `pyproject.toml` remains for local development.
- **Consequences:** Reliable cloud deployments on Python 3.12 without unnecessary package wrappers.

---

## 11. Separation of reported production gap and sample match rate

- **Context:** The prompt notes an 18% production gap in TrackNow conversions. The anonymized sample yields 0% exact matches due to synthetic identifiers.
- **Decision:** The reported 18% production gap (assignment premise) and the sample 0% match rate (local deterministic result) are explicitly presented as separate populations.
- **Consequences:** Prevents confusing the sample's synthetic properties with production root causes, maintaining analytical integrity.
