"""Investigation & monitoring page (Area 2: Investigation, Integration & Monitoring).

Area-2 narrative for the reported production gap: the 18% reported gap as the
assignment premise, the diagnostic queries that would run against production,
and the hypotheses and fixes. Companion prose to the design pages of the same
area — the five monitoring checks and alerting/on-call live on the "Data
quality monitoring" page, and the QuickBooks reconciliation design lives on
its own page. It reads no warehouse relation, renders no chart, and states
the boundary: production tables were not delivered, so nothing here is
executed.
"""
from __future__ import annotations

import streamlit as st

PAGE_INTRO = (
    "This page is Area 2's investigation narrative: what the reported 18% "
    "production gap is, how it would be investigated against production, and "
    "how the pipeline that closes it would be monitored. The real production "
    "tables were not delivered, so nothing below is executed here — these "
    "are the queries and hypotheses that would run against production. The "
    "provided anonymised sample cannot confirm or refute any of them. The "
    "attribution method and sample interpretation remain on the Area 1 "
    "Methodology page."
)

# Pointer to the area's design pages — the six Investigation & Monitoring
# elements required by the assignment's Area 2: elements 1-3 on this page,
# elements 4-6 on the companion design pages. A pointer, not duplication:
# each element lives in exactly one place.
AREA_MAP = (
    (
        "Reported 18% gap",
        "below — the assignment premise and what it claims",
    ),
    (
        "Investigation queries",
        "below — six pseudo-BigQuery diagnostics, in the order I would trust them",
    ),
    (
        "Hypotheses and fixes",
        "below — six hypotheses, each with a test and a fix",
    ),
    (
        "QuickBooks reconciliation design",
        "the QuickBooks reconciliation page of this area "
        "(docs/quickbooks_reconciliation_design.md)",
    ),
    (
        "Five monitoring checks",
        "the Data quality monitoring page of this area "
        "(docs/commission_monitoring_design.md)",
    ),
    (
        "Alerting / on-call",
        "the Data quality monitoring page of this area — severity routing "
        "and the alert payload",
    ),
)

# Constants below are the investigation narrative, relocated verbatim from
# the Area 1 Methodology page (streamlit/sections/methodology.py) so the
# Area 2 content sits in the Area 2 navigation group. The sketches are not
# executed code. No column is invented — every field either exists in the
# documented staging schema or is explicitly named as a hypothetical bridge
# column with its role stated.
INVESTIGATION_QUERIES = (
    (
        "Query 1 — Daily baseline of the gap",
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
        "Query 2 — Identifier coverage",
        "Measure how often each attribution key is even present: missing "
        "`click_id`, missing `affiliate_session_id`, presence of an "
        "attribution bridge record, and conversions that carry an identifier "
        "yet still fail to resolve a PostHog session.",
        """\
select
  count(*)                                                        as conversions,
  countif(t.click_id is null)                                     as missing_click_id,
  countif(t.affiliate_session_id is null)                         as missing_affiliate_session_id,
  countif(bridge.click_id is not null)                            as with_bridge_record,
  countif(bridge.click_id is not null
          and bridge.session_id is null)                          as bridge_but_no_session
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
where t.created_date >= date_sub(current_date(), interval 30 day);""",
    ),
    (
        "Query 3 — Gap by channel",
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
        "Query 4 — Gap by TrackNow-side dimensions",
        "Break the unmatched cohort down by the TrackNow conversion's own "
        "dimensions: firm, trading platform, and first-order status. A gap "
        "concentrated in a specific firm or platform points at that partner's "
        "integration. The PostHog session is missing by definition on the "
        "unmatched rows, so every dimension comes from the TrackNow conversion "
        "itself — no PostHog field is sourced, and no column is invented beyond "
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
    (
        "Query 5 — Conversion lag (cross-session loss)",
        "Measure the lag between the first/paid session, the affiliate "
        "click, and the conversion. Long lags expose conversions lost to "
        "lookback-window expiry or cross-session identity breaks rather "
        "than to broken click tracking.",
        """\
select
  t.conversion_id,
  date_diff(t.created_at, bridge.session_start_at, hour)  as session_lag_hours,
  date_diff(t.created_at, bridge.attribution_generated_at, hour) as bridge_lag_hours
from tracknow.conversions t
join attribution.bridge bridge
  on bridge.click_id = t.click_id
where t.created_date >= date_sub(current_date(), interval 30 day)
order by session_lag_hours desc;""",
    ),
    (
        "Query 6 — Attribution bridge propagation audit",
        "Audit whether the identifier captured at the outbound affiliate click "
        "is the same one that reappears on the conversion. Requires a stable "
        "click identifier (e.g. event_id or click_ref) that links the outbound "
        "click to the conversion independently of the attribution bridge. "
        "Without this documented key, the audit cannot distinguish propagation "
        "loss from a join miss.",
        """\
-- Audit: does the click identifier survive from outbound click to conversion?
-- Requires a stable click key (e.g. event_id, click_ref) that identifies the
-- same click event across both tables, independent of the attribution bridge.
-- Without this documented key, this audit cannot run as written.
select
  oc.click_id as outbound_click_id,
  c.click_id  as conversion_click_id,
  oc.click_id is distinct from c.click_id as click_id_changed,
  c.affiliate_session_id is distinct from oc.affiliate_session_id
                                                               as session_id_changed,
  count(*) as conversions
from tracknow.conversions c
join tracknow.outbound_clicks oc
  on oc.event_id = c.event_id   -- hypothetical stable click key
where c.created_date >= date_sub(current_date(), interval 30 day)
group by 1, 2, 3, 4
order by conversions desc;""",
    ),
)

# The hypothesis set for the reported gap. Each hypothesis names the test
# that would confirm it and the fix that would follow — none is claimed to
# be proven by the delivered sample.
INVESTIGATION_HYPOTHESES = (
    (
        "Hypothesis 1 — Identifier lost before the bridge",
        "`gclid` / `fbclid` exists on the landing session but is never "
        "persisted or propagated onto the affiliate link, so TrackNow "
        "receives a click it cannot tie to PostHog.",
        "**Test:** compare identifier coverage along the funnel — landing "
        "session vs affiliate outbound click vs TrackNow conversion (queries "
        "2 and 6).",
        "**Fix:** persist ad-click identifiers first-party and attach them "
        "consistently to the affiliate redirect.",
    ),
    (
        "Hypothesis 2 — Cross-session conversion",
        "The user enters through paid traffic but converts in a later "
        "session, so the converting session carries no click identifier and "
        "the original paid session is never linked.",
        "**Test:** find `distinct_id`s with an earlier paid session and a "
        "later conversion session that carries no click parameter (queries 1 "
        "and 5).",
        "**Fix:** keep first-party attribution state per user/browser for a "
        "defined window, so late conversions still resolve to the acquiring "
        "click.",
    ),
    (
        "Hypothesis 3 — Cross-device / cookie reset / incognito",
        "The PostHog `distinct_id` changes before purchase (new device, "
        "cleared cookies, incognito), so the converting identity never saw "
        "the ad click.",
        "**Test:** unmatched conversions broken down by firm/trading "
        "platform/first-order status (query 4), plus identity-reset "
        "analysis over the identities that do resolve.",
        "**Fix:** identity stitching on login/account identifier, keeping an "
        "anonymous-to-known mapping so pre-login sessions survive.",
    ),
    (
        "Hypothesis 4 — Redirect stripping / affiliate integration issue",
        "An affiliate network or redirect template strips query parameters, "
        "so the click identifier never reaches TrackNow.",
        "**Test:** unmatched rate by firm / trading platform (query 4) "
        "and by acquired channel (query 3) to expose specific partners "
        "losing parameters (query 6).",
        "**Fix:** repair the redirect template and add automated tracking "
        "QA that asserts parameter survival end to end.",
    ),
    (
        "Hypothesis 5 — Consent / ad blocker / PostHog collection gap",
        "The TrackNow conversion happens, but the PostHog session is never "
        "recorded client-side (consent not granted, blocker, script "
        "failure).",
        "**Test:** unmatched conversions broken down by firm/trading "
        "platform/first-order status (query 4), plus a comparison of "
        "server-side TrackNow volume against client-side analytics volume "
        "over time (query 1).",
        "**Fix:** capture the critical identifiers server-side or route "
        "analytics through a first-party tracking endpoint.",
    ),
    (
        "Hypothesis 6 — Ingestion latency / freshness",
        "The two systems land data at different speeds, so conversions are "
        "counted as unmatched until the matching PostHog session arrives.",
        "**Test:** re-run the match over an older window and count records "
        "that flip from unmatched to matched after reprocessing (query 1 "
        "repeated over time).",
        "**Fix:** late-arriving-data handling with incremental lookback "
        "reprocessing instead of point-in-time matching.",
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
        "The assignment's Area 2 asks for six elements. The first three are "
        "the investigation narrative on this page; the last three are the "
        "designs on the area's companion pages."
    )
    for element, where in AREA_MAP:
        st.markdown(f"- **{element}** — {where}")

    st.subheader("The reported 18% gap")
    st.write(
        "**Reported production issue (assignment premise):** 18% of TrackNow "
        "conversions in the last 30 days have no matching PostHog session. "
        "That figure is an input premise of this exercise — it describes the "
        "production tracking stack, not the delivered file — and it is never "
        "re-derived from the sample."
    )
    st.caption(
        "Each sketch is pseudo-BigQuery SQL over the documented production "
        "contract (TrackNow conversions, PostHog sessions, and the attribution "
        "bridge): no column is invented — every field either exists in the "
        "documented staging schema or is explicitly named as a hypothetical "
        "bridge column with its role stated."
    )

    st.markdown("##### Investigation queries")
    for title, purpose, sketch in INVESTIGATION_QUERIES:
        st.markdown(f"**{title}.** {purpose}")
        st.code(sketch, language="sql")

    st.markdown("##### Hypotheses")
    for title, body, test, fix in INVESTIGATION_HYPOTHESES:
        st.markdown(f"**{title}.** {body}")
        st.markdown(f"- {test}")
        st.markdown(f"- {fix}")

    st.markdown("##### Root-cause recommendation")
    st.write(ROOT_CAUSE_STATEMENT)
    st.write(
        "The fix is applied depending on which test wins: identifier "
        "persistence and propagation (Hypothesis 1), first-party attribution "
        "state with a defined window (Hypothesis 2), identity stitching on a "
        "login/account identifier (Hypothesis 3), redirect repair plus "
        "automated tracking QA (Hypothesis 4), server-side or first-party "
        "capture of the critical identifiers (Hypothesis 5), or late-arriving "
        "data handling with incremental lookback reprocessing (Hypothesis 6)."
    )
    st.caption(
        "Nothing on this page is executed: the production tables, the "
        "attribution bridge, and the monitoring stack it describes are not "
        "implemented in this repository. The executable pipeline remains the "
        "local DuckDB sample; the monitoring and reconciliation designs live "
        "on the area's companion pages."
    )
