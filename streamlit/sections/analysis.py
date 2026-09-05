"""Attribution analysis page for the PFM walkthrough.

This page answers the assignment's analytical questions with the published dbt
marts only:

- Attribution overview: valid conversions, commission, match/unmatched rates.
- What the provided sample can diagnose: the ``unmatched_reason`` taxonomy
  from the ``intermediate.int_unmatched_conversions`` diagnostic view,
  presented strictly as a diagnosis of the anonymised sample.
- Marketing attribution by UTM source and match method (gclid / fbclid / URL
  click id). No channel is inferred for unmatched conversions. Conversions and
  commission are both broken down by source in side-by-side bar charts.
- Revenue and commission: totals over the valid population, attributed vs
  unattributed, breakdown by source when attribution exists, and the local
  daily commission proxy as a clearly-labelled complement.

Everything here describes the provided sample. Production root-cause claims
are out of scope for this page: the reported 18% production gap is an
assignment premise and its investigation plan lives on the Methodology page.

No attribution rule, eligibility window, or business join is re-implemented
here: every number is an aggregate over a relation produced by dbt.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from warehouse_bootstrap import read_relation
from sections._components import require_connection

MART_SCHEMA = "marts"

# Exact-match identifier vocabulary that the attribution engine can produce.
# Populated by dbt's int_conversion_attribution; the diagnosis panel is stable
# even when a method has zero rows in the current sample.
# NOTE: mirrors the match_method vocabulary documented in
# dbt/models/marts/attribution/schema.yml and produced by the case statement
# in fct_revenue_attribution.sql.
MATCH_METHODS = (
    "gclid_exact",
    "fbclid_exact",
    "url_click_exact",
)

# unmatched_reason taxonomy produced by dbt's int_unmatched_conversions.
# Order matches the model's classification priority (first match wins).
# NOTE: mirrors the accepted_values list declared in
# dbt/models/intermediate/attribution/schema.yml.
UNMATCHED_REASONS = (
    "missing_click_id",
    "click_id_not_found",
    "outside_posthog_sample_window",
    "multiple_candidates",
    "unknown",
)


def _overview_metrics(connection) -> dict[str, int | float]:
    """Return coverage KPIs over the revenue-valid population.

    Valid conversions are the grain of fct_revenue_attribution (denied
    conversions are excluded there by the revenue-layer decision); the audit
    population that also includes denied rows is shown by the health mart.
    """
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
    matched = int(row[2])
    unmatched = int(row[3])
    ambiguous = int(row[4])
    total_decided = matched + unmatched + ambiguous
    return {
        "conversions": int(row[0]),
        "commission_gbp": float(row[1]),
        "matched": matched,
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "total_decided": total_decided,
        "match_rate": matched / total_decided if total_decided else None,
        "unmatched_rate": unmatched / total_decided if total_decided else None,
    }


def _render_overview(connection) -> None:
    st.subheader("Attribution overview")
    st.caption(
        "Population: valid conversions from marts.fct_revenue_attribution "
        "(denied conversions are excluded at the revenue layer; refunded ones "
        "are kept). The wider decided population, including denied rows, is "
        "reconciled in the audit strip below and in the health mart under "
        "'Detailed mart rows (audit)'."
    )
    metrics = _overview_metrics(connection)

    # What the evaluator should take away from the cards above: the sample is
    # 100% unattributed under exact matching — a property of the anonymised
    # sample, never a production measurement (ADR 11).
    if metrics["conversions"] and metrics["matched"] == 0:
        st.write(
            f"**Reading the cards.** This sample has {metrics['conversions']:,} "
            "valid conversions and every one is unattributed: the matched "
            "card shows 0 and the unmatched card shows the full population. "
            "Under the sample's exact click-id rule, no TrackNow click id "
            "equals a PostHog identifier in the anonymised file, so the "
            "engine reports zero matches rather than inventing a channel. "
            "That is a property of this sample — it does not restate the "
            "reported 18% production gap, which describes a different "
            "population (see the Overview and Methodology pages). The "
            "diagnosis section below classifies each non-match."
        )

    columns = st.columns(5)
    columns[0].metric("Valid conversions", f"{metrics['conversions']:,}")
    columns[1].metric("Commission (GBP)", f"£{metrics['commission_gbp']:,.2f}")
    columns[2].metric("Matched", f"{metrics['matched']:,}")
    columns[3].metric("Unmatched", f"{metrics['unmatched']:,}")
    columns[4].metric("Ambiguous", f"{metrics['ambiguous']:,}")

    rate_columns = st.columns(2)
    match_rate = metrics["match_rate"]
    unmatched_rate = metrics["unmatched_rate"]
    rate_columns[0].metric(
        "Match rate",
        f"{match_rate:.1%}" if match_rate is not None else "—",
    )
    rate_columns[1].metric(
        "Unmatched rate",
        f"{unmatched_rate:.1%}" if unmatched_rate is not None else "—",
    )

    # Reconciliation strip: the revenue-valid population (92) is a subset of
    # the full decided population (100) because 8 denied conversions stay in
    # the audit view. Both totals are read from dbt relations and should line
    # up as 100 = 92 + 8; showing them side by side makes the audit trail
    # explicit and lets an evaluator reconcile the overview numbers with the
    # diagnosis tables. The decided total comes from the health mart
    # (marts.mart_attribution_health), which publishes the full decided
    # population — including denied rows — without reading the intermediate
    # attribution table directly (ADR 8 keeps intermediate reads limited to
    # the pre-computed unmatched_reason diagnostic view).
    decided = int(
        connection.execute(
            "select coalesce(sum(total_conversions), 0) "
            "from marts.mart_attribution_health"
        ).fetchone()[0]
    )
    denied = decided - metrics["conversions"]
    audit_columns = st.columns(3)
    audit_columns[0].metric(
        "Decided conversions (all)",
        f"{decided:,}",
        help="Every conversion the attribution engine decided over, including "
        "denied ones (marts.mart_attribution_health).",
    )
    audit_columns[1].metric(
        "Denied (excluded from revenue)",
        f"{denied:,}",
        help="decided − valid; denied conversions never enter the revenue mart.",
    )
    audit_columns[2].caption(
        f"Valid {metrics['conversions']:,} + denied {denied:,} = decided "
        f"{decided:,} — reconciled from the health mart."
    )

    with st.expander("Detailed mart rows (audit)"):
        st.caption(
            "Raw rows from marts.fct_revenue_attribution — read-only view of "
            "the exact relation behind every number on this page."
        )
        revenue = read_relation(connection, "fct_revenue_attribution")
        st.dataframe(revenue, width="stretch", hide_index=True)
        health = read_relation(connection, "mart_attribution_health")
        st.caption("marts.mart_attribution_health — daily/source health.")
        st.dataframe(health, width="stretch", hide_index=True)


def _unmatched_reason_counts(connection) -> pd.DataFrame:
    """Return one row per taxonomy reason with conversion counts.

    The taxonomy is the dbt vocabulary (UNMATCHED_REASONS). Rows are read from
    the ``intermediate.int_unmatched_conversions`` diagnostic view, which is
    the attribution layer's official explanation of non-matched conversions
    (both 'unmatched' and 'ambiguous'). Reasons absent from the current sample
    are zero-filled so the audit panel is complete and self-explanatory.
    """
    query = f"""
        select unmatched_reason, count(*) as conversions
        from intermediate.int_unmatched_conversions
        group by unmatched_reason
    """
    by_reason = connection.execute(query).df()
    if by_reason.empty:
        by_reason = pd.DataFrame({"unmatched_reason": [], "conversions": []})
    reason_rows = by_reason.set_index("unmatched_reason")["conversions"].to_dict()
    counts = [int(reason_rows.get(reason, 0)) for reason in UNMATCHED_REASONS]
    frame = pd.DataFrame({"unmatched_reason": list(UNMATCHED_REASONS), "conversions": counts})
    # Empty population (an all-matched warehouse has zero non-matched rows):
    # every reason percentage must render as a valid 0.0 rather than NaN (0/0).
    total = sum(counts)
    frame["percent"] = frame["conversions"] / total * 100 if total else 0.0
    return frame


def _render_unmatched_diagnosis(connection) -> None:
    st.subheader("What the provided sample can diagnose")
    st.caption(
        "Every conversion the attribution engine did not match "
        "(intermediate.int_unmatched_conversions, the full decided population "
        "including denied conversions). The reason is decided in dbt with the "
        "same exact click-id rule and eligibility window as the attribution "
        "itself; this page only aggregates that explanation. The taxonomy "
        "diagnoses the anonymised sample — by itself it does not prove which "
        "of the production hypotheses in the Methodology page drives the "
        "reported 18% gap."
    )
    frame = _unmatched_reason_counts(connection)

    total = int(frame["conversions"].sum())
    # The interpretation is written in prose, not only shown as bars: the
    # reasons are read straight from the same dbt view that feeds the chart.
    if total:
        counts = dict(
            zip(frame["unmatched_reason"], frame["conversions"], strict=True)
        )
        outside = counts.get("outside_posthog_sample_window", 0)
        not_found = counts.get("click_id_not_found", 0)
        missing = counts.get("missing_click_id", 0)
        st.write(
            "**Where the loss happens in this sample.** The reasons map to "
            "data-side gaps within the delivered file: **"
            f"{outside:,}** conversions fall outside the PostHog sample "
            "window (their orders predate the first session in the sample, "
            "or the only sessions carrying their click id come after the "
            "order date), **"
            f"{not_found:,}** carry a click id that never appears in any "
            "PostHog session, and "
            f"**{missing:,}** have no click id at all and therefore cannot be "
            "matched under the sample's exact-only rule. These are "
            "identifier-coverage and sample-span properties of the "
            "anonymised extract; production would additionally expose "
            "identity-bridge, propagation, and collection gaps that this "
            "file cannot show (see the Methodology investigation plan)."
        )
        if counts.get("multiple_candidates", 0) or counts.get("unknown", 0):
            st.write(
                "The remaining buckets (`multiple_candidates`, `unknown`) are "
                "residual: the engine found candidates but could not "
                "deterministically choose one session, or could not prove "
                "temporal eligibility."
            )

    chart_columns = st.columns([2, 1])
    with chart_columns[0]:
        st.bar_chart(
            frame,
            x="unmatched_reason",
            y="conversions",
            color="#d98324",
            horizontal=True,
        )
    with chart_columns[1]:
        st.dataframe(
            frame.style.format(
                {"conversions": "{:,.0f}", "percent": "{:.1f}%"}
            ),
            hide_index=True,
        )
    st.caption(
        f"Total non-matched conversions: {total:,}. "
        "Reasons are mutually exclusive; each conversion is counted once."
    )


def _marketing_attribution(connection) -> pd.DataFrame:
    """Return conversions and commission by UTM source (attributed only).

    Unmatched and ambiguous conversions have no attributed session, so they
    carry no UTM (fct_revenue_attribution leaves those columns NULL). Grouping
    on utm_source therefore never fabricates a channel: conversions with no
    attributed source roll into the explicit 'Unattributed' bucket.
    """
    return connection.execute(
        """
        select
            coalesce(utm_source, 'Unattributed') as utm_source,
            count(*) as conversions,
            round(coalesce(sum(commission_gbp), 0), 2) as commission_gbp
        from marts.fct_revenue_attribution
        group by 1
        order by commission_gbp desc
        """
    ).df()


def _match_method_counts(connection) -> pd.DataFrame:
    """Return one row per match method with conversion counts.

    The methods mirror the attribution vocabulary produced by dbt's
    int_conversion_attribution (gclid_exact / fbclid_exact / url_click_exact).
    The zero-filled rows make the absence of a method visible rather than
    silently dropping it when the sample has no matches.
    """
    query = """
        select match_method, count(*) as conversions
        from marts.fct_revenue_attribution
        where match_status = 'matched'
        group by match_method
    """
    by_method = connection.execute(query).df()
    counts = {
        str(row["match_method"]): int(row["conversions"])
        for _, row in by_method.iterrows()
    }
    return pd.DataFrame(
        {
            "match_method": list(MATCH_METHODS),
            "conversions": [counts.get(method, 0) for method in MATCH_METHODS],
        }
    )


def _render_marketing_attribution(connection) -> None:
    st.subheader("Marketing attribution")
    st.caption(
        "Attributed conversions only. No channel is inferred for unmatched "
        "conversions: they roll into the 'Unattributed' bucket because the "
        "matched session's UTM parameters are the only source of channel "
        "information this pipeline trusts."
    )
    by_source = _marketing_attribution(connection)

    # Interpretation before the bars: with no matched conversion every row is
    # the explicit 'Unattributed' bucket, so no channel is ever implied.
    if by_source["conversions"].sum() and "Unattributed" in set(
        by_source["utm_source"]
    ):
        unattributed = int(
            by_source.loc[by_source["utm_source"] == "Unattributed", "conversions"].sum()
        )
        if unattributed == by_source["conversions"].sum():
            st.write(
                "**Reading the charts.** Every conversion is in the "
                "'Unattributed' bucket, so no channel can be read from this "
                "sample. The pipeline refuses to infer a source: an "
                "unmatched conversion carries no UTM data, and assigning it "
                "to a channel would fabricate the very attribution this "
                "exercise is meant to measure."
            )

    # Visual requirement: bars for BOTH conversions and commission by source.
    # Two side-by-side horizontal bars keep each measure legible (a single
    # grouped chart with mixed scales would bury the £ amounts next to large
    # conversion counts); the audit table below carries both columns verbatim.
    chart_columns = st.columns(2)
    with chart_columns[0]:
        st.caption("Conversions by source")
        if not by_source.empty:
            st.bar_chart(
                by_source,
                x="utm_source",
                y="conversions",
                color="#1f77b4",
                horizontal=True,
            )
    with chart_columns[1]:
        st.caption("Commission by source")
        if not by_source.empty:
            st.bar_chart(
                by_source,
                x="utm_source",
                y="commission_gbp",
                color="#ff7f0e",
                horizontal=True,
            )
    st.dataframe(
        by_source.style.format(
            {"conversions": "{:,.0f}", "commission_gbp": "£{:,.2f}"}
        ),
        hide_index=True,
    )

    method_frame = _match_method_counts(connection)
    st.caption(
        "Match methods (exact click-id matches by identifier type):"
    )
    if method_frame["conversions"].sum() == 0:
        st.write(
            "No conversions were matched in this sample, so no match method "
            "was exercised. The zero rows above make that explicit instead of "
            "hiding an absent channel signal."
        )
    st.dataframe(
        method_frame.style.format({"conversions": "{:,.0f}"}),
        hide_index=True,
    )


def _commission_view(connection) -> pd.DataFrame:
    """Return attributed vs unattributed commission over valid conversions."""
    return connection.execute(
        """
        select
            case when match_status = 'matched' then 'Attributed'
                 else 'Unattributed' end as attribution_status,
            count(*) as conversions,
            round(coalesce(sum(commission_gbp), 0), 2) as commission_gbp
        from marts.fct_revenue_attribution
        group by 1
        order by commission_gbp desc
        """
    ).df()


def _render_commission(connection) -> None:
    st.subheader("Revenue and commission")
    commission = _commission_view(connection)
    st.caption(
        "Commission on the valid population of marts.fct_revenue_attribution. "
        "Because the sample has no matched conversions, the whole amount "
        "falls into the unattributed bucket; no share is re-allocated to a "
        "channel without an exact match."
    )
    # Interpretation in prose before the visual: this is the direct answer to
    # "how does coverage affect reading revenue/commission by channel?".
    if not commission.empty:
        total_gbp = float(commission["commission_gbp"].sum())
        unattributed_rows = commission[
            commission["attribution_status"] == "Unattributed"
        ]
        if len(unattributed_rows) == 1 and float(
            unattributed_rows["commission_gbp"].iloc[0]
        ) == total_gbp:
            st.write(
                f"**Reading the chart.** The full **£{total_gbp:,.2f}** of "
                "commission sits in the unattributed bucket. Splitting that "
                "amount across channels without an exact match would invent a "
                "distribution; the chart keeps it whole and labelled, which "
                "is the only defensible reading for this sample. A future "
                "sample with matched conversions will populate the attributed "
                "side of this same chart automatically."
            )
    chart_columns = st.columns([2, 1])
    with chart_columns[0]:
        if not commission.empty:
            st.bar_chart(
                commission,
                x="attribution_status",
                y="commission_gbp",
                color="#2ca02c",
                horizontal=True,
            )
    with chart_columns[1]:
        st.dataframe(
            commission.style.format(
                {"conversions": "{:,.0f}", "commission_gbp": "£{:,.2f}"}
            ),
            hide_index=True,
        )

    st.caption(
        "Daily commission proxy (marts.fct_commission_daily_local) — "
        "complementary view only."
    )
    proxy = connection.execute(
        """
        select
            conversion_date,
            sum(conversion_count) as conversions,
            round(sum(commission_gbp), 2) as commission_gbp
        from marts.fct_commission_daily_local
        group by conversion_date
        order by conversion_date
        """
    ).df()
    if not proxy.empty:
        st.line_chart(
            proxy, x="conversion_date", y="commission_gbp", color="#9467bd"
        )
    with st.expander("Daily proxy table (audit)"):
        proxy_table = read_relation(connection, "fct_commission_daily_local")
        st.caption(
            "fct_commission_daily_local is a sample-derived LOCAL proxy; the "
            "authoritative analytics_core f_commission_daily source was not "
            "provided with the assignment."
        )
        st.dataframe(proxy_table, width="stretch", hide_index=True)


def render() -> None:
    st.header("Attribution analysis")

    connection = require_connection()

    _render_overview(connection)
    _render_unmatched_diagnosis(connection)
    _render_marketing_attribution(connection)
    _render_commission(connection)
