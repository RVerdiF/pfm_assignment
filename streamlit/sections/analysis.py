"""Attribution analysis page for the PFM walkthrough.

Card 1 scope: provide the analysis surface the later cards complete, while
preserving the read-only consumer functionality that was already delivered.
This page shows the attribution KPIs, revenue/commission by UTM source, the
attribution health monitor, and the local daily commission proxy — all read
straight from the dbt marts. No attribution rule or join is re-implemented
here.
"""
from __future__ import annotations

import streamlit as st

from warehouse_bootstrap import read_relation
from sections._components import require_connection

MART_SCHEMA = "marts"


def _kpi_row(connection) -> tuple[int, ...]:
    """Return (conversions, commission, matched, unmatched, ambiguous)."""
    row = connection.execute(
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
    return tuple(int(value) if value is not None else 0 for value in row)


def render() -> None:
    st.header("Attribution analysis")

    connection = require_connection()

    conversions, commission_gbp, matched, unmatched, ambiguous = _kpi_row(connection)
    total_decided = max(matched + unmatched + ambiguous, 1)
    match_rate = matched / total_decided
    unmatched_rate = unmatched / total_decided

    kpi_columns = st.columns(5)
    kpi_columns[0].metric("Valid conversions", f"{conversions:,}")
    kpi_columns[1].metric("Commission (GBP)", f"£{commission_gbp:,.2f}")
    kpi_columns[2].metric("Matched", f"{matched:,}")
    kpi_columns[3].metric("Unmatched", f"{unmatched:,}")
    kpi_columns[4].metric("Ambiguous", f"{ambiguous:,}")

    rate_columns = st.columns(2)
    rate_columns[0].metric("Match rate", f"{match_rate:.1%}")
    rate_columns[1].metric("Unmatched rate", f"{unmatched_rate:.1%}")

    st.subheader("Revenue attribution by UTM source")
    st.caption(
        "Only attributed conversions carry a channel; unmatched conversions "
        "roll into 'Unattributed'. No channel is inferred for them."
    )
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
    ).fetch_arrow_table()
    if by_source.num_rows:
        st.bar_chart(by_source, x="utm_source", y="commission_gbp")

    st.subheader("Revenue attribution detail")
    revenue = read_relation(connection, "fct_revenue_attribution")
    st.dataframe(revenue, width="stretch", hide_index=True)

    st.subheader("Attribution health")
    st.caption(
        "Daily/source health of the attribution machinery over the full "
        "decided population (including denied conversions)."
    )
    health = read_relation(connection, "mart_attribution_health")
    st.dataframe(health, width="stretch", hide_index=True)

    st.subheader("Local daily commission proxy")
    st.caption(
        "Sample-derived local proxy, not the unavailable authoritative "
        "analytics_core daily commission source."
    )
    daily_commission = read_relation(connection, "fct_commission_daily_local")
    st.dataframe(daily_commission, width="stretch", hide_index=True)
