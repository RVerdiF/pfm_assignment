# PFM assignment

A local data pipeline for Excel ingestion, deterministic conversion attribution,
and mart consumption. The warehouse is DuckDB, dbt owns the transformation
layers, and Streamlit is a thin read-only consumer of the published marts.

## Requirements

- Python 3.11 or newer
- `dbt-core` with the `dbt-duckdb` adapter
- The Python dependencies declared in `pyproject.toml`
- `data/source.xlsx` (already delivered with this project)

Create or activate a virtual environment, then install the project and the
optional consumer dependency. The project dependencies include `dbt-core` and
`dbt-duckdb`, so the documented pipeline is available after this install:

```bash
python -m pip install -e ".[consumer]"
```

## Reproduce the pipeline locally

The checked-in profile is an example only. Copy it into the project-local dbt
profile directory; this avoids credentials, absolute paths, and changes to a
user's global `~/.dbt` configuration.

From the repository root:

```bash
cp dbt/profiles.yml.example dbt/profiles.yml
export DBT_PROFILES_DIR="$PWD/dbt"

python ingestion/load_excel.py
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

The ingestion command reads the two analytical worksheets in
`data/source.xlsx`, normalizes column names to snake_case, and creates or
replaces these raw tables:

- `raw.tracknow_checkouts`
- `raw.posthog_sessions`

It preserves source values and null rows within the worksheet extent. Running
it again is safe and deterministic for the local warehouse.

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
exact-match and deterministic in the intermediate layer; downstream marts and
consumers carry that decision rather than re-implementing it. The local daily
commission model is explicitly a sample-derived proxy because the authoritative
`analytics_core.f_commission_daily` source was not provided.

Run selected checks when iterating:

```bash
cd dbt
dbt list --resource-type model
dbt build --select staging+
dbt build --select marts
```

`dbt build` runs model builds and the declared schema/singular tests. The
project has no external package dependencies, so `dbt deps` is not required.

## Streamlit consumer

After ingestion and `dbt build`, launch the consumer from the repository root:

```bash
streamlit run streamlit/app.py
```

The app opens `warehouse/pfm.duckdb` read-only by default. To use another local
warehouse without editing code, set an explicit path:

```bash
PFM_DUCKDB_PATH=/path/to/pfm.duckdb streamlit run streamlit/app.py
```

The app reads only these dbt marts:

- `marts.fct_revenue_attribution` for valid-conversion revenue, commission,
  match status, and UTM breakdowns;
- `marts.mart_attribution_health` for daily/source attribution monitoring;
- `marts.fct_commission_daily_local` for the clearly labelled local commission
  proxy.

It does not query raw or staging relations and does not perform attribution
joins in Python. If the warehouse or marts are missing, it displays setup
instructions instead of creating or modifying data.

## BigQuery consumption asset

`sql/bigquery/attribution_health.sql` is a BigQuery-compatible read-only
consumer query over the published `marts.mart_attribution_health` relation.
Replace the `project_id` placeholder with the target GCP project before
execution. It does not deploy infrastructure or reimplement the dbt
transformation logic.

## Repository layout

```text
data/source.xlsx                 Delivered source workbook
ingestion/load_excel.py           Excel -> DuckDB raw loader
dbt/dbt_project.yml               dbt project and layer configuration
dbt/profiles.yml.example          Credential-free local profile template
dbt/models/sources.yml            Raw source declaration
dbt/models/staging/               Staging views
dbt/models/intermediate/          Attribution and diagnostics
dbt/models/marts/                 Consumer-facing tables
sql/bigquery/attribution_health.sql  BigQuery mart consumption query
streamlit/app.py                  Read-only marts consumer
warehouse/pfm.duckdb              Generated local warehouse (ignored)
```
