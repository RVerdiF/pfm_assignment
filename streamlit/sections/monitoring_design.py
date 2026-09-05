"""Data quality monitoring design page (Area 2: Investigation, Integration & Monitoring).

Pure-prose companion to ``docs/commission_monitoring_design.md``: it presents
the five monitoring checks for the commission pipeline — what each validates,
its threshold, its P1/P2/P3 severity, its implementation, and how on-call is
notified — plus the alert routing and the monitoring architecture. It reads no
warehouse relation, renders no chart, and states the design-only boundary: the
production stack this page describes is not implemented here.
"""
from __future__ import annotations

import streamlit as st

DESIGN_INTRO = (
    "The commission pipeline needs a small, explicit set of data quality "
    "checks. Five checks cover it: source freshness, conversion grain, "
    "attribution quality, reconciliation variance, and accounting mapping "
    "coverage. Each check names what it validates, its threshold, its "
    "P1/P2/P3 severity, and how on-call is notified. This is a design "
    "answer to Area 2 of the assignment — nothing on this page is "
    "implemented in this repository."
)

# One entry per check: (name, what it validates, metric, threshold, severity,
# implementation, on-call action). The tuples mirror the tables in
# docs/commission_monitoring_design.md.
CHECKS = (
    (
        "Check 1 — Commission source freshness",
        "The official commission source arrived within SLA.",
        "max(commission_date) and/or the ingestion timestamp of the "
        "commission raw table, compared to the expected delivery calendar.",
        "P1: no new data by 10:00 UTC on the expected delivery day. P2: "
        "arrival more than 2h later than the SLA, before the critical cutoff "
        "(example thresholds, configurable).",
        "P1 — when daily financial reporting is unavailable.",
        "dbt source freshness on the commission source, or a scheduled query "
        "over a pipeline metadata table; alert when freshness exceeds the "
        "threshold.",
        "Verify the commission integration sync, the source itself, the "
        "BigQuery load, and the last dbt run — in that order.",
    ),
    (
        "Check 2 — Duplicate / invalid TrackNow conversions",
        "The grain of the conversion table: one row per conversion, "
        "primary conversion identifier present, statuses within the known set.",
        "Duplicate tracknow_order_id count; null conversion IDs; statuses "
        "outside the accepted set.",
        "Any duplicate ID > 0 → alert. Any null conversion ID > 0 → alert.",
        "P1 — duplicates can double-count revenue and commission.",
        "dbt tests: unique and not_null on tracknow_order_id, "
        "accepted_values on status, plus a singular test for the business "
        "grain.",
        "Mart publication is blocked or the run fails; decide whether to "
        "quarantine the batch and re-run ingestion.",
    ),
    (
        "Check 3 — Attribution unmatched-rate regression",
        "Attribution quality has not regressed: conversions keep joining to "
        "tracking sessions at the expected rate.",
        "unmatched_rate = unmatched_conversions / total_conversions, from "
        "mart_attribution_health.",
        "P2 if the rate exceeds 25%, or rises more than 5 percentage points "
        "above the trailing 7-day baseline. The reported ~18% production gap "
        "is an observation, not a hardcoded SLA — the baseline comes from "
        "recent history and thresholds are configuration.",
        "P2 — escalates to P1 if the unmatched rate exceeds 40% (hard ceiling) "
        "or a critical report goes dark.",
        "Scheduled query over mart_attribution_health in production, broken "
        "down by total, channel, firm, and device/browser where available.",
        "Compare against the baseline, check whether one channel or "
        "identifier source regressed, hand off to the tracking/integration "
        "owner if capture broke.",
    ),
    (
        "Check 4 — Commission reconciliation variance",
        "QuickBooks invoices and TrackNow-derived commission agree within "
        "materiality.",
        "absolute_delta and pct_delta per firm_id and reconciliation period, "
        "from int_quickbooks_tracknow_reconciliation.",
        "P1: absolute delta > £500. P2: pct delta > 5% and absolute delta > "
        "£50. P3: same sign delta for 3+ consecutive periods (regardless of "
        "materiality).",
        "P1/P2/P3 — by materiality.",
        "Monitoring query over int_quickbooks_tracknow_reconciliation "
        "(output of the reconciliation design).",
        "The alert carries firm, period, both values, and both deltas with a "
        "link to the reconciliation query; Finance is notified for P1/P2.",
    ),
    (
        "Check 5 — Firm / accounting mapping coverage",
        "Every QuickBooks invoice/customer resolves to a firm_id via the "
        "dim_firm_accounting_mapping bridge.",
        "unmapped_invoices / total_invoices from the reconciliation output.",
        "Any new unmapped invoice → P2. More than 1% of the population "
        "unmapped → P1 if reconciliation is blocked.",
        "P2 — by default; P1 only when reconciliation cannot close.",
        "dbt test / monitoring query over dim_firm_accounting_mapping and "
        "the reconciliation output (left-anti join for unmapped keys).",
        "Add the missing mapping (customer id → firm_id, never a name join), "
        "then re-run reconciliation.",
    ),
)

FIRST_CHECK_NOTE = (
    "**Build Check 1 (Commission source freshness) first.** If the source "
    "data has not arrived, every downstream check is unreliable — freshness "
    "is the precondition for the other four. It is simple to implement "
    "(one freshness query on one relation), detects failure early, cuts "
    "time-to-diagnosis, and protects reporting and reconciliation before "
    "anything else exists. Immediately after freshness, I would implement "
    "uniqueness/grain checks (Check 2), because duplicate financial rows "
    "can silently overstate revenue."
)

ALERT_FLOW = """\
data source / pipeline
    ↓
dbt build + monitoring queries
    ↓
monitoring table
    ↓
threshold evaluation
    ↓
notification
"""

ROUTING_NOTE = (
    "In production I would route P1 to the on-call paging system and P2/P3 "
    "to a dedicated data-alerts Slack channel, with Finance copied on "
    "reconciliation-specific issues."
)

ROUTING_TABLE = (
    ("P1", "On-call pager (PagerDuty/Opsgenie or equivalent)", "interrupts a human, 24/7"),
    ("P2", "Dedicated data-alerts Slack channel", "reviewed during working hours, owned by data"),
    ("P3", "Dedicated data-alerts Slack channel (or daily digest)", "tracked, no page"),
    ("Finance", "Copied/e-mailed on reconciliation-specific issues (Checks 4 and 5)", "visibility on money-impacting variance"),
)

ALERT_PAYLOAD = """\
check_name
severity
detected_at
affected_date/period
firm_id (if applicable)
observed_value
threshold
query/model
run_id
suggested first action
"""

ARCHITECTURE = """\
Airbyte / source loads
        ↓
BigQuery raw
        ↓
dbt tests + monitoring models
        ↓
monitoring mart
        ↓
scheduled evaluation
        ↓
Slack / paging
"""

ARCHITECTURE_NOTE = (
    "Implementation options, in the order I would reach for them: dbt tests "
    "and dbt source freshness (run inside the existing dbt job), scheduled "
    "queries or a dedicated monitoring model evaluated by the scheduler "
    "(Cloud Run job / dbt Cloud job), and the platform's alerting surface "
    "(Cloud Monitoring or an observability platform of choice). The local "
    "repository already exercises the equivalent contract with dbt tests "
    "and the mart_attribution_health mart."
)

NOT_IMPLEMENTED_NOTE = (
    "Nothing in this design is implemented in this repository: there is no "
    "Airbyte connection, no BigQuery deployment, no dbt Cloud job, no "
    "Cloud Monitoring alert, and no Slack/paging integration. The repo's "
    "executable pipeline remains the local DuckDB sample; this page and "
    "docs/commission_monitoring_design.md describe the production answer "
    "only."
)


def render() -> None:
    st.header("Data quality monitoring design")
    st.write(DESIGN_INTRO)

    st.subheader("The five checks")
    for name, validates, metric, threshold, severity, implementation, action in CHECKS:
        st.markdown(f"**{name}**")
        st.markdown(f"- *Validates:* {validates}")
        st.markdown(f"- *Metric:* {metric}")
        st.markdown(f"- *Threshold:* {threshold}")
        st.markdown(f"- *Severity:* {severity}")
        st.markdown(f"- *Implementation:* {implementation}")
        st.markdown(f"- *On-call:* {action}")

    st.subheader("Which check to build first")
    st.markdown(FIRST_CHECK_NOTE)

    st.subheader("Alerting / on-call")
    st.code(ALERT_FLOW, language=None)
    st.write(ROUTING_NOTE)
    st.table(
        {
            "Severity": [row[0] for row in ROUTING_TABLE],
            "Channel": [row[1] for row in ROUTING_TABLE],
            "Expectation": [row[2] for row in ROUTING_TABLE],
        }
    )
    st.markdown("**Every alert carries:**")
    st.code(ALERT_PAYLOAD, language=None)

    st.subheader("Monitoring architecture")
    st.code(ARCHITECTURE, language=None)
    st.write(ARCHITECTURE_NOTE)

    st.caption(NOT_IMPLEMENTED_NOTE)
