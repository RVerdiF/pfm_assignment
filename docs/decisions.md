# Decisions

Closed decisions recorded as lightweight ADRs. Each entry states the context,
the decision, and the consequences the codebase is built around.

---

## 1. Ingestion uses Polars, never Pandas

**Context:** The ingestion step reads Excel sheets and writes them to DuckDB.
Both libraries are viable in Python.

**Decision:** All ingestion code (`ingestion/load_excel.py`) uses Polars
(`pl.read_excel`, Arrow-backed DataFrames). Pandas is not used anywhere in the
data path.

**Consequences:** Column-oriented performant reads with a consistent Arrow
bridge into DuckDB; the EDA notebook and ingestion share the same Polars
contract.

---

## 2. Fully null rows are preserved — no `dropna(how="all")`

**Context:** The source workbook defines its own extent; some interior rows are
entirely empty.

**Decision:** The spreadsheet extent is the source contract. Sheets are read
with `drop_empty_rows=False` and no row filtering or deduplication is applied
during ingestion. Fully null interior rows are real records.

**Consequences:** Downstream models may encounter all-null rows and must not
assume DataFrame-import defaults trimmed them. The behavior is pinned by tests
(e.g. `test_load_retains_fully_null_interior_rows`).

---

## 3. Attribution uses exact click-ID matching, never fuzzy

**Context:** TrackNow orders carry `click_id`; PostHog sessions carry `gclid`,
`fbclid`, and `click_id_from_url`.

**Decision:** A conversion is attributed only through an **exact** equality
between its `click_id` and a PostHog identifier value. No fuzzy matching, no
normalization of identifier values (case preserved), and no invented join key
(`affiliate_session_id` is never assumed to equal a PostHog `session_id`).

**Consequences:** Attribution is deterministic and auditable. Conversions
without an exact match are not forced into a match; they are explained by
`int_unmatched_conversions` with a deterministic `unmatched_reason`.

---

## 4. Local DuckDB is the warehouse

**Context:** The assignment provides a bounded sample (one Excel workbook) and
no external warehouse access.

**Decision:** DuckDB is the local analytical warehouse. Ingestion writes to the
`raw` schema of `warehouse/pfm.duckdb`; dbt models materialize on top of it.

**Consequences:** Zero-infrastructure local development; the database file is
gitignored and recreated by re-running ingestion.

---

## 5. Code lands only through review -> PR -> manual merge

**Context:** The repository is owned by a single maintainer and changes are
gate-reviewed.

**Decision:** Every change follows the flow: implementation in an isolated
branch, review gate, pull request, and **manual merge by the owner**. Direct
merges to `main` are forbidden.

**Consequences:** `main` always reflects reviewed work; the review gate is a
hard requirement for any contribution, including documentation.

---

## 6. Code is 100% English

**Context:** Repository authors and future readers work in a mixed-language
environment.

**Decision:** All code, model names, comments, and repository documentation are
written in English (Portuguese appears only in external assignment notes, never
in the codebase).

**Consequences:** A single language for code and docs; identifiers, comments,
and PRs stay consistent and grep-friendly.
---

## 7. Streamlit auto-bootstraps the local warehouse when it is missing

**Context:** The Streamlit app must start reproducibly on a fresh hosting
environment where `warehouse/pfm.duckdb` does not exist yet, while still being
a thin read-only consumer of dbt marts.

**Decision:** The app checks for the warehouse file and the *required
relations* on startup — the consumer marts plus the single
`intermediate.int_unmatched_conversions` diagnostic view (ADR 8), which both
the analysis and methodology pages read. When they are missing, it runs the
canonical pipeline once per Streamlit session — `python ingestion/load_excel.py`,
then `dbt build` with the project-local profile (created from
`dbt/profiles.yml.example` when absent) — before opening the connection
read-only. The connection is cached with `st.cache_resource`. The app never
re-implements attribution or business joins; it reads only the published
consumer relations.

**Consequences:** A fresh checkout can launch the app without manual pipeline
steps. The bootstrap is limited to the default project warehouse (custom
`PFM_DUCKDB_PATH` values must point at an already-provisioned warehouse
satisfying the full required-relation contract — a warehouse that passes only
the mart checks cannot crash later at render time with a missing-relation
error), and pipeline failures surface as readable errors instead of silent
partial state.

---

## 8. The Streamlit consumer may read the diagnostic intermediate view

**Context:** Card 2 asks the analysis page to explain *why* conversions are
not attributed (`missing_click_id`, `click_id_not_found`,
`outside_posthog_sample_window`, `multiple_candidates`, `unknown`). That
explanation is produced once, deterministically, by
`int_unmatched_conversions` in the intermediate layer; re-deriving it in the
app would duplicate the attribution-adjacent classification logic the project
explicitly keeps out of Python.

**Decision:** The consumer may read `intermediate.int_unmatched_conversions`
as a read-only diagnostic relation — an aggregate over its pre-computed
`unmatched_reason` column only, never a join. It remains forbidden from
reading raw/staging relations and from re-implementing attribution rules. The
intermediate relation is materialized as a dbt view, so it always mirrors the
latest attribution table. All other aggregate totals the page needs (decided
conversions including denied rows, match status, daily/source health) are
published by `marts.mart_attribution_health` and read from that mart.

**Consequences:** The diagnosis panel reconciles with
`int_conversion_attribution` by construction and stays vocabulary-stable (the
page zero-fills the full declared taxonomy). The audit trail remains intact:
the view is a strict filtered projection of the attribution decision table.
The intermediate-layer reading is narrow and documented so later consumers do
not broaden it into business joins.

---

## 9. The walkthrough narrative is self-contained in the Streamlit pages

**Context:** Card 3 turns the app into a final, self-contained delivery: an
evaluator must understand the problem, the solution architecture, the
method, the observed results, and the limitations *without* opening external
documentation.

**Decision:** The walkthrough lives in the Streamlit pages, as prose and
light visuals around the same dbt-published relations the analysis page
reads:

- The Overview page states the problem, renders the real pipeline
  architecture (`Excel sample -> Polars -> DuckDB raw -> dbt staging ->
  dbt intermediate -> dbt marts -> Streamlit`) as a client-side graphviz
  diagram plus one-line layer responsibilities, and confirms the read-only
  marts connection.
- The Methodology and limitations page explains the four deterministic rules
  (exact click-id match, temporal window, identifier priority, recency
  tie-break), the matched/ambiguous/unmatched outcomes, interprets the
  observed results, and lists limitations and recommendations.
- Every analysis section opens with a prose reading of its numbers. No
  attribution rule is re-implemented and no new intermediate read is added.

**Consequences:** The app is a complete walkthrough with a clear heading
hierarchy and short prose around each chart. Every narrative quantity cited
in prose — health-mart sums, revenue-valid conversions and commission,
loss-cause reason counts, and the warehouse-specific limitation figures
(decided/valid conversion counts, the conversion-date span, and the
outside-window count) — is read live from the same dbt relations as the
charts (the health mart, the revenue mart, and the pre-computed
`int_unmatched_conversions` diagnostic view), so text cannot drift from data
and a different valid warehouse via the documented `PFM_DUCKDB_PATH` override
is never contradicted by the walkthrough. Layer responsibilities and rule
vocabulary are kept in sync with the dbt model headers and docs in this file.

---

## 10. "What I'd do next" is a prose-only page, never fictional infrastructure

**Context:** Card 4 asks the walkthrough to close with a short section on how
the local solution could evolve to a production GCP architecture. The
assignment explicitly forbids implementing BigQuery, Terraform, CI/CD, or any
other production infrastructure, and forbids presenting fictional
infrastructure as if it were implemented.

**Decision:** The closing "What I'd do next" page is pure prose. It states the
main message (`This implementation is intentionally local and self-contained.
In production, I would preserve the same transformation contracts while moving
execution and storage to managed GCP services.`), shows the one-line future
architecture (`Source -> Cloud Storage/API -> BigQuery raw -> dbt -> BigQuery
marts -> Streamlit/BI`) with its supporting automation, and splits the
evolution into *what changes* (BigQuery as the managed warehouse, dbt-bigquery
as the adapter, Cloud Storage as the landing zone, Cloud Run Jobs / Cloud
Build for execution and scheduling, Terraform for datasets/service
accounts/IAM/buckets with least privilege, GitHub Actions for CI/CD, Cloud
Monitoring for freshness/failure/match-rate/unmatched-reason observability)
and *what stays the same* (the dbt transformation contracts and layered
shape, the read-only consumer posture, and the existing BigQuery-compatible
`sql/bigquery/attribution_health.sql` asset). The page reads no warehouse
relation and renders no chart, and its closing note makes the boundary
explicit: nothing on it exists in this repository yet.

**Consequences:** The walkthrough ends with an honest, short,
architecture-oriented answer to "what next" without expanding the assignment's
scope. The change-vs-constant split makes it clear that the value to preserve
is the dbt transformation design, not the local execution details. Because
the page is prose-only, it adds no new relation to the consumer contract and
no fictional resource to the repository.
## 10. Deploying to Streamlit Community Cloud uses `requirements.txt`, not Poetry

**Context:** A Streamlit Community Cloud deploy of the walkthrough failed
with `The current project could not be installed: No file/folder found for
package pfm-assignment`. Community Cloud treats a root `pyproject.toml` as a
**Poetry** manifest and runs `poetry install`. This repository is a plain
setuptools/PEP 621 project (`[project]` + `[build-system]` with setuptools)
— not a Poetry project and not an installable package — so Poetry's attempt
to install the project itself fails. Adding `package-mode = false` would only
help a genuine Poetry project; here the correct, supported path is the one
Community Cloud prefers.

**Decision:** The deploy environment is installed from a root
`requirements.txt` with fully pinned, locally validated versions. Community
Cloud resolves `requirements.txt` before `pyproject.toml`, so the deploy
never invokes Poetry and `pyproject.toml` remains the single manifest for
local development. Only one dependency file (`requirements.txt`) drives the
deploy. The app runs on **Python 3.12** — Community Cloud's default and the
version the pins are validated against. No artificial Python package is
created to satisfy a package manager.

**Consequences:** The deploy installs exactly the pinned versions that were
validated in a clean Python 3.12 virtualenv (full pytest suite green and a
real first-boot bootstrap: no warehouse file and no dbt profile present, then
ingestion + `dbt build` create the required relations before the app serves
the pages). Local development is unchanged (`pip install -e ".[consumer,dev]"`
reads `pyproject.toml`). Keeping `requirements.txt` in sync with
`pyproject.toml` is a manual step documented in the README; future
dependency bumps must be validated in both manifests.
