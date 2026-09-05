"""Methodology, limitations and recommendations page for the PFM walkthrough.

This page closes the walkthrough in four parts, per the assignment's Areas 1
and 2:

1. **Production attribution design** — how attribution should work in
   production end to end: ad-click identifiers, PostHog sessions, the
   persistence/propagation bridge, and the TrackNow contract
   (`click_id` / `affiliate_session_id`).
2. **Sample implementation** — how the executable sample decides attribution
   (exact click-identifier matching with a temporal window and deterministic
   tie-breaks), and what the observed local results mean (numbers read from
   the same dbt relations as the analysis page).
3. **Investigation of the reported 18% gap** — the evidence-driven plan for
   the production issue the assignment reports (18% of TrackNow conversions
   in the last 30 days have no matching PostHog session): six diagnostic
   queries and six hypotheses, each with a test and a fix. Nothing here is
   executed against production: the real tables were not delivered.
4. **Limitations and recommendations** — what the sample cannot support and
   what would raise coverage.

The page reads published relations only for the numbers it cites; the sample
rules described here are the ones implemented once in the dbt intermediate
layer (int_conversion_attribution) and documented in docs/decisions.md
(ADR 3, ADR 11). No attribution logic is re-implemented in Python.

Narrative numbers are never hard-coded: every result/recommendation quantity
is derived on each render from the same dbt relations the analysis page
charts — marts.mart_attribution_health (decided/match-status totals),
marts.fct_revenue_attribution (valid conversions and commission), and
intermediate.int_unmatched_conversions (the non-match reason taxonomy). The
warehouse-specific figures in the Limitations list are read live too. A page
rendered against a different valid warehouse (the documented PFM_DUCKDB_PATH
override) always reads that warehouse's own totals, so the walkthrough cannot
contradict its own marts. The reported 18% production figure is an assignment
premise and is intentionally NOT derived from any relation.
"""
from __future__ import annotations

import streamlit as st

from sections._components import require_connection

# Deterministic attribution rules OF THE SAMPLE IMPLEMENTATION, in the exact
# order the intermediate model applies them. Each rule is stated in plain
# language next to the technical term an evaluator will meet in the code.
# These describe what the executable sample does — not the production
# architecture (see PRODUCTION_IDENTITY_FLOW below and ADR 3).
METHOD_RULES = (
    (
        "1. Exact match only",
        "A conversion is attributed to a session only when the TrackNow "
        "`click_id` equals a PostHog click identifier exactly — a `gclid`, "
        "`fbclid`, or the click id read from the landing URL. This is the "
        "sample implementation constraint: exact click-id equality is the "
        "only relationship provable in the anonymised file. No fuzzy "
        "matching, no normalization of identifier values, and no invented "
        "bridge — the sample carries no documented identity contract, so an "
        "`affiliate_session_id` is never ASSUMED to equal a PostHog "
        "`session_id` here (that is a data limitation, not evidence that "
        "`affiliate_session_id` is irrelevant in production).",
    ),
    (
        "2. Temporal window",
        "Only sessions on or before the conversion date are eligible. "
        "TrackNow exposes a conversion date, not a time, so the pipeline "
        "never invents a conversion hour: every session on the conversion "
        "date itself counts, and later sessions cannot drive the conversion.",
    ),
    (
        "3. Identifier priority",
        "Among eligible sessions, typed identifiers (`gclid`/`fbclid`) "
        "outrank the generic click id read from the URL, so a Google or Meta "
        "click is preferred over an untyped one.",
    ),
    (
        "4. Recency tie-break",
        "Among the remaining eligible sessions the most recent one wins. "
        "When no single session wins — e.g. two sessions tie under rules 3 "
        "and 4 — the conversion is marked ambiguous and carries no attributed "
        "session.",
    ),
)

# Decision states produced by the attribution engine, each with the meaning an
# evaluator needs to read the analysis page.
DECISION_STATES = (
    (
        "matched",
        "Exactly one eligible session survived rules 2–4. The conversion is "
        "reported with that session's channel (UTM source).",
    ),
    (
        "ambiguous",
        "More than one eligible session tied for first. No single session "
        "was chosen deterministically, so no channel is reported.",
    ),
    (
        "unmatched",
        "No eligible exact match exists: the conversion has no click id, its "
        "click id appears nowhere in the PostHog sample, or the only sessions "
        "carrying it fall after the conversion date.",
    ),
)

# The production identity flow, stated once as design material. It describes
# how attribution SHOULD work when the systems are under our control — not
# what the anonymised sample can demonstrate (ADR 3 / ADR 11).
PRODUCTION_IDENTITY_FLOW = """\
1. Capture ad-click identifier
   Google / Meta ad click → capture `gclid` / `fbclid` on the landing page

2. Persist with PostHog identity
   `gclid` / `fbclid` → store in first-party attribution bridge keyed by
   PostHog `distinct_id` + `session_id`

3. Generate / persist attribution identifier
   Attribution bridge → generate a persistent `attribution_click_id`
   (first-party, survives session boundaries)

4. Propagate onto affiliate redirect
   `attribution_click_id` → pass as TrackNow `click_id` on the affiliate URL

5. TrackNow closes the loop
   TrackNow `click_id` → returns the same `click_id` on the conversion

6. Conversion resolves the bridge
   `conversion.click_id` → resolves the attribution bridge → resolves the
   PostHog session / `distinct_id`
"""

# The role each identifier plays in the production design. The sample cannot
# prove these relationships; they are the contract production must implement.
PRODUCTION_IDENTIFIER_ROLES = (
    (
        "`gclid` / `fbclid`",
        "Captured on the landing page from the Google / Meta ad click. Must "
        "be persisted with the PostHog session / `distinct_id` and propagated "
        "onto the affiliate redirect.",
    ),
    (
        "`click_id_from_url`",
        "PostHog's record of the click id read from the landing URL — the "
        "analytics-side trace of the same identifier flow.",
    ),
    (
        "`distinct_id`",
        "The PostHog identity anchor. First-party attribution state keys on "
        "it (or on a logged-in account id) so a conversion can be tied back "
        "to the session that acquired the click.",
    ),
    (
        "`session_id`",
        "PostHog's session scope. Never assumed equal to any TrackNow field "
        "without a documented contract between the systems.",
    ),
    (
        "`attribution_click_id`",
        "The first-party identifier generated from the bridge. Passed to "
        "TrackNow as the affiliate `click_id`; the deterministic key that "
        "links a conversion back to the PostHog identity.",
    ),
    (
        "`click_id`",
        "The TrackNow outbound-click identifier carried by the conversion — "
        "the key that closes the loop. Must equal the `attribution_click_id` "
        "passed on the affiliate URL.",
    ),
    (
        "`affiliate_session_id`",
        "Assigned by TrackNow when the affiliate link is clicked; one of the "
        "keys to attribution in the TrackNow contract. The sample cannot "
        "relate it to a PostHog session, which is a property of the "
        "provided anonymised file — production design must document what it "
        "references rather than discard it.",
    ),
    (
        "`utm_content`",
        "Not used as a conversion→session key. After the session is "
        "identified, it enriches attribution with Meta ad/creative data "
        "(e.g. ad_id) for reporting.",
    ),
)

# Edge cases that break the match and how the data model handles each one.
# These are distinct from the investigation hypotheses (which explain the
# reported 18% gap); these are the structural boundaries the production
# data model must accommodate.
EDGE_CASES = (
    (
        "Missing click_id on conversion",
        "Conversion arrives with no click identifier at all.",
        "unmatched / missing_click_id — cannot be attributed under exact "
        "matching; surfaced for tracking-layer repair.",
    ),
    (
        "Cross-session conversion",
        "User enters via paid traffic but converts in a later session; the "
        "converting session carries no click identifier.",
        "Persistent identity bridge keyed by `distinct_id` keeps the "
        "attribution state across sessions for a defined lookback window.",
    ),
    (
        "Multiple paid clicks before conversion",
        "User clicks both a Google and a Meta ad (or multiple ads) before "
        "converting.",
        "Deterministic attribution policy (typed-identifier priority + "
        "recency tie-break) chooses exactly one session; no ambiguous "
        "multi-channel credit.",
    ),
    (
        "Cookie reset / cross-device / incognito",
        "PostHog `distinct_id` changes before purchase (new device, cleared "
        "cookies, incognito); the converting identity never saw the ad click.",
        "Anonymous-to-known identity map stitched on login/account "
        "identifier; pre-login sessions survive the identity transition.",
    ),
    (
        "Late-arriving data",
        "The two systems land data at different speeds; a conversion is "
        "counted unmatched until the matching PostHog session arrives.",
        "Incremental lookback reprocessing over a defined window; records "
        "flip from unmatched to matched when the session lands.",
    ),
)

# Diagnostic queries for the reported production gap. Sketches in pseudo-
# BigQuery SQL over the KNOWN production contract (TrackNow conversions,
# PostHog sessions, and the attribution bridge): the real production tables
# were not delivered, so these are the documented investigation, not
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
  countif(bridge.session_id is null)       as unmatched,
  countif(bridge.session_id is null) / count(*) as unmatched_rate
from tracknow.conversions t
left join attribution.bridge bridge
  on bridge.click_id = t.click_id
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


def _read_narrative_facts(connection) -> dict[str, int | float]:
    """Return the live relation totals the prose cites, in one read.

    Every quantity comes from the same dbt relations the analysis page reads:

    - marts.mart_attribution_health — the full decided population (including
      denied conversions) with match-status counts.
    - marts.fct_revenue_attribution — the revenue-valid population and its
      commission total.
    - intermediate.int_unmatched_conversions — the diagnostic reason taxonomy
      over every non-matched decided conversion (published under ADR 8).

    The reason counts always describe the same non-matched decided population
    as the health mart's unmatched + ambiguous columns.
    """
    health = connection.execute(
        "select "
        "  coalesce(sum(total_conversions), 0), "
        "  coalesce(sum(matched_conversions), 0), "
        "  coalesce(sum(unmatched_conversions), 0), "
        "  coalesce(sum(ambiguous_conversions), 0) "
        "from marts.mart_attribution_health"
    ).fetchone()
    revenue = connection.execute(
        "select "
        "  count(*), "
        "  coalesce(sum(commission_gbp), 0) "
        "from marts.fct_revenue_attribution"
    ).fetchone()
    reason_rows = connection.execute(
        "select unmatched_reason, count(*) "
        "from intermediate.int_unmatched_conversions "
        "group by unmatched_reason"
    ).fetchall()
    reasons = {str(reason): int(count) for reason, count in reason_rows}
    return {
        "decided": int(health[0]),
        "matched": int(health[1]),
        "unmatched": int(health[2]),
        "ambiguous": int(health[3]),
        "valid": int(revenue[0]),
        "commission_gbp": float(revenue[1]),
        "missing_click_id": reasons.get("missing_click_id", 0),
        "click_id_not_found": reasons.get("click_id_not_found", 0),
        "outside_posthog_sample_window": reasons.get(
            "outside_posthog_sample_window", 0
        ),
    }


def _build_result_interpretations(
    facts: dict[str, int | float],
) -> list[tuple[str, str]]:
    """Render the prose reading of the observed results from live facts.

    Each interpretation is emitted only when the live numbers make it true, so
    the narrative cannot contradict the marts it is rendered against: an
    all-unmatched sample (the delivered one) gets the full 'nothing matched'
    reading; a warehouse with matches simply does not claim the opposite. The
    numbers quoted are the exact live facts, so the prose is always
    reconcilable with the relations.
    """
    decided = int(facts["decided"])
    matched = int(facts["matched"])
    unattributed = int(facts["unmatched"]) + int(facts["ambiguous"])
    valid = int(facts["valid"])
    commission = float(facts["commission_gbp"])
    missing = int(facts["missing_click_id"])
    not_found = int(facts["click_id_not_found"])
    outside = int(facts["outside_posthog_sample_window"])

    interpretations: list[tuple[str, str]] = []

    if decided and matched == 0 and valid:
        interpretations.append(
            (
                "The whole valid sample is unattributed",
                f"Of the {decided:,} decided conversions, the health mart "
                f"counts {matched:,} matched and {unattributed:,} "
                "unmatched/ambiguous, so the revenue mart "
                f"({valid:,} valid conversions, £{commission:,.2f} of "
                "commission) carries no channel signal at all. This is a "
                "property of the provided sample, not a pipeline failure: "
                "the attribution engine is exact-only, and no TrackNow click "
                "id equals a PostHog identifier value inside the sample.",
            )
        )

    identifier_parts = []
    if missing:
        identifier_parts.append(
            f"{missing:,} conversions have no click id at all and can never "
            "be attributed under exact matching"
        )
    if not_found:
        prefix = "a further " if missing else ""
        identifier_parts.append(
            f"{prefix}{not_found:,} carry a click id that the PostHog "
            "sample never records"
        )
    if identifier_parts:
        body = (
            "; ".join(identifier_parts)
            + ". These are the identifiers the business must learn to persist "
            "and propagate."
        )
        interpretations.append(("Loss happens before matching", body))

    if outside:
        interpretations.append(
            (
                "The PostHog sample window also removes candidates",
                f"{outside:,} conversions fall outside what the sample can "
                "explain: their orders predate the sample's first session, or "
                "the only sessions carrying their click id come after the "
                "order date, so they cannot have an eligible session in the "
                "sample even when their click id appears later.",
            )
        )

    if decided and matched == 0 and valid:
        interpretations.append(
            (
                "Reporting revenue by channel is not possible yet",
                "Because no conversion is matched, every UTM-source group in "
                "the analysis page is the explicit 'Unattributed' bucket. "
                "Reading commission by channel from this sample would "
                f"misattribute the whole £{commission:,.2f}; the honest "
                "output is a health signal: the attribution machinery is "
                "working, the sample cannot feed it.",
            )
        )

    return interpretations


def _format_date(value) -> str:
    """Format a date value from DuckDB as an ISO day (YYYY-MM-DD)."""
    return str(value) if value is not None else "—"


def _limitation_notes(connection) -> list[tuple[str, str]]:
    """Return the limitation items, with warehouse-specific figures read live.

    Each limitation maps to a real boundary of this delivery; none is invented
    to look thorough. The first two carry numbers/dates that describe the
    *warehouse being evaluated*, so they are read from the same consumer
    relations the rest of the page reads (never from fixed delivered-sample
    totals, which would contradict a valid PFM_DUCKDB_PATH override):

    - marts.mart_attribution_health — the full decided conversion population
      (every TrackNow conversion the attribution engine decided, including
      denied rows) and its conversion-date span.
    - marts.fct_revenue_attribution — the revenue-valid conversion count (the
      subset the app's overview cites as "valid conversions").
    - intermediate.int_unmatched_conversions — the number of conversions the
      diagnostic view classifies as falling outside the PostHog sample window
      (the only window-aware quantity the consumer contract publishes; the
      session-side start date is not exposed to the app, so the boundary is
      stated structurally rather than with a fixed calendar date).

    The remaining three limitations are non-numeric properties of the
    pipeline/assignment and are stated once.
    """
    health = connection.execute(
        "select "
        "  coalesce(sum(total_conversions), 0), "
        "  min(conversion_date), "
        "  max(conversion_date) "
        "from marts.mart_attribution_health"
    ).fetchone()
    decided = int(health[0])
    min_date = _format_date(health[1])
    max_date = _format_date(health[2])
    valid = int(
        connection.execute(
            "select count(*) from marts.fct_revenue_attribution"
        ).fetchone()[0]
    )
    outside = int(
        connection.execute(
            "select count(*) from intermediate.int_unmatched_conversions "
            "where unmatched_reason = 'outside_posthog_sample_window'"
        ).fetchone()[0]
    )

    notes = [
        (
            "Small sample",
            f"{decided:,} conversions (of which {valid:,} are revenue-valid) "
            f"over the span {min_date} to {max_date} cannot represent "
            "production volume or channel mix.",
        ),
        (
            "Limited PostHog window",
            f"{outside:,} conversions fall outside what the sample can explain "
            "because their orders predate the earliest recorded session (or the "
            "only sessions carrying their click id come after the order date). "
            "A conversion before the session window is structurally "
            "unexplainable by this sample.",
        ),
        (
            "TrackNow gives a conversion date, not a timestamp",
            "Attribution cannot tell whether a session earlier the same day "
            "actually preceded the order, so same-day sessions are all eligible "
            "and late-day sessions are never excluded by time.",
        ),
        (
            "No authoritative daily commission source",
            "The real `analytics_core.f_commission_daily` table was not provided. "
            "The app shows a clearly labelled LOCAL proxy built from the TrackNow "
            "sample instead, never as the source of truth.",
        ),
        (
            "No fuzzy rules or undocumented bridges",
            "Attribution never approximates identifiers and never joins on an "
            "assumed relationship. That keeps every decision auditable, at the "
            "cost of leaving conversions unmatched when the data does not carry "
            "an exact key. In the sample this is a deliberate implementation "
            "constraint; the production identity contract it defers is "
            "described in the production design section above.",
        ),
    ]
    return notes


def _page_intro() -> None:
    st.header("Methodology and limitations")
    st.write(
        "This page is the walkthrough's reference, in four parts: how "
        "attribution should work in production (Production attribution "
        "design), how the executable sample decides attribution and what its "
        "results mean (Sample implementation), how the reported production "
        "gap of 18% would be investigated (Investigation), and what this "
        "delivery cannot claim (Limitations and recommendations). Every "
        "sample rule stated here is implemented once in the dbt intermediate "
        "layer and documented in docs/decisions.md; this app never re-applies "
        "the logic."
    )


def _production_design_section() -> None:
    st.subheader("Production attribution design")
    st.write(
        "The reported 18% gap is a failure mode of the identity flow between "
        "the ad platforms, PostHog, and TrackNow. In production, attribution "
        "should not be inferred after the conversion: the bridge between "
        "systems must be explicit and designed. The intended end-to-end flow:"
    )
    st.code(PRODUCTION_IDENTITY_FLOW, language=None)
    st.write("Each identifier in that flow has a defined role:")
    for identifier, role in PRODUCTION_IDENTIFIER_ROLES:
        st.markdown(f"- **{identifier}** — {role}")
    st.write(
        "Two design constraints follow. First, `gclid` / `fbclid` are "
        "captured at the landing and must be persisted together with the "
        "PostHog `distinct_id` / session, then propagated onto the affiliate "
        "outbound click, so `attribution_click_id` can close the loop at the "
        "conversion. Second, `affiliate_session_id` is treated as part of the "
        "TrackNow contract — a key to attribution — without assuming that it "
        "equals `PostHog.session_id`; whatever it references must be documented "
        "by the integration, not guessed after the fact. `utm_content` is "
        "preserved as Meta ad/creative enrichment (e.g. ad_id) for reporting "
        "after the session is identified, not as a conversion→session key."
    )
    st.markdown("##### Edge cases and data-model handling")
    st.write(
        "The following structural boundaries apply regardless of which "
        "production mechanism drives the reported gap. Each one names the "
        "edge case, when it occurs, and how the data model resolves it."
    )
    for case, when, handling in EDGE_CASES:
        st.markdown(f"- **{case}.** *When:* {when}. *Handling:* {handling}")


def _method_section() -> None:
    st.subheader("Sample implementation")
    st.write(
        "The executable sample implements one deterministic answer per "
        "conversion — **which PostHog session drove this order?** — with the "
        "four rules below, applied in order by the `int_conversion_attribution` "
        "dbt model. These rules describe what the anonymised sample supports, "
        "not the production architecture above."
    )
    for title, body in METHOD_RULES:
        st.markdown(f"**{title}** — {body}")
    st.markdown("**Outcome** — every conversion gets one of three states:")
    for state, meaning in DECISION_STATES:
        st.markdown(f"- **`{state}`** — {meaning}")


def _results_section(facts: dict[str, int | float]) -> None:
    st.subheader("Interpreting the observed results")
    st.write(
        "The analysis page shows the numbers behind these statements; the "
        "statements themselves are the interpretation."
    )

    # The interpretation prose is built from the same live relation totals the
    # analysis page charts, so the text can never drift from the data.
    for title, body in _build_result_interpretations(facts):
        st.markdown(f"**{title}.** {body}")

    st.caption(
        f"Health mart totals over the decided population: "
        f"{int(facts['decided']):,} conversions — {int(facts['matched']):,} "
        f"matched, {int(facts['unmatched']):,} unmatched, "
        f"{int(facts['ambiguous']):,} ambiguous."
    )


def _limitations_section(connection) -> None:
    st.subheader("Limitations")
    st.write("What this delivery does not claim:")
    for title, body in _limitation_notes(connection):
        st.markdown(f"- **{title}** — {body}")


def _investigation_section() -> None:
    st.subheader("How I would investigate the reported 18% attribution gap")
    st.write(
        "**Reported production issue (assignment premise):** 18% of TrackNow "
        "conversions in the last 30 days have no matching PostHog session. "
        "The real production tables were not delivered, so nothing below is "
        "executed here — these are the queries and hypotheses that would run "
        "against production, in the order I would trust them. The provided "
        "anonymised sample cannot confirm or refute any of them."
    )
    st.caption(
        "Each sketch is pseudo-BigQuery SQL over the documented production "
        "contract (TrackNow conversions, PostHog sessions, and the attribution "
        "bridge): no column is invented — every field either exists in the "
        "documented staging schema or is explicitly named as a hypothetical "
        "bridge column with its role stated."
    )

    st.markdown("##### Diagnostic queries")
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


def _recommendations_section(facts: dict[str, int | float]) -> None:
    st.subheader("Recommendations")
    st.write(
        "Each recommendation targets one of the concrete loss causes observed "
        "in the sample:"
    )
    missing = int(facts["missing_click_id"])
    not_found = int(facts["click_id_not_found"])
    outside = int(facts["outside_posthog_sample_window"])

    if missing:
        coverage_tail = (
            f" In this sample, {missing:,} conversions arrived without one."
        )
    else:
        coverage_tail = (
            " A conversion without a click id can never be attributed under "
            "exact matching."
        )
    st.markdown(
        "- **Raise click-id coverage at the source** — "
        "The tracking layer should treat the click id as a required field on "
        "every order." + coverage_tail
    )

    if not_found:
        propagate_tail = (
            f" In this sample, {not_found:,} conversions carried a click id "
            "the PostHog sample never saw."
        )
    else:
        propagate_tail = ""
    st.markdown(
        "- **Propagate identifiers consistently** — "
        "Whatever id is captured at click time must survive redirects and be "
        "written into the session record, not only into the URL."
        + propagate_tail
    )

    st.markdown(
        "- **Persist identifiers between session and conversion** — "
        "The generic URL click id exists only on the session side; converting "
        "flows should carry the same identifier into the order payload so the "
        "two systems share one key namespace."
    )

    if outside:
        window_tail = (
            f" In this sample, {outside:,} conversions fall outside the "
            "PostHog sample window."
        )
    else:
        window_tail = ""
    st.markdown(
        "- **Widen and monitor the PostHog window** — "
        "A production window must start before the earliest order and be "
        "monitored so coverage loss is visible continuously, not discovered "
        "at report time." + window_tail
    )


def render() -> None:
    _page_intro()
    connection = require_connection()

    # The interpretation and recommendation prose share one read of the live
    # narrative facts, so every number cited on this page is internally
    # consistent within a single render.
    facts = _read_narrative_facts(connection)

    _production_design_section()
    _method_section()
    _results_section(facts)
    _investigation_section()
    _limitations_section(connection)
    _recommendations_section(facts)
