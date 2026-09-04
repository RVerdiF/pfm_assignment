"""Streamlit consumer for the dbt marts.

This app is intentionally a thin consumer: all attribution decisions and
business-layer joins are made upstream in dbt marts. The app only reads the
published marts relations and presents their metrics.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "warehouse" / "pfm.duckdb"


@st.cache_resource
def get_connection(database_path: str) -> duckdb.DuckDBPyConnection:
    """Open the local warehouse read-only so the consumer cannot mutate it."""
    return duckdb.connect(database_path, read_only=True)


def read_table(connection: duckdb.DuckDBPyConnection, table_name: str):
    """Read one published mart relation as an Arrow table."""
    return connection.execute(f"select * from marts.{table_name}").to_arrow_table()


def main() -> None:
    """Render the revenue and attribution monitoring views."""
    st.set_page_config(page_title="PFM Attribution", layout="wide")
    st.title("PFM attribution and commission")
    st.caption("Read-only consumer of dbt marts in warehouse/pfm.duckdb")

    database_path = Path(os.environ.get("PFM_DUCKDB_PATH", DEFAULT_DATABASE_PATH)).expanduser()
    if not database_path.exists():
        st.error(f"Warehouse not found: {database_path}")
        st.info("Run `python ingestion/load_excel.py` and `cd dbt && dbt build` first.")
        st.stop()

    try:
        connection = get_connection(str(database_path))
        revenue = read_table(connection, "fct_revenue_attribution")
        daily_commission = read_table(connection, "fct_commission_daily_local")
        health = read_table(connection, "mart_attribution_health")
    except Exception as exc:  # Streamlit should show an actionable setup error.
        st.error(f"Could not read the dbt marts: {exc}")
        st.info("Confirm that dbt build completed and created the marts schema.")
        st.stop()

    kpi = connection.execute(
        """
        select
            count(*) as conversions,
            coalesce(sum(commission_gbp), 0) as commission_gbp,
            count(*) filter (where match_status = 'matched') as matched,
            count(*) filter (where match_status = 'unmatched') as unmatched,
            count(*) filter (where match_status = 'ambiguous') as ambiguous
        from marts.fct_revenue_attribution
        """
    ).fetchone()
    conversions, commission_gbp, matched, unmatched, ambiguous = kpi

    columns = st.columns(5)
    columns[0].metric("Valid conversions", f"{conversions:,}")
    columns[1].metric("Commission (GBP)", f"£{commission_gbp:,.2f}")
    columns[2].metric("Matched", f"{matched:,}")
    columns[3].metric("Unmatched", f"{unmatched:,}")
    columns[4].metric("Ambiguous", f"{ambiguous:,}")

    st.subheader("Revenue attribution")
    st.dataframe(revenue, width="stretch", hide_index=True)

    by_source = connection.execute(
        """
        select
            coalesce(utm_source, 'Unattributed') as utm_source,
            sum(commission_gbp) as commission_gbp,
            count(*) as conversions
        from marts.fct_revenue_attribution
        group by 1
        order by commission_gbp desc
        """
    ).to_arrow_table()
    if by_source.num_rows:
        st.bar_chart(by_source, x="utm_source", y="commission_gbp")

    st.subheader("Attribution health")
    st.dataframe(health, width="stretch", hide_index=True)

    st.subheader("Local daily commission proxy")
    st.caption("This is the sample-derived local proxy, not the unavailable authoritative analytics_core source.")
    st.dataframe(daily_commission, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
