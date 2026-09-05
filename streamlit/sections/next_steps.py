"""What I'd do next page for the PFM walkthrough.

The final page of the walkthrough. Every earlier page describes what this
assignment actually builds; this page closes the story by outlining, in a few
short architecture-oriented paragraphs, how the same solution could evolve to
a production GCP pipeline — without implementing any of it here.

The page is deliberately pure prose: it reads no warehouse relation and adds
no chart, because there is nothing in the delivered repo to measure yet. Its
only job is to make the boundary explicit:

- the current implementation is intentionally local and self-contained
  (DuckDB + dbt + a read-only Streamlit consumer);
- the transformation contracts (the dbt layers and the exact-match
  attribution rules) are the part that would carry over;
- the managed-GCP pieces (BigQuery, Cloud Run/Cloud Build, Terraform,
  GitHub Actions, monitoring) are the part that would be added, and none of
  that infrastructure exists in this repository.
"""
from __future__ import annotations

import streamlit as st

# Main message the card requires: local today, preserved contracts tomorrow.
NEXT_STEPS_INTRO = (
    "**This implementation is intentionally local and self-contained.** "
    "In production, I would preserve the same transformation contracts while "
    "moving execution and storage to managed GCP services."
)

# The production architecture in one line, as the card asks. Nothing with this
# shape exists in the repository; it is the destination, not the delivery.
PRODUCTION_ARCHITECTURE = (
    "Source -> Cloud Storage/API -> BigQuery raw -> dbt -> BigQuery marts "
    "-> Streamlit/BI"
)

# Supporting automation for the production architecture, stated once.
PRODUCTION_SUPPORT = (
    "Terraform + GitHub Actions + Cloud Run Jobs / Cloud Build + "
    "Cloud Monitoring"
)

# What changes when the local solution moves to GCP. Each item names the
# managed service and the job it would take over; none is implemented here.
WHAT_CHANGES = (
    (
        "Warehouse",
        "Replace the local DuckDB file with **BigQuery** as the managed "
        "warehouse. dbt remains the transformation owner and keeps the same "
        "layered shape: `raw -> staging -> intermediate -> marts`.",
    ),
    (
        "dbt adapter",
        "Run the models with **dbt-bigquery** instead of dbt-duckdb. Most of "
        "the SQL logic and the model contracts would carry over; the changes "
        "are adapter-specific (warehouse-specific SQL, BigQuery naming and "
        "materialization details), not a rewrite of the transformation "
        "design.",
    ),
    (
        "Ingestion and execution",
        "When the source stops being a local workbook, **Cloud Storage** "
        "becomes the landing zone and **Cloud Run Jobs** or **Cloud Build** "
        "run ingestion and `dbt build` on the managed pipeline, on a managed "
        "schedule when needed.",
    ),
    (
        "Infrastructure",
        "Provision the production footprint with **Terraform**: BigQuery "
        "datasets, service accounts, IAM, and auxiliary buckets/resources, "
        "with the minimum permissions each stage needs (ingest, transform, "
        "consume).",
    ),
    (
        "CI/CD",
        "Use **GitHub Actions** for lint and tests, `dbt parse` / `dbt "
        "build` in a controlled environment, Terraform validation, and "
        "deploys of infrastructure and pipeline.",
    ),
    (
        "Observability",
        "Monitor the pipeline with **Cloud Monitoring**: data freshness, "
        "ingestion failures, dbt failures, a drop in the attribution match "
        "rate, an increase in `unmatched` or `ambiguous` conversions, and "
        "abnormal shifts in the main non-attribution reasons.",
    ),
)

# What stays the same. The card asks for an explicit change-vs-constant split,
# so each item names a contract this repository already ships that would
# survive the move.
WHAT_STAYS = (
    (
        "Transformation contracts",
        "The dbt models keep owning the `raw -> staging -> intermediate -> "
        "marts` layers and the deterministic exact click-id attribution rules; "
        "the consumer still reads the same published mart contracts.",
    ),
    (
        "Read-only consumption",
        "The walkthrough stays a thin read-only consumer of the published "
        "relations — now served from BigQuery marts instead of DuckDB — and "
        "never re-implements attribution or business joins.",
    ),
    (
        "Existing BigQuery-shaped asset",
        "The repository already ships `sql/bigquery/attribution_health.sql`, "
        "a BigQuery-compatible read over `marts.mart_attribution_health`; it "
        "shows the mart contract is already consumable in that shape.",
    ),
)

# Closing boundary: this is an outline, not a delivered infrastructure change.
NOT_IMPLEMENTED_NOTE = (
    "Nothing on this page is implemented in this repository: there are no "
    "BigQuery datasets, no Terraform configuration, and no CI/CD pipeline. "
    "It only describes the direction a production evolution would take while "
    "the delivered solution stays local and self-contained."
)


def render() -> None:
    st.header("What I'd do next")
    st.write(NEXT_STEPS_INTRO)

    st.subheader("Where this would go")
    st.code(PRODUCTION_ARCHITECTURE, language=None)
    st.caption(PRODUCTION_SUPPORT)

    st.subheader("What changes")
    for title, body in WHAT_CHANGES:
        st.markdown(f"- **{title}** — {body}")

    st.subheader("What stays the same")
    for title, body in WHAT_STAYS:
        st.markdown(f"- **{title}** — {body}")

    st.caption(NOT_IMPLEMENTED_NOTE)
