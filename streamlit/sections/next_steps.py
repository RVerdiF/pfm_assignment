"""What I'd do next page for the PFM walkthrough.

The final page of the walkthrough. Every earlier page describes what this
assignment actually builds; this page closes the story by outlining, in a few
short architecture-oriented paragraphs, how the same solution could evolve to
a production GCP pipeline - without implementing any of it here.

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

# What changes when the local solution moves to GCP.
WHAT_CHANGES = (
    (
        "Warehouse",
        "Migrate from local DuckDB to **BigQuery** as the managed warehouse. "
        "dbt continues to own the transformations across the same layered "
        "structure: `raw -> staging -> intermediate -> marts`.",
    ),
    (
        "dbt adapter",
        "Switch to **dbt-bigquery**. SQL business logic and model contracts "
        "remain intact; adjustments are strictly adapter-specific, covering "
        "dialect syntax, partitioning, and clustering.",
    ),
    (
        "Ingestion and execution",
        "Replace manual spreadsheet loading by using **Cloud Storage** as "
        "the landing zone. Automated workflows in **Cloud Run Jobs** or "
        "Cloud Build then run ingestion and `dbt build` on scheduled triggers.",
    ),
    (
        "Infrastructure",
        "Manage all cloud resources with **Terraform**: datasets, storage "
        "buckets, service accounts, and IAM roles granted with the minimum "
        "permissions required for each stage (ingest, transform, consume).",
    ),
    (
        "CI/CD",
        "Automate validation via **GitHub Actions**: run SQLFluff, pytest, and "
        "`dbt build` in an isolated, controlled environment before deploying "
        "pipeline changes.",
    ),
    (
        "Observability",
        "Configure alerts in **Cloud Monitoring** for data freshness, job "
        "failures, sudden drops in the attribution match rate, spikes in "
        "`unmatched` or `ambiguous` conversions, or shifts in non-match "
        "reasons.",
    ),
)

# What stays the same.
WHAT_STAYS = (
    (
        "Transformation contracts",
        "The dbt models keep owning the `raw -> staging -> intermediate -> "
        "marts` lineage and deterministic attribution rules. Downstream "
        "consumers query the exact same mart contracts.",
    ),
    (
        "Read-only consumption",
        "The reporting dashboard remains a thin, read-only consumer of "
        "published marts (pointing to BigQuery instead of DuckDB), never "
        "re-implementing joins or attribution logic.",
    ),
    (
        "Existing BigQuery-shaped asset",
        "The repository already includes `sql/bigquery/attribution_health.sql`, "
        "demonstrating that the mart contract is BigQuery-compatible and "
        "ready for cloud BI tools.",
    ),
)

# Closing boundary: this is an outline, not a delivered infrastructure change.
NOT_IMPLEMENTED_NOTE = (
    "Nothing on this page is implemented in this repository: there are no "
    "BigQuery datasets, no Terraform configuration, and no CI/CD pipeline. "
    "This roadmap simply outlines the architectural path to production while "
    "keeping the delivered exercise fully local and self-contained."
)


def render() -> None:
    st.header("What I'd do next")
    st.write(NEXT_STEPS_INTRO)

    st.subheader("Where this would go")
    st.code(PRODUCTION_ARCHITECTURE, language=None)
    st.caption(PRODUCTION_SUPPORT)

    st.subheader("What changes")
    for title, body in WHAT_CHANGES:
        st.markdown(f"- **{title}** - {body}")

    st.subheader("What stays the same")
    for title, body in WHAT_STAYS:
        st.markdown(f"- **{title}** - {body}")

    st.caption(NOT_IMPLEMENTED_NOTE)
