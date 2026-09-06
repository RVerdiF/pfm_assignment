"""Investigation & monitoring page (Area 2: Investigation, Integration & Monitoring).

Area-2 narrative for the reported production gap: the 18% reported gap as the
assignment premise, the diagnostic queries that would run against production,
and the hypotheses and fixes. Companion prose to the design pages of the same
area - the five monitoring checks and alerting/on-call live on the "Data
quality monitoring" page, and the QuickBooks reconciliation design lives on
its own page. It reads no warehouse relation, renders no chart, and states
the boundary: production tables were not delivered, so nothing here is
executed.
"""
from __future__ import annotations

import streamlit as st

PAGE_INTRO = (
    "An investigation plan for the reported 18% production gap. "
    "Because real production tables were not delivered with this assignment, "
    "the first diagnostic queries below run against the delivered dbt staging "
    "relations and the hypotheses define what to check in production. The "
    "provided anonymised sample cannot confirm or refute any production root "
    "cause. The attribution logic and sample findings remain on the Area 1 "
    "Methodology page."
)

# Pointer to the area's design pages - the six Investigation & Monitoring
# elements required by the assignment's Area 2: elements 1-3 on this page,
# elements 4-6 on the companion design pages. A pointer, not duplication:
# each element lives in exactly one place.
AREA_MAP = (
    (
        "Reported 18% gap",
        "the problem baseline and assignment premise (below)",
    ),
    (
        "Diagnostic queries",
        "four staging SQL queries in expanders to isolate where tracking breaks (below)",
    ),
    (
        "Hypotheses and fixes",
        "four concrete failure modes with test and remediation steps (below)",
    ),
    (
        "QuickBooks reconciliation design",
        "daily accounting reconciliation pipeline "
        "(docs/quickbooks_reconciliation_design.md)",
    ),
    (
        "Five monitoring checks",
        "data quality thresholds across freshness, grain, and variance "
        "(docs/commission_monitoring_design.md)",
    ),
    (
        "Alerting / on-call",
        "severity routing (P1/P2/P3) and incident response procedures",
    ),
)

# Constants below use the two delivered dbt staging relations. They are
# executable investigation sketches over the sample's actual fields, not a
# fictional production bridge. The sample cannot establish the missing
# cross-system relationship; the exact-overlap query makes that boundary
# measurable.
INVESTIGATION_QUERIES = (
    (
        "Query 1 - Dates, status and population",
        "Profile the comparable populations first: conversion dates, order "
        "status, and click-id coverage. This shows whether the reported "
        "production window can be compared with the delivered sample.",
        """\
select
  conversion_date,
  status,
  count(*) as conversions,
  countif(is_valid_conversion) as valid_conversions,
  countif(status = 'denied') as denied_conversions,
  countif(status is null) as unknown_status_rows,
  countif(click_id is null) as missing_click_id
from staging.stg_tracknow_checkouts
group by conversion_date, status
order by conversion_date, status;""",
    ),
    (
        "Query 2 - Identifier coverage",
        "Measure whether the identifiers needed for a bridge exist on each "
        "side of the delivered data: TrackNow conversion identifiers and "
        "PostHog session click identifiers. This is coverage evidence, not "
        "a claim that the fields share a namespace.",
        """\
select
  'tracknow' as source,
  count(*) as rows,
  countif(click_id is not null) as click_id_present,
  countif(affiliate_session_id is not null) as affiliate_session_id_present,
  countif(tracknow_user_id is not null) as tracknow_user_id_present,
  0 as click_id_from_url_present,
  0 as gclid_present,
  0 as fbclid_present
from staging.stg_tracknow_checkouts
union all
select
  'posthog' as source,
  count(*) as rows,
  0 as click_id_present,
  0 as affiliate_session_id_present,
  0 as tracknow_user_id_present,
  countif(click_id_from_url is not null) as click_id_from_url_present,
  countif(gclid is not null) as gclid_present,
  countif(fbclid is not null) as fbclid_present
from staging.stg_posthog_sessions;""",
    ),
    (
        "Query 3 - Exact identifier overlap",
        "Quantify the only deterministic match available in the sample: a "
        "TrackNow `click_id` equal to a PostHog `gclid`, `fbclid`, or "
        "`click_id_from_url`, with no session-token assumption.",
        """\
with posthog_ids as (
  select gclid as identifier_value
  from staging.stg_posthog_sessions
  where gclid is not null
  union
  select fbclid
  from staging.stg_posthog_sessions
  where fbclid is not null
  union
  select click_id_from_url
  from staging.stg_posthog_sessions
  where click_id_from_url is not null
),
conversion_ids as (
  select conversion_id, click_id
  from staging.stg_tracknow_checkouts
)
select
  count(*) as conversions,
  countif(c.click_id is not null) as click_id_present,
  countif(p.identifier_value is not null) as exact_overlap,
  countif(c.click_id is not null and p.identifier_value is null) as click_id_without_overlap,
  countif(p.identifier_value is not null) / nullif(count(*), 0) as exact_overlap_rate
from conversion_ids c
left join posthog_ids p on p.identifier_value = c.click_id;""",
    ),
    (
        "Query 4 - Exact overlap by firm and date",
        "Show denominators before interpreting a pattern: conversion volume, "
        "missing IDs, and exact overlap by TrackNow firm/date. This can reveal "
        "a partner or collection boundary while staying within delivered fields.",
        """\
with posthog_ids as (
  select gclid as identifier_value
  from staging.stg_posthog_sessions where gclid is not null
  union
  select fbclid
  from staging.stg_posthog_sessions where fbclid is not null
  union
  select click_id_from_url
  from staging.stg_posthog_sessions where click_id_from_url is not null
)
select
  t.conversion_date,
  t.firm_id,
  count(*) as conversions,
  countif(t.click_id is null) as missing_click_id,
  countif(t.click_id is not null and p.identifier_value is not null) as exact_overlap,
  countif(t.click_id is not null and p.identifier_value is not null)
    / nullif(count(*), 0)
    as exact_overlap_rate
from staging.stg_tracknow_checkouts t
left join posthog_ids p on p.identifier_value = t.click_id
group by t.conversion_date, t.firm_id
order by t.conversion_date, conversions desc;""",
    ),
)

# The hypothesis set for the reported gap. Each hypothesis names the test
# that would confirm it and the fix that would follow - none is claimed to
# be proven by the delivered sample.
INVESTIGATION_HYPOTHESES = (
    (
        "Hypothesis 1 - Population or window mismatch",
        "The reported 18% production denominator and the delivered sample "
        "cover different dates or status populations. A short PostHog window, "
        "denied orders, or late-arriving rows can make the rates incomparable.",
        "**Test:** use Query 1 to compare conversion dates, statuses, valid "
        "rows, and identifier coverage before comparing any unmatched rate.",
        "**Fix:** publish one denominator and date rule, then reprocess a small "
        "lookback when either source arrives late.",
    ),
    (
        "Hypothesis 2 - Missing cross-system identifier bridge",
        "Both sources contain identifiers, but the delivered data has no "
        "record that correlates TrackNow's native `click_id` with a PostHog "
        "session. The platform tokens therefore remain separate namespaces.",
        "**Test:** compare the TrackNow and PostHog coverage rows in Query 2 "
        "and the exact overlap count in Query 3.",
        "**Fix:** capture the native TrackNow `click_id` and persist the "
        "proposed bridge fields with the PostHog session and capture source.",
    ),
    (
        "Hypothesis 3 - Parameter loss at redirect or checkout",
        "A click identifier is present in one stage but is stripped before it "
        "reaches the other stage, leaving TrackNow and PostHog with no exact "
        "overlap. The sample cannot locate the exact hop without event logs.",
        "**Test:** use Query 3 and Query 4 to compare exact overlap by firm and "
        "date, retaining denominators and missing-ID counts.",
        "**Fix:** add redirect/landing checks for parameter survival and retain "
        "the native TrackNow click event used to build the bridge.",
    ),
    (
        "Hypothesis 4 - Collection failure or ingestion lag",
        "The click or session is collected, but a client-side failure or source "
        "delay leaves PostHog incomplete when conversions are evaluated. Recent "
        "dates should show a larger gap if this is the cause.",
        "**Test:** compare the date pattern and denominators in Queries 1 and 4 "
        "after applying the same freshness cutoff; the provided sample has no "
        "ingestion timestamp to prove this.",
        "**Fix:** monitor source freshness and reprocess a bounded lookback "
        "before declaring a conversion permanently unmatched.",
    ),
)

# The root-cause boundary, stated verbatim in the walkthrough: the sample
# cannot prove which production mechanism drives the reported gap.
ROOT_CAUSE_STATEMENT = (
    "The provided anonymised sample does not contain a deterministic "
    "cross-system identity overlap. The investigation above is designed to "
    "isolate whether the gap comes from identifier capture, propagation, "
    "identity persistence, or client-side collection."
)


def render() -> None:
    st.header("Investigation & monitoring")
    st.write(PAGE_INTRO)

    st.subheader("What this area covers")
    st.write(
        "Area 2 structures the investigation, integration, and monitoring into "
        "six components: the diagnostic queries and root-cause hypotheses on this "
        "page, followed by monitoring, reconciliation, and evolution designs on "
        "the companion pages."
    )
    for element, where in AREA_MAP:
        st.markdown(f"- **{element}** - {where}")

    st.subheader("The reported 18% gap")
    st.write(
        "**Reported production issue (assignment premise):** 18% of TrackNow "
        "conversions in the last 30 days have no matching PostHog session. "
        "That figure is an input premise of this exercise describing the "
        "production tracking stack, not the delivered file, and is never "
        "re-derived from the sample."
    )
    st.caption(
        "Queries use the delivered dbt staging contracts "
        "(`staging.stg_tracknow_checkouts` and `staging.stg_posthog_sessions`) "
        "and can be adapted to the production schema once its source tables "
        "are available. No bridge relation is assumed or queried."
    )

    st.markdown("##### Diagnostic queries (delivered staging data)")
    for title, purpose, sketch in INVESTIGATION_QUERIES:
        with st.expander(title):
            st.markdown(f"**Objective:** {purpose}")
            st.code(sketch, language="sql")

    st.markdown("##### Hypotheses")
    for title, body, test, fix in INVESTIGATION_HYPOTHESES:
        st.markdown(f"**{title}.** {body}")
        st.markdown(f"- {test}")
        st.markdown(f"- {fix}")

    st.markdown("##### Root-cause recommendation")
    st.write(ROOT_CAUSE_STATEMENT)
    st.write(
        "Remediation depends on which test confirms the root cause: fixing "
        "the denominator and freshness rule (Hypothesis 1), "
        "populating the native-click bridge (Hypothesis 2), "
        "repairing parameter survival (Hypothesis 3), "
        "or fixing collection and bounded reprocessing (Hypothesis 4)."
    )
    st.caption(
        "This page is a design reference and does not query the warehouse: the "
        "production tables and attribution bridge described here were not delivered "
        "and are not implemented in this repository. Executable logic is confined to the "
        "local DuckDB sample."
    )
