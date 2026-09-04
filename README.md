# PFM assignment

A local data pipeline for Excel ingestion, deterministic conversion attribution,
and mart consumption. The warehouse is DuckDB, dbt owns the transformation
layers, and Streamlit is a thin read-only consumer of the published marts.

## Pipeline

```text
data/source.xlsx  (Sample TrackNow Checkouts + Sample PostHog Sessions)
        |
        v
ingestion/load_excel.py  (Polars, snake_case only — values and nulls untouched)
        |
        v
warehouse/pfm.duckdb  (raw schema: raw.tracknow_checkouts, raw.posthog_sessions)
        |
        v
dbt staging  (stg_tracknow_checkouts, stg_posthog_sessions)
        |
        v
dbt intermediate  (attribution candidates -> deterministic attribution -> unmatched diagnostics)
        |
        v
dbt marts  (fct_revenue_attribution, fct_commission_daily_local, mart_attribution_health)
        |
        v
consumers  (EDA notebook, Streamlit app, BigQuery consumption query)
```

## Requirements

- Python 3.11 or newer
- `dbt-core` with the `dbt-duckdb` adapter
- The Python dependencies declared in `pyproject.toml`
- `data/source.xlsx` (already delivered with this project)

Create or activate a virtual environment, then install the project with the
`consumer` and `dev` extras. The project dependencies include `dbt-core` and
`dbt-duckdb`; `consumer` adds Streamlit and `dev` adds pytest and Jupyter, so
every step of the Quickstart below works from a clean environment:

```bash
python -m pip install -e ".[consumer,dev]"
```

## Quickstart

### 1. Load the raw data

The ingestion command reads the two analytical worksheets in
`data/source.xlsx`, normalizes column names to snake_case, and creates or
replaces these raw tables in `warehouse/pfm.duckdb`:

- `raw.tracknow_checkouts`
- `raw.posthog_sessions`

From the repository root:

```bash
python ingestion/load_excel.py
```

It preserves source values and null rows within the worksheet extent. Running
it again is safe and deterministic for the local warehouse. The full contract
is documented in `ingestion/ingestion.md`.

### 2. Build the dbt models

The checked-in profile is an example only. Copy it into the project-local dbt
profile directory; this avoids credentials, absolute paths, and changes to a
user's global `~/.dbt` configuration.

From the repository root:

```bash
cp dbt/profiles.yml.example dbt/profiles.yml
export DBT_PROFILES_DIR="$PWD/dbt"

cd dbt
dbt debug
dbt build
```

`DBT_PROFILES_DIR` is exported before changing directory, so the documented
commands are exactly `dbt debug` and `dbt build` from `dbt/`. The generated
`dbt/profiles.yml` is ignored by Git. The profile points to
`../warehouse/pfm.duckdb`, which is correct when dbt is run from `dbt/`.

To remove local dbt artifacts after a run:

```bash
cd dbt
dbt clean
```

### 3. Run the tests

```bash
pytest -q
```

### 4. Explore the data

```bash
jupyter notebook notebooks/01_data_exploration.ipynb
```

See `notebooks/README.md` for the EDA findings that shaped the dbt pipeline.

### 5. Launch the consumer

```bash
streamlit run streamlit/app.py
```

See the Streamlit consumer section below for details.

## dbt layer contract

The dbt project is configured with the `pfm_assignment` profile and writes
schemas directly as `raw`, `staging`, `intermediate`, and `marts`.

| Layer | Relations | Materialization | Purpose |
| --- | --- | --- | --- |
| Raw | `raw.tracknow_checkouts`, `raw.posthog_sessions` | DuckDB tables from ingestion | Source-shaped data |
| Staging | `stg_tracknow_checkouts`, `stg_posthog_sessions` | Views in `staging` | Typed, trimmed, stable source interfaces |
| Intermediate | Attribution candidates and diagnostics | Views in `intermediate` by default | Attribution preparation and diagnostics |
| Intermediate | `int_conversion_attribution` | Table in `intermediate` | Single deterministic attribution decision |
| Marts | `fct_revenue_attribution`, `fct_commission_daily_local`, `mart_attribution_health` | Tables in `marts` | Consumer-facing revenue and monitoring relations |

The `raw` source declaration is in `dbt/models/sources.yml`. Attribution is
exact-match and deterministic in the intermediate layer (see
`dbt/models/intermediate/attribution/winner_rules.yml` and
`docs/decisions.md`); downstream marts and consumers carry that decision rather
than re-implementing it. The local daily commission model is explicitly a
sample-derived proxy because the authoritative `analytics_core.f_commission_daily`
source was not provided.

Run selected checks when iterating:

```bash
cd dbt
dbt list --resource-type model
dbt build --select staging+
dbt build --select marts
```

`dbt build` runs model builds and the declared schema/singular tests. The
project has no external package dependencies, so `dbt deps` is not required.

## Testing strategy

Tests run in two layers:

1. **pytest** (`tests/`) — Python-level behavior. `tests/test_load_excel.py`
   covers ingestion: snake_case normalization, sheet-to-table mapping, raw
   table creation, preservation of fully null interior rows
   (`drop_empty_rows=False`), and Excel-to-DuckDB reconciliation.
   `tests/test_project_structure.py` guards the project manifest and the
   checked-in BigQuery consumption asset.
2. **dbt tests** — data contracts inside the model `schema.yml` files
   (`not_null`, `unique`, `accepted_values`) plus 23 singular tests under
   `dbt/tests/` that prove invariants: no fan-out, exact-match-only
   attribution, row parity between layers, unmatched reasons, and marts
   reconciling to staging.

## Streamlit consumer

Launch the consumer from the repository root:

```bash
streamlit run streamlit/app.py
```

The app opens `warehouse/pfm.duckdb` read-only by default. To use another
already-provisioned local warehouse without editing code, set an explicit
path:

```bash
PFM_DUCKDB_PATH=/path/to/pfm.duckdb streamlit run streamlit/app.py
```

### Reproducible bootstrap

The app is designed to start even on a fresh environment where
`warehouse/pfm.duckdb` does not exist yet. On startup it checks for the
warehouse file and the required dbt marts; when they are missing it runs the
canonical pipeline once — `python ingestion/load_excel.py`, then `dbt build`
using the project-local profile (created from `dbt/profiles.yml.example` when
absent) — and only then opens the connection. The bootstrap is cached for the
Streamlit session, so the same execution never rebuilds the warehouse twice.
Failures are presented as readable errors in the app.

A custom `PFM_DUCKDB_PATH` is expected to point at an existing warehouse with
the required marts; the auto-rebuild path manages the default project
warehouse only, because the ingestion script and dbt profile are wired to that
location.

### Pages and marts

The walkthrough is organised into pages (`Overview`, `Attribution analysis`,
`Methodology and limitations`) that read only the published marts:

- `marts.fct_revenue_attribution` for valid-conversion revenue, commission,
  match status, and UTM breakdowns;
- `marts.mart_attribution_health` for daily/source attribution monitoring;
- `marts.fct_commission_daily_local` for the clearly labelled local commission
  proxy.

It does not query raw or staging relations and does not perform attribution
joins in Python.

## BigQuery consumption asset

`sql/bigquery/attribution_health.sql` is a BigQuery-compatible read-only
consumer query over the published `marts.mart_attribution_health` relation.
Replace the `project_id` placeholder with the target GCP project before
execution. It does not deploy infrastructure or reimplement the dbt
transformation logic.

## Repository layout

```text
data/source.xlsx                   Delivered source workbook
ingestion/load_excel.py            Excel -> DuckDB raw loader
ingestion/ingestion.md             Ingestion contract and how to re-run it
dbt/dbt_project.yml                dbt project and layer configuration
dbt/profiles.yml.example           Credential-free local profile template
dbt/macros/                        Project macros (schema naming)
dbt/models/sources.yml             Raw source declaration
dbt/models/staging/                Staging views
dbt/models/intermediate/           Attribution and diagnostics
dbt/models/marts/                  Consumer-facing tables
dbt/tests/                         Singular tests (data contracts and invariants)
notebooks/01_data_exploration.ipynb  Pre-modeling EDA
notebooks/README.md                How to run the EDA and what it found
docs/decisions.md                  Closed project decisions (ADR-lite)
sql/bigquery/attribution_health.sql  BigQuery mart consumption query
streamlit/app.py                   Walkthrough entrypoint (navigation + bootstrap)
streamlit/warehouse_bootstrap.py   Read-only connection + reproducible bootstrap
streamlit/sections/                Walkthrough pages (overview, analysis, methodology)
tests/                             pytest suites (ingestion, bootstrap, structure)
warehouse/pfm.duckdb               Generated local warehouse (ignored)
```

## Documentation

- `ingestion/ingestion.md` — sheet-to-table mapping, snake_case contract, raw
  schema, and how to re-run ingestion.
- `notebooks/README.md` — EDA purpose, execution, and conclusions that shaped
  the dbt pipeline.
- `docs/decisions.md` — closed decisions: Polars ingestion, preservation of
  fully null rows, exact click-ID matching, local DuckDB, mandatory
  review -> PR -> manual merge flow, English-only code.