"""Overview / context page for the PFM walkthrough.

Explains the problem this assignment addresses, the pipeline that turns the
Excel sample into attributed data, and confirms the app is connected
read-only to the published marts. Deeper analytics live on the "Attribution
analysis" page; the full narrative, methodology, limitations and
recommendations are completed in the walkthrough build-out.
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

    st.subheader("How the data reaches this app")
    st.caption(
        "Excel sample -> Polars ingestion -> DuckDB raw -> dbt staging -> "
        "dbt intermediate attribution -> dbt marts -> this Streamlit app "
        "(read-only)."
    )
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
