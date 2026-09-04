"""Overview / context page for the PFM walkthrough.

The first screen explains the assignment's purpose before any chart is shown:
TrackNow records conversions with a commission, PostHog records sessions, and
the pipeline measures how many conversions can be related to a session by an
exact click identifier. It then shows the real architecture — Excel sample,
Polars ingestion, DuckDB raw, dbt staging / intermediate / marts, and this
read-only Streamlit app — with a one-line responsibility per layer, confirms
the app is connected read-only to the published marts, and points to the
deeper pages.

All numbers and relations shown come from dbt-published marts; this page never
re-implements attribution or business joins.
"""
from __future__ import annotations

import streamlit as st

from warehouse_bootstrap import (
    DEFAULT_DATABASE_PATH,
    EXPECTED_MARTS,
    PROJECT_ROOT,
)
from sections._components import require_connection, warehouse_readiness_banner

MART_SCHEMA = "marts"

# Architecture diagram, one node per real pipeline stage. The DOT is rendered
# client-side by Streamlit (no server-side graphviz binary required); the
# labels below describe the same stages in words, one responsibility per layer.
ARCHITECTURE_DOT = """\
digraph pfm_architecture {
  rankdir=LR;
  node [shape=box, style="rounded,filled", fontname="helvetica", fontsize=11];
  edge [fontname="helvetica", fontsize=10];
  excel [label="Excel sample\\nTrackNow conversions\\nPostHog sessions", fillcolor="#e8eef7"];
  ingestion [label="Ingestion (Polars)\\nload_excel.py", fillcolor="#fdeedd"];
  raw [label="DuckDB raw\\nraw.tracknow_checkouts\\nraw.posthog_sessions", fillcolor="#e8eef7"];
  staging [label="dbt staging\\nstg_tracknow_checkouts\\nstg_posthog_sessions", fillcolor="#e8eef7"];
  intermediate [label="dbt intermediate\\nattribution candidates\\nexact-match decision", fillcolor="#f2e6f7"];
  marts [label="dbt marts\\nfct_revenue_attribution\\nmart_attribution_health\\nfct_commission_daily_local", fillcolor="#e3f2e3"];
  app [label="Streamlit\\nread-only walkthrough", fillcolor="#f7e6e6"];
  excel -> ingestion -> raw -> staging -> intermediate -> marts -> app;
}
"""

# One-line responsibility per architecture layer, in pipeline order. This is
# the textual companion to ARCHITECTURE_DOT and mirrors the real code layout.
ARCHITECTURE_LAYERS = (
    (
        "Excel sample",
        "The delivered workbook: conversion orders (TrackNow) and browsing "
        "sessions (PostHog), the only inputs to the pipeline.",
    ),
    (
        "Ingestion (Polars)",
        "Reads both worksheets, normalizes column names to snake_case and "
        "loads the values into the DuckDB raw schema, untouched.",
    ),
    (
        "DuckDB raw",
        "Source-shaped tables (raw.tracknow_checkouts, raw.posthog_sessions) "
        "that staging reads as the declared source.",
    ),
    (
        "dbt staging",
        "Clean, typed views over raw. They trim and type the columns, but no "
        "attribution or business rule is applied here.",
    ),
    (
        "dbt intermediate",
        "Attribution preparation and decision. Candidates are listed first; "
        "int_conversion_attribution then decides each conversion with the "
        "exact click-id rules (see Methodology), and a diagnostic view "
        "explains every non-matched conversion.",
    ),
    (
        "dbt marts",
        "Consumer-facing tables: revenue/commission per conversion, the local "
        "daily commission proxy, and the attribution-health mart used for "
        "monitoring.",
    ),
    (
        "Streamlit",
        "This app. It opens the warehouse read-only and only reads the "
        "published marts; it never re-implements joins or business rules.",
    ),
)


def render() -> None:
    st.title("PFM conversion attribution — walkthrough")
    st.write(
        "**The problem.** TrackNow records every conversion (an order) with a "
        "commission in GBP. PostHog records browsing sessions, some of which "
        "carry click identifiers. To report commission by marketing channel "
        "we must know which session drove each conversion — but not every "
        "conversion carries an identifier that can be matched exactly, so a "
        "share of conversions stays unattributed."
    )

    st.subheader("Purpose of this walkthrough")
    st.write(
        "This app explains, without external documentation: **what** the data "
        "is, **how** a conversion is attributed to a session, **how much** of "
        "the sample can be attributed and why the rest cannot, and **what that "
        "means** for reporting revenue and commission by channel. The pages "
        "are ordered as that story: Overview (context + architecture), "
        "Attribution analysis (observed results), and Methodology and "
        "limitations (method, caveats, recommendations)."
    )

    st.subheader("Architecture")
    st.graphviz_chart(ARCHITECTURE_DOT)
    st.caption(
        "Excel sample -> Polars ingestion -> DuckDB raw -> dbt staging -> "
        "dbt intermediate attribution -> dbt marts -> this Streamlit app "
        "(read-only)."
    )
    for layer, responsibility in ARCHITECTURE_LAYERS:
        st.markdown(f"- **{layer}** — {responsibility}")
    st.write(
        "Attribution is decided once, in dbt, using **exact click-identifier "
        "matching** (gclid / fbclid / URL click id). The Streamlit app never "
        "re-implements joins or business rules; it only reads the published "
        "marts."
    )

    connection = require_connection()
    warehouse_readiness_banner(connection)

    st.subheader("Marts this walkthrough reads")
    counts: dict[str, int] = {}
    for mart in EXPECTED_MARTS:
        try:
            row = connection.execute(
                f'select count(*) from "{MART_SCHEMA}"."{mart}"'
            ).fetchone()
            counts[mart] = int(row[0]) if row else 0
        except Exception as exc:  # pragma: no cover - read failure is surfaced
            counts[mart] = -1
            st.error(f"Could not read marts.{mart}: {exc}")
    columns = st.columns(len(EXPECTED_MARTS))
    for mart, column in zip(EXPECTED_MARTS, columns, strict=True):
        column.metric(mart, f"{counts[mart]:,} rows")

    with st.expander("Warehouse details"):
        st.write(f"Project root: {PROJECT_ROOT}")
        st.write(f"Warehouse file: {DEFAULT_DATABASE_PATH}")
        st.write(
            "The connection is opened read-only; this app cannot mutate the "
            "warehouse."
        )
        st.write(
            "If the warehouse is missing when the app starts, it is rebuilt "
            "once per session by running ingestion and `dbt build` before the "
            "read-only connection is opened."
        )
