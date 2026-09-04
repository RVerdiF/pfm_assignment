"""Shared Streamlit building blocks for the walkthrough pages."""
from __future__ import annotations

import streamlit as st

from warehouse_bootstrap import EXPECTED_MARTS, connection_for_app

MART_SCHEMA = "marts"


def require_connection():
    """Return the bootstrapped read-only connection or stop the page.

    Pages call this first. On failure a readable error is already rendered by
    ``connection_for_app``, so the caller only needs to stop rendering.
    """
    connection = connection_for_app()
    if connection is None:
        st.stop()
    return connection


def warehouse_readiness_banner(connection) -> None:
    """Render a small banner confirming the read-only marts connection."""
    rows = connection.execute(
        "select count(*) from information_schema.tables "
        f"where table_schema = '{MART_SCHEMA}'"
    ).fetchone()
    st.caption(
        f"Connected read-only to the local warehouse. "
        f"{rows[0] if rows else 0} relation(s) in the {MART_SCHEMA} schema."
    )
