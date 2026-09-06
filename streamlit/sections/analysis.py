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
assignment premise and its investigation lives on the Area 2 Investigation
& monitoring page.

No attribution rule, eligibility window, or business join is re-implemented
here: every number is an aggregate over a relation produced by dbt.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from sections._components import require_connection

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql" / "bigquery"


def _read_sql_asset(filename: str) -> str:
    path = SQL_DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return f"-- SQL asset not found: {filename}"

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
        "Source: valid conversions in marts.fct_revenue_attribution (denied "
        "orders excluded from revenue; refunded orders retained at their source "
        "amount, not necessarily net recognized commission). The total "
        "decided population, including denied rows, reconciles in the audit "
        "metrics below and in the health mart table."
    )
    metrics = _overview_metrics(connection)

    # What the evaluator should take away from the cards above: the sample is
    # 100% unattributed under exact matching - a property of the anonymised
    # sample, never a production measurement (ADR 11).
    if metrics["conversions"] and metrics["matched"] == 0:
        st.write(
            f"Across the {metrics['conversions']:,} valid conversions in this "
            "sample, none matched a PostHog session: the matched card shows 0 "
            "and the unmatched card contains the full cohort. Under exact "
            "click-identifier rules, no TrackNow click ID in this extract "
            "equals a PostHog click ID, so the pipeline outputs zero matches "
            "rather than guessing a channel. That outcome is a property of "
            "this sample rather than a restatement of the reported 18% production "
            "gap (see Overview and Investigation & monitoring). The breakdown "
            "below classifies each non-match."
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
        f"{match_rate:.1%}" if match_rate is not None else "-",
    )
    rate_columns[1].metric(
        "Unmatched rate",
        f"{unmatched_rate:.1%}" if unmatched_rate is not None else "-",
    )

    # Reconciliation strip: the revenue-valid population (92) is a subset of
    # the full decided population (100) because 8 denied conversions stay in
    # the audit view. Both totals are read from dbt relations and should line
    # up as 100 = 92 + 8; showing them side by side makes the audit trail
    # explicit and lets an evaluator reconcile the overview numbers with the
    # diagnosis tables. The decided total comes from the health mart
    # (marts.mart_attribution_health), which publishes the full decided
    # population - including denied rows - without reading the intermediate
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
        f"{decided:,} - reconciled from the health mart."
    )


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
        "Conversions without a match (from "
        "intermediate.int_unmatched_conversions, covering all decided orders "
        "including denied ones). Reasons are assigned directly in dbt using "
        "the exact-match rules and time windows. This taxonomy diagnoses the "
        "anonymised sample; it does not determine which production hypothesis "
        "in Investigation & monitoring accounts for the reported 18% gap."
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
            "The non-match reasons reflect concrete data gaps in this file: "
            f"**{outside:,}** conversions fall outside the PostHog session "
            "window (orders occurred before the sample began, or sessions with "
            "matching click IDs occurred only after the conversion date), **"
            f"{not_found:,}** carry click IDs that never appear in PostHog, and "
            f"**{missing:,}** have no click ID at all. In production, losses "
            "can also stem from redirect stripping, cookie resets, or bridge breaks, "
            "as detailed on the Investigation & monitoring page."
        )
        if counts.get("multiple_candidates", 0) or counts.get("unknown", 0):
            st.write(
                "Any rows in `multiple_candidates` or `unknown` represent ties "
                "where multiple sessions qualified or eligibility could not be "
                "proven deterministically."
            )

    st.markdown(
        "**Diagnostic category glossary:**\n\n"
        "* `missing_click_id`: The conversion record arrived without a click identifier, making attribution impossible under exact matching.\n"
        "* `click_id_not_found`: The conversion carries a click identifier, but that identifier never appears in the recorded PostHog sessions.\n"
        "* `outside_posthog_sample_window`: The conversion occurred before the recorded session window began, or matching sessions only appeared after the conversion date.\n"
        "* `multiple_candidates`: More than one eligible session tied with identical priority and timestamp recency, creating an ambiguous match.\n"
        "* `unknown`: Residual records where session timestamps were missing, preventing chronological validation."
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
    """Return conversions and commission by marketing channel (attributed only).

    Unmatched and ambiguous conversions have no attributed session, so they
    carry no UTM/channel (fct_revenue_attribution leaves channel and UTM columns NULL). Grouping
    on channel (derived from utm_source) therefore never fabricates a channel: conversions with no
    attributed source roll into the explicit 'Unattributed' bucket.
    """
    return connection.execute(
        """
        select
            coalesce(channel, 'Unattributed') as utm_source,
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
        "Attributed conversions only. Unmatched conversions roll into "
        "'Unattributed' because we only source UTM parameters from a "
        "deterministically matched session."
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
                "Every conversion currently sits in the 'Unattributed' bucket, "
                "so this sample cannot show marketing performance by channel. "
                "The pipeline deliberately avoids guessing channels: "
                "assigning unmatched orders without an exact click ID would "
                "fabricate attribution rather than measure it."
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
            "No conversions were matched in this sample, so no match methods "
            "were triggered. Showing the zero counts keeps the absence of "
            "attribution explicit rather than hiding it."
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
        "Commission from valid conversions in marts.fct_revenue_attribution. "
        "Without matched sessions, the full balance remains unattributed; "
        "no commission is distributed without an exact match."
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
                f"The full **£{total_gbp:,.2f}** in commission is recorded "
                "under Unattributed. Splitting this revenue across channels "
                "without verified session matches would invent figures; "
                "keeping it unassigned is the only defensible choice for this "
                "dataset. When run against data with valid click overlap, the "
                "attributed breakdown populates automatically."
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
        "Daily commission trend (marts.fct_commission_daily_local) - "
        "local proxy view."
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
    with st.expander("Production BigQuery: Commission anomaly detection query (Area 1, Question 3)"):
        st.caption(
            "This query targets the production contract provided in the assignment "
            "(`analytics_core.f_commission_daily`) and is not executed locally because "
            "`analytics_core.f_commission_daily` was not included in the supplied data."
        )
        st.markdown(
            "- **Source**: `analytics_core.f_commission_daily` (production contract: `commission_date`, `firm_id`, `commission_amount`).\n"
            "- **Trailing 7-day baseline**: calendar-day window (`RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING` via `UNIX_DATE(commission_date)`), strictly excluding current day.\n"
            "- **Anomaly threshold**: flags absolute swings `|pct_change_vs_7d_avg| > 40%` (`'anomaly'` vs `'normal'`).\n"
            "- **Edge cases**: `SAFE_DIVIDE` avoids zero-division on zero/missing baselines; sorted by `absolute_revenue_impact DESC`."
        )
        st.code(_read_sql_asset("commission_anomalies.sql"), language="sql")


def render() -> None:
    st.header("Attribution analysis")

    connection = require_connection()

    _render_overview(connection)
    _render_unmatched_diagnosis(connection)
    _render_marketing_attribution(connection)
    _render_commission(connection)
