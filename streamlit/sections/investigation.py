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
    "the diagnostic queries and hypotheses below reflect the investigation I would "
    "run in BigQuery. The provided anonymised sample cannot confirm or refute "
    "any of them. The attribution logic and sample findings remain on the Area 1 "
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
        "four diagnostic BigQuery queries in expanders to isolate where tracking breaks (below)",
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

# Constants below are the investigation narrative, relocated verbatim from
# the Area 1 Methodology page (streamlit/sections/methodology.py) so the
# Area 2 content sits in the Area 2 navigation group. The sketches are not
# executed code. No column is invented - every field either exists in the
# documented staging schema or is explicitly named as a hypothetical bridge
# column with its role stated.
INVESTIGATION_QUERIES = (
    (
        "Query 1 - Daily baseline of the gap",
        "Confirm the trend and temporal concentration of the reported "
        "unmatched share before any breakdown is trusted.",
        """\
-- Trend and temporal concentration of the reported gap.
-- Verifies the PostHog session actually exists, not just that the bridge
-- resolved a session_id: TrackNow LEFT JOIN bridge LEFT JOIN PostHog,
-- unmatched = ph.session_id IS NULL.
select
  t.conversion_date,
  count(*)                                                      as conversions,
  countif(ph.session_id is null)                                as unmatched,
  countif(ph.session_id is null) / count(*)                     as unmatched_rate
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
left join posthog.sessions ph
  on ph.session_id = bridge.session_id
where t.created_date >= date_sub(current_date(), interval 30 day)
group by t.conversion_date
order by t.conversion_date;""",
    ),
    (
        "Query 2 - Identifier coverage",
        "Measure how often each attribution key is even present: missing "
        "`click_id`, missing `affiliate_session_id`, presence of an "
        "attribution bridge record, and conversions that carry an identifier "
        "yet still fail to resolve a live PostHog session (the bridge's "
        "session_id is absent or dangling).",
        """\
select
  count(*)                                                        as conversions,
  countif(t.click_id is null)                                     as missing_click_id,
  countif(t.affiliate_session_id is null)                         as missing_affiliate_session_id,
  countif(bridge.click_id is not null)                            as with_bridge_record,
  -- bridge present but no live PostHog session: the bridge has no
  -- session_id or its session_id no longer exists in PostHog (dangling),
  -- matching the reported-gap definition used in Queries 1/3/4
  countif(bridge.click_id is not null
          and ph.session_id is null)    as bridge_but_no_posthog_session
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
left join posthog.sessions ph
  on ph.session_id = bridge.session_id
where t.created_date >= date_sub(current_date(), interval 30 day);""",
    ),
    (
        "Query 3 - Gap by channel",
        "Split unmatched conversions by acquiring channel: Google, Meta, and "
        "other/unknown. A gap concentrated in one ad platform points at that "
        "platform's click-identifier plumbing.",
        """\
select
  bridge.acquired_channel,   -- 'google' | 'meta' | 'other', from the bridge
  count(*)                                 as conversions,
  -- unmatched = no matching PostHog session, consistent with Queries 1/4:
  -- a bridge row whose session_id no longer exists in PostHog is unmatched,
  -- so PostHog is joined through the bridge and rows without a live
  -- PostHog session (ph.session_id is null) are counted as unmatched
  countif(ph.session_id is null)           as unmatched,
  countif(ph.session_id is null) / count(*) as unmatched_rate
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
left join posthog.sessions ph
  on ph.session_id = bridge.session_id
where t.created_date >= date_sub(current_date(), interval 30 day)
group by bridge.acquired_channel
order by unmatched desc;""",
    ),
    (
        "Query 4 - Gap by TrackNow-side dimensions",
        "Break the unmatched cohort down by the TrackNow conversion's own "
        "dimensions: firm, trading platform, and first-order status. A gap "
        "concentrated in a specific firm or platform points at that partner's "
        "integration. The PostHog session is missing by definition on the "
        "unmatched rows, so every dimension comes from the TrackNow conversion "
        "itself - no PostHog field is sourced, and no column is invented beyond "
        "the documented TrackNow schema (firm_id, trading_platform, first_order).",
        """\
-- The unmatched cohort has no PostHog session by definition, so the
-- breakdown uses only TrackNow's own documented fields: firm_id,
-- trading_platform, first_order. No ph.* dimension, no invented telemetry.
select
  t.firm_id,
  t.trading_platform,
  t.first_order,
  count(*) as unmatched_conversions
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
left join posthog.sessions ph
  on ph.session_id = bridge.session_id
where t.created_date >= date_sub(current_date(), interval 30 day)
  and ph.session_id is null     -- unmatched cohort: session not in PostHog
group by 1, 2, 3
order by unmatched_conversions desc;""",
    ),
)

# The hypothesis set for the reported gap. Each hypothesis names the test
# that would confirm it and the fix that would follow - none is claimed to
# be proven by the delivered sample.
INVESTIGATION_HYPOTHESES = (
    (
        "Hypothesis 1 - Identifier lost before or at affiliate redirect",
        "`gclid` / `fbclid` exists on the landing session but is never "
        "persisted or attached to the affiliate outbound link, so TrackNow "
        "receives a click it cannot tie to PostHog.",
        "**Test:** compare identifier coverage in Query 2 (missing click_id "
        "vs with_bridge_record) and channel breakdown in Query 3.",
        "**Fix:** persist ad-click identifiers first-party and attach them "
        "consistently to the affiliate outbound redirect.",
    ),
    (
        "Hypothesis 2 - Cross-session conversion & identity expiration",
        "The user enters through paid traffic but converts in a later "
        "session or after cookie reset, so the converting session carries no "
        "click identifier and the original ad click is never linked.",
        "**Test:** inspect daily trend in Query 1 and first-order breakdown "
        "in Query 4 alongside multi-session identity tracking.",
        "**Fix:** keep first-party attribution state per user/browser for a "
        "defined lookback window and stitch identities upon login.",
    ),
    (
        "Hypothesis 3 - Partner / affiliate platform parameter stripping",
        "An affiliate network or partner trading platform strips query "
        "parameters on redirect or checkout, so the click identifier never reaches TrackNow.",
        "**Test:** unmatched rate breakdown by `firm_id` and `trading_platform` "
        "(Query 4) and by `acquired_channel` (Query 3).",
        "**Fix:** standardize redirect parameter templates with partner networks "
        "and add automated tracking QA tests asserting parameter survival.",
    ),
    (
        "Hypothesis 4 - Client-side collection drop (ad blockers / consent)",
        "The TrackNow conversion happens server-side, but the PostHog session "
        "is never recorded client-side (consent not granted, ad blocker, script "
        "failure).",
        "**Test:** compare server-side TrackNow volume against client-side "
        "analytics volume over time (Query 1) across devices/platforms.",
        "**Fix:** capture critical conversion identifiers server-side or route "
        "analytics through a first-party tracking endpoint.",
    ),
)

# The root-cause boundary, stated verbatim in the walkthrough: the sample
# cannot prove which production mechanism drives the reported gap.
ROOT_CAUSE_STATEMENT = (
    "The provided anonymised sample does not contain a deterministic "
    "cross-system identity overlap. The investigation above is designed to "
    "isolate whether the gap comes from identifier capture, propagation, "
    "identity persistence, client-side collection, or ingestion latency."
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
        "Queries use BigQuery SQL over documented production contracts "
        "(TrackNow conversions, PostHog sessions, and the attribution bridge). "
        "Any hypothetical fields beyond current schemas are explicitly noted."
    )

    st.markdown("##### Diagnostic queries (BigQuery)")
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
        "persistence and propagation across affiliate redirects (Hypothesis 1), "
        "introducing first-party multi-session attribution state (Hypothesis 2), "
        "repairing affiliate partner redirect parameter stripping (Hypothesis 3), "
        "or routing client-side analytics through a first-party proxy / server-side capture (Hypothesis 4)."
    )
    st.caption(
        "This page is a design reference and does not query the warehouse: the "
        "production tables and attribution bridge described here were not delivered "
        "and are not implemented in this repository. Executable logic is confined to the "
        "local DuckDB sample."
    )
