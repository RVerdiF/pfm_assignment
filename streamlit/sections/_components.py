"""Shared Streamlit building blocks for the walkthrough pages."""
from __future__ import annotations

import streamlit as st

from warehouse_bootstrap import REQUIRED_RELATIONS, connection_for_app


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
    found = sum(
        1
        for schema, table in REQUIRED_RELATIONS
        if connection.execute(
            "select count(*) from information_schema.tables "
            "where table_schema = ? and table_name = ?",
            [schema, table],
        ).fetchone()[0]
        > 0
    )
    st.caption(
        f"Connected read-only to the local warehouse. "
        f"{found} of {len(REQUIRED_RELATIONS)} required relation(s) present "
        "(marts + the ADR-8 diagnostic view)."
    )
