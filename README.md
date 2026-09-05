# PFM assignment

A local data pipeline for Excel ingestion, deterministic conversion attribution,
and mart consumption. The warehouse is DuckDB, dbt owns the transformation
layers, and Streamlit is a thin read-only consumer of the published marts (plus
the single ADR-8 diagnostic intermediate view).

## What this submission contains

- An executable local sample pipeline (Excel → DuckDB raw → dbt staging /
  intermediate / marts → Streamlit walkthrough).
- A dbt attribution model with deterministic exact-click-id rules and its
  sample diagnostics (unmatched reasons, attribution health).
- The production attribution design: identifier contract, identity flow, and
  edge cases.
- The 18% reported-gap investigation plan (diagnostic queries + hypotheses).
- A BigQuery commission anomaly query (`sql/bigquery/commission_anomalies.sql`).
- A QuickBooks → BigQuery → dbt reconciliation architecture
  (`docs/quickbooks_reconciliation_design.md`, design only).
- A data quality monitoring design: five checks, thresholds, P1/P2/P3
  severities, and on-call routing
  (`docs/commission_monitoring_design.md`, design only).
- A Streamlit walkthrough organised around the assignment's two areas.

## What is not implemented

- No real BigQuery deployment, Airbyte connection, or QuickBooks API access.
- No production data is delivered or queried - all executable metrics come
  from the anonymised sample. The 18% production-gap figure is an
  assignment-provided reported premise, not a number computed here.
- No actual alerting infrastructure (no Slack/paging integration, no dbt
  Cloud job, no Cloud Monitoring alerts).

This boundary is deliberate scope control: the delivered pipeline runs
locally and self-contained, and every production design is labelled as
design-only.

## Pipeline

```text
data/source.xlsx  (Sample TrackNow Checkouts + Sample PostHog Sessions)
        |
        v
ingestion/load_excel.py  (Polars, snake_case only - values and nulls untouched)
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
consumers  (EDA notebook, Streamlit walkthrough, BigQuery consumption query)
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

1. **pytest** (`tests/`) - Python-level behavior. `tests/test_load_excel.py`
   covers ingestion: snake_case normalization, sheet-to-table mapping, raw
   table creation, preservation of fully null interior rows
   (`drop_empty_rows=False`), and Excel-to-DuckDB reconciliation.
   `tests/test_project_structure.py` guards the project manifest and the
   checked-in BigQuery consumption asset.
2. **dbt tests** - data contracts inside the model `schema.yml` files
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
warehouse file and the *required relations* - the consumer marts plus the
`intermediate.int_unmatched_conversions` diagnostic view that both the
analysis and methodology pages read. When they are missing it runs the
canonical pipeline once - `python ingestion/load_excel.py`, then `dbt build`
using the project-local profile (created from `dbt/profiles.yml.example` when
absent) - and only then opens the connection. The bootstrap is cached for the
Streamlit session, so the same execution never rebuilds the warehouse twice.
Failures are presented as readable errors in the app.

A custom `PFM_DUCKDB_PATH` is expected to point at an existing warehouse with
the required relations (the three marts **and** the diagnostic
`intermediate.int_unmatched_conversions` view); the auto-rebuild path manages
the default project warehouse only, because the ingestion script and dbt
profile are wired to that location.

### Deploying on Streamlit Community Cloud

Community Cloud treats a root `pyproject.toml` as a **Poetry** manifest and
runs `poetry install`. This repository is a plain setuptools/PEP 621 project
- it is not a Poetry project and not an installable package - so that path
fails with:

```text
The current project could not be installed: No file/folder found for
package pfm-assignment
```

The fix is the **fallback explicitly preferred for the deploy**: the app is
installed from the root `requirements.txt`, which Community Cloud resolves
*before* `pyproject.toml`. `pyproject.toml` remains the single manifest for
local development (`pip install -e ".[consumer,dev]"`); `requirements.txt`
is the single dependency file for the deploy environment, so the two never
compete.

```text
requirements.txt   <- Community Cloud installs the app from this file
pyproject.toml     <- local development only (kept, never used by the deploy)
```

Set the app's Python version to **3.12** (Community Cloud's default, and the
version the pinned dependencies are validated against) in the deploy's
*Advanced settings*. Do not use Python 3.14: not every pinned dependency
ships a wheel for it yet, so the build would try to compile from source.

On first boot the app finds no `warehouse/pfm.duckdb` and no local dbt
profile, runs the canonical bootstrap (ingestion, then `dbt build` with the
profile created from `dbt/profiles.yml.example`), and then serves the
walkthrough pages - see the reproducible-bootstrap section above.

### Pages and relations

The walkthrough is organised around the assignment's two areas:

#### Area 1 - Attribution & data modeling
The pages in Area 1 read directly from the published marts and one diagnostic intermediate view:
- **Overview**: presents the pipeline architecture, outlines each layer's responsibility, and distinguishes the reported 18% production gap (an assignment premise) from the extract's 0% match rate.
- **Attribution analysis**: reports valid conversion volume, commission, match and non-match rates, and marketing attribution by UTM source. It visualizes the non-match taxonomy using `intermediate.int_unmatched_conversions` and reconciles decided rows against `marts.mart_attribution_health`.
- **Methodology and limitations**: documents the target production identity flow (`gclid`/`fbclid`, `affiliate_session_id`), the sample's deterministic matching rules, dynamic metrics read live from the warehouse, and concrete data limitations.

Published relations consumed:
- `marts.fct_revenue_attribution`: valid conversions, commission, and channel attribution.
- `marts.mart_attribution_health`: daily attribution health and population reconciliation.
- `marts.fct_commission_daily_local`: local daily commission proxy.
- `intermediate.int_unmatched_conversions`: pre-computed non-match reason breakdown (read-only diagnostic view).

#### Area 2 - Investigation, integration & monitoring
The pages in Area 2 are design references that do not query the local warehouse:
- **Investigation & monitoring**: documents the 18% gap investigation plan with six diagnostic BigQuery queries, six hypotheses with associated tests and fixes, and root-cause guidance.
- **Data quality monitoring**: presents the five commission pipeline monitoring checks (freshness, conversion grain, unmatched rate regression, reconciliation variance, mapping coverage), P1/P2/P3 alert severities, and on-call routing policies (`docs/commission_monitoring_design.md`).
- **QuickBooks reconciliation**: details the daily automated reconciliation pipeline between QuickBooks invoices and TrackNow commission (`docs/quickbooks_reconciliation_design.md`).
- **What I'd do next**: engineering roadmap for migrating the local pipeline to GCP (BigQuery, Cloud Storage, Cloud Run Jobs, Terraform, CI/CD, and Cloud Monitoring).

## BigQuery consumption assets

`sql/bigquery/commission_anomalies.sql` is the direct answer to the assignment's BigQuery anomaly detection question (Area 1, Question 3). It is a BigQuery Standard SQL anomaly-detection query over the authoritative production `analytics_core.f_commission_daily` relation, producing per firm-day commission, a 7-day rolling calendar average (current row excluded), the percentage change vs that average, and an `anomaly` flag for absolute swings greater than 40%, ordered by absolute revenue impact descending. Replace the `project_id` placeholder with the target GCP project before execution.

> This query targets the production contract provided in the assignment and is not executed locally because `analytics_core.f_commission_daily` was not included in the supplied data.

`sql/bigquery/attribution_health.sql` is a complementary consumption asset that exposes the dbt `marts.mart_attribution_health` monitoring table for BigQuery consumers; it serves a separate monitoring purpose and is not the anomaly query.

Neither asset deploys GCP infrastructure or reimplements the dbt
transformation logic.

## Production commission architecture

The authoritative commission source is a **Google Sheet** maintained by the
business. The planned production pipeline that consumes it is:

```text
Google Sheet commission
        │
        ▼
Airbyte (ingestion)
        │
        ▼
BigQuery raw          raw.google_sheets_commission_daily
        │
        ▼
dbt staging           stg_commission_daily
        │                 grain: (commission_date, firm_id)
        │                 transforms: types, firm_id normalization,
        │                   currency validation, duplicate detection,
        │                   null checks
        ▼
intermediate          int_tracknow_commission_reconciliation
        │                 grain: (commission_date, firm_id)
        │                 fields: TrackNow-derived commission, official
        │                   Google Sheet commission, absolute delta,
        │                   pct delta, reconciliation status
        ▼
marts                 analytics_core.f_commission_daily
                          (or its local alias fct_commission_daily)
                          the official reporting-layer target
```

### Local sample vs production source

The local repository delivers `marts.fct_commission_daily_local`, a **proxy**
derived from the TrackNow `referral_bonus_gbp` field in the delivered
`data/source.xlsx` sample. That proxy exists to demonstrate the pipeline shape
and the Streamlit consumer with real, queryable numbers.

It is a development stand-in only: the authoritative Google Sheet → Airbyte → BigQuery
source was not provided with this exercise. Production reporting, reconciliation,
and anomaly detection must query `analytics_core.f_commission_daily` instead.

### Staging model contract

- **Model:** `stg_commission_daily`
- **Grain:** one row per `(commission_date, firm_id)`
- **Fields:**
  - `commission_date`
  - `firm_id` (normalized)
  - `firm_name`
  - `commission_amount`
  - `sales_amount`
  - `ingestion_timestamp`
- **Responsibilities:** types, firm_id normalization, currency validation,
  duplicate detection, null checks.

### Intermediate / reconciliation contract

- **Model:** `int_tracknow_commission_reconciliation`
- **Grain:** one row per `(commission_date, firm_id)`
- **Fields:**
  - TrackNow-derived commission (local proxy)
  - Official Google Sheet commission (production source)
  - Absolute delta
  - Pct delta
  - Reconciliation status
- **Rule:** the official Google Sheet value has precedence in the reporting
  layer when the two sources disagree.

None of this production GCP infrastructure exists in this repository; the
delivered pipeline remains local and self-contained.

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
requirements.txt                   Pinned runtime deps for the Community Cloud deploy
pyproject.toml                     Project manifest for local development (PEP 621)
docs/decisions.md                  Closed project decisions (ADR-lite)
sql/bigquery/commission_anomalies.sql  BigQuery anomaly query over `analytics_core.f_commission_daily`
sql/bigquery/attribution_health.sql   BigQuery read over `marts.mart_attribution_health`
docs/quickbooks_reconciliation_design.md  Area 2 design: QuickBooks -> Airbyte -> BigQuery -> dbt reconciliation -> alerts (design only)
docs/commission_monitoring_design.md  Area 2 design: five data quality checks, thresholds, P1/P2/P3 severities, on-call routing (design only)
streamlit/app.py                   Walkthrough entrypoint (navigation + bootstrap)
streamlit/warehouse_bootstrap.py   Read-only connection + reproducible bootstrap
streamlit/sections/                Walkthrough pages (overview, analysis, methodology, investigation, monitoring_design, quickbooks_reconciliation, next_steps)
tests/                             pytest suites (ingestion, bootstrap, structure)
tests/sql/                         Static checks on the BigQuery SQL assets
warehouse/pfm.duckdb               Generated local warehouse (ignored)
```

## Documentation

- `ingestion/ingestion.md` - sheet-to-table mapping, snake_case contract, raw
  schema, and how to re-run ingestion.
- `notebooks/README.md` - EDA purpose, execution, and conclusions that shaped
  the dbt pipeline.
- `docs/decisions.md` - closed decisions: Polars ingestion, preservation of
  fully null rows, exact click-ID matching, local DuckDB, mandatory
  review -> PR -> manual merge flow, English-only code.
- `docs/quickbooks_reconciliation_design.md` - Area 2 design answer: the
  QuickBooks -> Airbyte -> BigQuery raw -> dbt staging -> reconciliation ->
  alert pipeline, with per-layer grains, the
  `dim_firm_accounting_mapping` bridge, the reconciliation status taxonomy,
  and DQ checks per layer.
- `docs/commission_monitoring_design.md` - Area 2 design answer: the five
  data quality checks for the commission pipeline (source freshness,
  conversion grain, attribution unmatched-rate regression, reconciliation
  variance, mapping coverage) with thresholds, P1/P2/P3 severities, alert
  routing, and which check to build first.