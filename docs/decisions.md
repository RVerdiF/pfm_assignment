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