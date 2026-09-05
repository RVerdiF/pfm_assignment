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

## 2. Fully null rows are preserved - no `dropna(how="all")`

**Context:** The source workbook defines its own extent; some interior rows are
entirely empty.

**Decision:** The spreadsheet extent is the source contract. Sheets are read
with `drop_empty_rows=False` and no row filtering or deduplication is applied
during ingestion. Fully null interior rows are real records.

**Consequences:** Downstream models may encounter all-null rows and must not
assume DataFrame-import defaults trimmed them. The behavior is pinned by tests
(e.g. `test_load_retains_fully_null_interior_rows`).

---

## 3. The sample uses exact click-ID matching; production attribution needs a broader identity contract

**Context:** TrackNow orders carry `click_id`; PostHog sessions carry `gclid`,
`fbclid`, and `click_id_from_url`. The delivered workbook is an anonymised
sample whose identifiers show no deterministic cross-system overlap, and the
assignment also reports that 18% of TrackNow conversions in production lack a
matching PostHog session.

**Decision:** For the provided sample, a conversion is attributed only through
an **exact** equality between its `click_id` and a PostHog identifier value.
No fuzzy matching and no normalization of identifier values (case preserved).
Exact click-id equality is the only relationship that is *provable* in the
delivered file; the sample implementation constraint must not be read as the
production architecture. In production the identity contract must be
explicitly designed: ad-click identifiers (`gclid`/`fbclid`) are captured at
the landing and persisted with the PostHog `distinct_id`/session, propagated
onto the affiliate outbound click, and carried into TrackNow so `click_id` can
close the loop. `affiliate_session_id` is part of that TrackNow contract -
the sample's inability to relate it to a PostHog `session_id` does **not**
prove it irrelevant. Without a documented contract, no
`affiliate_session_id = PostHog.session_id` equality is assumed.

**Consequences:** Attribution in the executable sample is deterministic and
auditable; conversions without an exact match are not forced into a match and
are explained by `int_unmatched_conversions` with a deterministic
`unmatched_reason`. The local zero-match outcome is a property of the
anonymised sample, never a restatement of the production 18% gap (see ADR 11).

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
relations* on startup - the consumer marts plus the single
`intermediate.int_unmatched_conversions` diagnostic view (ADR 8), which both
the analysis and methodology pages read. When they are missing, it runs the
canonical pipeline once per Streamlit session - `python ingestion/load_excel.py`,
then `dbt build` with the project-local profile (created from
`dbt/profiles.yml.example` when absent) - before opening the connection
read-only. The connection is cached with `st.cache_resource`. The app never
re-implements attribution or business joins; it reads only the published
consumer relations.

**Consequences:** A fresh checkout can launch the app without manual pipeline
steps. The bootstrap is limited to the default project warehouse (custom
`PFM_DUCKDB_PATH` values must point at an already-provisioned warehouse
satisfying the full required-relation contract - a warehouse that passes only
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
as a read-only diagnostic relation - an aggregate over its pre-computed
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
in prose - health-mart sums, revenue-valid conversions and commission,
loss-cause reason counts, and the warehouse-specific limitation figures
(decided/valid conversion counts, the conversion-date span, and the
outside-window count) - is read live from the same dbt relations as the
charts (the health mart, the revenue mart, and the pre-computed
`int_unmatched_conversions` diagnostic view), so text cannot drift from data
and a different valid warehouse via the documented `PFM_DUCKDB_PATH` override
is never contradicted by the walkthrough. Layer responsibilities and rule
vocabulary are kept in sync with the dbt model headers and docs in this file.

---

## 10. Deploying to Streamlit Community Cloud uses `requirements.txt`, not Poetry

**Context:** A Streamlit Community Cloud deploy of the walkthrough failed
with `The current project could not be installed: No file/folder found for
package pfm-assignment`. Community Cloud treats a root `pyproject.toml` as a
**Poetry** manifest and runs `poetry install`. This repository is a plain
setuptools/PEP 621 project (`[project]` + `[build-system]` with setuptools)
- not a Poetry project and not an installable package - so Poetry's attempt
to install the project itself fails. Adding `package-mode = false` would only
help a genuine Poetry project; here the correct, supported path is the one
Community Cloud prefers.

**Decision:** The deploy environment is installed from a root
`requirements.txt` with fully pinned, locally validated versions. Community
Cloud resolves `requirements.txt` before `pyproject.toml`, so the deploy
never invokes Poetry and `pyproject.toml` remains the single manifest for
local development. Only one dependency file (`requirements.txt`) drives the
deploy. The app runs on **Python 3.12** - Community Cloud's default and the
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

---

## 11. The reported production gap and the sample's match rate are different populations

**Context:** The assignment reports, as a production fact, that 18% of
TrackNow conversions in the last 30 days have no matching PostHog session.
The delivered Excel sample is an anonymised, bounded extract (100 TrackNow
conversions, 200 PostHog sessions) in which no TrackNow `click_id` equals any
PostHog identifier value, so the local exact-match engine attributes 0% of
it. Treating the two numbers as one population conflates the exercise premise
with a property of the sample.

**Decision:** The two figures are always presented as separate populations:

- **Reported production issue** - an input premise from the assignment:
  18% of TrackNow conversions in the last 30 days have no matching PostHog
  session. It is cited as the investigation subject, never re-derived from
  the sample.
- **Observed deterministic match rate in the provided anonymised sample** -
  a factual property of the local executable model under exact matching,
  measured from the dbt marts on every render.

The Streamlit walkthrough and the dbt documentation state that these numbers
describe different populations and must not be compared as if one validated
the other. Production attribution design (identifier capture, persistence,
propagation, the TrackNow contract including `affiliate_session_id`, and the
investigation of the reported gap) is documented as design material, distinct
from what the sample demonstrates.

**Consequences:** No page of the walkthrough presents the sample's 0% match
rate as the production unmatched rate, as evidence about the production root
cause, or as a reason to redesign production attribution. Conversely, the
18% premise is never recomputed from the Excel data. The local SQL keeps its
exact-match logic - no fuzzy bridge is introduced to fabricate matches - and
the sample's results continue to reconcile with the published marts.
