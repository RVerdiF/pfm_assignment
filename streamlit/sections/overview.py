"""Overview / context page for the PFM walkthrough.

The first screen explains the assignment's purpose before any chart is shown:
TrackNow records conversions with a commission, PostHog records sessions, and
the pipeline measures how many conversions can be related to a session by an
exact click identifier. It separates the two populations the exercise talks
about - the production system with its REPORTED 18% unmatched gap (an
assignment premise, never re-derived here) and the anonymised sample this app
executes on - then shows the real architecture - Excel sample, Polars
ingestion, DuckDB raw, dbt staging / intermediate / marts, and this read-only
Streamlit app - with a one-line responsibility per layer, confirms the app is
connected read-only to the published marts, and points to the deeper pages.

All numbers and relations shown come from dbt-published relations: the
consumer marts plus the single ``intermediate.int_unmatched_conversions``
diagnostic view (ADR 8) that the analysis and methodology pages read for the
non-match reason taxonomy. This page never re-implements attribution or
business joins.
"""
from __future__ import annotations

import streamlit as st

from sections._components import require_connection

# Architecture diagram, rendered via Mermaid with visual separation across pipeline stages:
# Source -> Ingestion -> Warehouse -> Transformation -> Consumption.
ARCHITECTURE_MERMAID = """\
flowchart LR
    subgraph Source["Source"]
        excel["Excel sample<br/>(TrackNow & PostHog)"]
    end

    subgraph Ingestion["Ingestion"]
        ingest["Ingestion (Polars)<br/>load_excel.py"]
    end

    subgraph Warehouse["Warehouse"]
        raw["DuckDB raw<br/>raw.tracknow_checkouts<br/>raw.posthog_sessions"]
    end

    subgraph Transformation["Transformation (dbt)"]
        staging["dbt staging"]
        intermediate["dbt intermediate"]
        marts["dbt marts"]
        staging --> intermediate --> marts
    end

    subgraph Consumption["Consumption"]
        app["Streamlit<br/>read-only walkthrough"]
    end

    excel --> ingest
    ingest --> raw
    raw --> staging
    marts --> app
"""

# One-line responsibility per architecture layer, in pipeline order.
ARCHITECTURE_LAYERS = (
    (
        "Excel sample",
        "Delivered workbook containing TrackNow orders and PostHog browsing "
        "sessions, the raw inputs for this pipeline.",
    ),
    (
        "Ingestion (Polars)",
        "Reads both Excel sheets, normalizes column headers to snake_case, "
        "and loads raw records into DuckDB without applying business transforms.",
    ),
    (
        "DuckDB raw",
        "Source tables (raw.tracknow_checkouts, raw.posthog_sessions) that "
        "staging models reference as sources.",
    ),
    (
        "dbt staging",
        "Type casting, string trimming, and basic column cleaning. No "
        "business or attribution logic lives here.",
    ),
    (
        "dbt intermediate",
        "Candidate generation and attribution logic. Matches conversions to "
        "sessions using exact click IDs, with a dedicated diagnostic view "
        "explaining every unmatched row.",
    ),
    (
        "dbt marts",
        "Analytical tables for consumption: revenue per conversion, a local "
        "daily commission roll-up, and an attribution health monitoring mart.",
    ),
    (
        "Streamlit",
        "Read-only presentation layer. Queries the published marts and the "
        "diagnostic view directly, without re-implementing any joins or "
        "business logic.",
    ),
)


def render() -> None:
    st.title("PFM conversion attribution - walkthrough")
    st.write(
        "**The problem.** TrackNow records every conversion (an order) with a "
        "commission in GBP. PostHog records browsing sessions, some of which "
        "carry click identifiers. To report commission by marketing channel, "
        "we must know which session drove each conversion. When identifiers "
        "are missing or mismatched, those conversions remain unattributed."
    )

    st.subheader("Purpose of this walkthrough")
    st.write(
        "This app documents the pipeline and its results: data flow across "
        "layers, how conversions match to sessions, why unmatched rows "
        "occur in this sample, and the impact on channel reporting. "
        "The walkthrough is organized into the two assignment areas:\n\n"
        "- **Area 1 - Attribution & data modeling**: sample architecture (Overview), "
        "observed findings on the extract (Attribution analysis), and deterministic "
        "rules, production identity design, and limitations (Methodology and limitations).\n"
        "- **Area 2 - Investigation, integration & monitoring**: diagnosing the reported "
        "18% production gap (Investigation & monitoring), production data quality "
        "checks and alerting (Data quality monitoring), QuickBooks to BigQuery "
        "reconciliation design (QuickBooks reconciliation), and the engineering roadmap "
        "(What I'd do next). The Area 2 pages are design references and do not query the warehouse."
    )
    st.write(
        "The reported 18% production gap connects both areas: Area 1 shows how "
        "attribution handles identifiers and why sample rows remain unmatched, "
        "while Area 2 investigates potential production root causes and specifies "
        "monitoring to catch them."
    )

    st.subheader("The reported production problem")
    st.write(
        "**Reported production issue (from the assignment):** 18% of "
        "TrackNow conversions in the last 30 days have no matching PostHog "
        "session. That figure is an input premise of this exercise describing the production "
        "tracking stack, not this extract, and is never re-derived from the sample. "
        "It is investigated on the Area 2 Investigation & monitoring page."
    )

    connection = require_connection()

    # The sample-side number of the callout is read live from the health mart
    # (the full decided population), so it always reconciles with the marts
    # and with a PFM_DUCKDB_PATH override warehouse.
    health_row = connection.execute(
        "select coalesce(sum(total_conversions), 0), "
        "coalesce(sum(matched_conversions), 0) "
        "from marts.mart_attribution_health"
    ).fetchone()
    decided_total = int(health_row[0])
    matched_total = int(health_row[1])
    sample_match_display = (
        f"{matched_total / decided_total:.0%}" if decided_total else "-"
    )

    st.subheader("What this executable sample demonstrates")
    st.write(
        "The delivered workbook is an anonymised, bounded extract: 100 "
        "TrackNow conversions and 200 PostHog sessions. It exists so the "
        "attribution pipeline can be modelled, executed, and inspected end "
        "to end. The provided anonymised sample does not contain deterministic "
        "cross-system identifier overlap, so the local exact-match model attributes "
        "none of the sample's conversions - a factual property of this file, "
        "not a measurement of production and not a contradiction of the reported 18%."
    )
    st.info(
        "Reported production gap: **18%**\n\n"
        "Observed deterministic match rate in provided anonymised sample: "
        f"**{sample_match_display}**\n\n"
        "These numbers describe different populations and should not be "
        "compared as if one validates the other."
    )

    st.subheader("Architecture")
    st.mermaid_chart(ARCHITECTURE_MERMAID, width="stretch")
    st.caption(
        "Excel sample -> Polars ingestion -> DuckDB raw -> dbt staging -> "
        "dbt intermediate attribution -> dbt marts -> this Streamlit app "
        "(read-only)."
    )
    for layer, responsibility in ARCHITECTURE_LAYERS:
        st.markdown(f"- **{layer}** - {responsibility}")
    st.write(
        "All attribution rules run inside dbt using exact click-identifier "
        "matching (gclid, fbclid, and URL click IDs). The Streamlit app acts "
        "strictly as a presentation layer: it reads the published marts and "
        "a single diagnostic view (`intermediate.int_unmatched_conversions`) "
        "to explain why conversions were not matched, without re-implementing "
        "joins or business logic in Python (see Attribution analysis and "
        "Investigation & monitoring)."
    )
