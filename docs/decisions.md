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

**Decision:** The app checks for the warehouse file and the required marts on
startup. When they are missing, it runs the canonical pipeline once per
Streamlit session — `python ingestion/load_excel.py`, then `dbt build` with
the project-local profile (created from `dbt/profiles.yml.example` when
absent) — before opening the connection read-only. The connection is cached
with `st.cache_resource`. The app never re-implements attribution or business
joins; it only reads the published marts.

**Consequences:** A fresh checkout can launch the app without manual pipeline
steps. The bootstrap is limited to the default project warehouse (custom
`PFM_DUCKDB_PATH` values must point at an already-provisioned warehouse), and
pipeline failures surface as readable errors instead of silent partial state.

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
