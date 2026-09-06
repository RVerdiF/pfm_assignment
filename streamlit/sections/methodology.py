"""Methodology, limitations and recommendations page for the PFM walkthrough.

This page is the Area 1 reference in four parts:

1. **Production attribution design** - how attribution should work in
   production end to end: ad-click identifiers, PostHog sessions, the
   persistence/propagation bridge, and the TrackNow contract
   (`click_id` / `affiliate_session_id`).
2. **dbt transformation architecture** - complete model, layer, grain, and
   key transformations catalog covering both local models and the production
   Google Sheet commission pipeline.
3. **Sample implementation** - how the executable sample decides attribution
   (exact click-identifier matching with a temporal window and deterministic
   tie-breaks), and what the observed local results mean (numbers read from
   the same dbt relations as the analysis page).
4. **Limitations and recommendations** - what the sample cannot support and
   what would raise coverage.

The investigation of the reported 18% production gap (four diagnostic queries
and four hypotheses, each with a test and a fix) lives on the Area 2
"Investigation & monitoring" page (streamlit/sections/investigation.py),
alongside the area's monitoring and reconciliation designs. Nothing there is
executed against production: the real tables were not delivered.

The page reads published relations only for the numbers it cites; the sample
rules described here are the ones implemented once in the dbt intermediate
layer (int_conversion_attribution) and documented in docs/decisions.md
(ADR 3, ADR 11). No attribution logic is re-implemented in Python.

Narrative numbers are never hard-coded: every result/recommendation quantity
is derived on each render from the same dbt relations the analysis page
charts - marts.mart_attribution_health (decided/match-status totals),
marts.fct_revenue_attribution (valid conversions and commission), and
intermediate.int_unmatched_conversions (the non-match reason taxonomy). The
warehouse-specific figures in the Limitations list are read live too. A page
rendered against a different valid warehouse (the documented PFM_DUCKDB_PATH
override) always reads that warehouse's own totals, so the walkthrough cannot
contradict its own marts. The reported 18% production figure is an
assignment premise and is intentionally NOT derived from any relation.
"""
from __future__ import annotations

import streamlit as st

from sections._components import require_connection

# Deterministic attribution rules OF THE SAMPLE IMPLEMENTATION, in the exact
# order the intermediate model applies them. Each rule is stated in plain
# language next to the technical term an evaluator will meet in the code.
# These describe what the executable sample does - not the production
# architecture (see PRODUCTION_IDENTITY_FLOW below and ADR 3).
METHOD_RULES = (
    (
        "1. Exact match only",
        "A conversion is attributed to a session only when the TrackNow "
        "`click_id` equals a PostHog click identifier exactly, such as a `gclid`, "
        "`fbclid`, or the click id read from the landing URL. This is the "
        "sample implementation constraint: exact click-id equality is the "
        "only relationship provable in the anonymised file. No fuzzy "
        "matching, no normalization of identifier values, and no invented "
        "bridge: the sample carries no documented identity contract, so an "
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
        "When no single session wins, for example when two sessions tie under rules 3 "
        "and 4, the conversion is marked ambiguous and carries no attributed "
        "session.",
    ),
)

# Decision states produced by the attribution engine, each with the meaning an
# evaluator needs to read the analysis page.
DECISION_STATES = (
    (
        "matched",
        "Exactly one eligible session survived rules 2 through 4. The conversion is "
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
# how attribution SHOULD work when the systems are under our control - not
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
        "PostHog's record of the click id read from the landing URL: the "
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
        "The TrackNow outbound-click identifier carried by the conversion, "
        "which is the key that closes the loop. Must equal the `attribution_click_id` "
        "passed on the affiliate URL.",
    ),
    (
        "`affiliate_session_id`",
        "Assigned by TrackNow when the affiliate link is clicked; one of the "
        "keys to attribution in the TrackNow contract, without assuming that it equals "
        "`PostHog.session_id`. The sample cannot "
        "relate it to a PostHog session, which is a property of the "
        "provided anonymised file: production design must document what it "
        "references rather than discard it.",
    ),
    (
        "`utm_content` / `ad_id`",
        "Not used as a conversion-to-session key. After the session is "
        "identified, it enriches attribution with Meta ad/creative data "
        "(exposing `ad_id` from `utm_content` per the source workbook) for reporting.",
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
        "unmatched / missing_click_id: cannot be attributed under exact "
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
        "Deterministic attribution policy (typed-identifier priority plus "
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
        "Redirect strips parameters",
        "An affiliate or ad-network redirect drops the click parameters, so "
        "the landing page never records the identifier the conversion "
        "carries.",
        "Redirect QA on every paid link plus server-side parameter "
        "persistence (capture the click before the redirect chain and "
        "restore it on the landing session).",
    ),
    (
        "Late-arriving data",
        "The two systems land data at different speeds; a conversion is "
        "counted unmatched until the matching PostHog session arrives.",
        "Incremental lookback reprocessing over a defined window; records "
        "flip from unmatched to matched when the session lands.",
    ),
)

# Complete dbt transformation architecture: model, layer, grain, and key
# transformations across both the executable local sample and the production
# Google Sheet daily commission pipeline.
DBT_ARCHITECTURE_TABLE = (
    (
        "stg_tracknow_checkouts",
        "Staging (Implemented / Sample)",
        "One row per TrackNow conversion (conversion_id)",
        "Reads raw.tracknow_checkouts; casts types (conversion_date to DATE, order_price_gbp and commission_gbp to DOUBLE); trims whitespace on string identifiers (empty becomes NULL); maps referral_bonus_gbp to commission_gbp; derives is_valid_conversion (status <> 'denied') under SQL three-valued logic while preserving denied orders for audit.",
    ),
    (
        "stg_posthog_sessions",
        "Staging (Implemented / Sample)",
        "One row per PostHog browsing session (session_id)",
        "Reads raw.posthog_sessions; trims identifiers and marketing params with empty strings becoming NULL (schema tests enforce not_null and unique on session_id); casts session_start_at to TIMESTAMPTZ and session_date to DATE; trims UTM parameters with case preserved; preserves click identifiers (click_id_from_url, gclid, fbclid).",
    ),
    (
        "stg_commission_daily",
        "Staging (Production Assumption)",
        "One row per (commission_date, firm_id)",
        "Production assumption: The Google Sheets commission workbook was not provided in assignment assets. The model schema, join keys, logic, and data quality checks are proposed based on the prompt specification, not validated against real production files. In production, reads raw.google_sheets_commission_daily ingested via Airbyte into BigQuery; casts column types (commission_date to DATE, amounts to NUMERIC); normalizes firm_id; validates currency; checks for nulls; deduplicates by (commission_date, firm_id).",
    ),
    (
        "int_tracknow_attribution_candidates",
        "Intermediate (Implemented / Sample)",
        "One row per TrackNow conversion (conversion_id)",
        "Projects candidate conversion identifiers (click_id, conversion_date, affiliate_session_id, tracknow_user_id) without deciding attribution; computes boolean presence flags (has_click_id, has_affiliate_session_id, has_tracknow_user_id) to monitor tracking coverage.",
    ),
    (
        "int_posthog_attribution_candidates",
        "Intermediate (Implemented / Sample)",
        "One row per candidate click identifier (session_id, identifier_type, identifier_value)",
        "Unpivots existing non-null PostHog session click identifiers (UNION ALL across gclid, fbclid, and click_id_from_url) into (session_id, identifier_type, identifier_value); filters out sessions without click identifiers; does not apply matching or priority ordering (ranking is deferred to int_conversion_attribution).",
    ),
    (
        "int_conversion_attribution",
        "Intermediate (Implemented / Sample)",
        "One row per TrackNow conversion (conversion_id)",
        "Core deterministic attribution engine (table); joins candidate sessions and applies 4-step hierarchy: 1. Exact click identifier match, 2. Temporal eligibility window (session_date <= conversion_date), 3. Identifier priority (typed gclid/fbclid rank 0 over generic click_id_from_url rank 1), 4. Recency tie-break (latest session_start_at wins); classifies into matched, ambiguous, or unmatched; attaches session attributes.",
    ),
    (
        "int_unmatched_conversions",
        "Intermediate (Implemented / Sample)",
        "One row per non-matched TrackNow conversion (conversion_id)",
        "Diagnostic taxonomy view (ADR 8) projecting non-matched rows from int_conversion_attribution; classifies each into deterministic root-cause reasons (missing_click_id, outside_posthog_sample_window, multiple_candidates, click_id_not_found, unknown); preserves 1:1 row parity for auditable health telemetry.",
    ),
    (
        "int_tracknow_commission_reconciliation",
        "Intermediate (Production Assumption)",
        "One row per (commission_date, firm_id)",
        "Production assumption: Proposed reconciliation logic based on prompt specifications, not validated against live Google Sheets data. Full outer join between TrackNow daily commission aggregates and the authoritative Google Sheet daily commission (stg_commission_daily) on (commission_date, firm_id); computes absolute and percentage deltas; classifies reconciliation status; enforces precedence of the official Google Sheet commission over TrackNow values.",
    ),
    (
        "fct_revenue_attribution",
        "Marts (Implemented / Sample)",
        "One row per valid conversion (conversion_id)",
        "Filters int_conversion_attribution to valid conversions (is_valid_conversion = true; excludes denied orders, retains refunded orders); joins attributed session marketing channels (utm_source, utm_medium, utm_campaign, utm_content); exposes commission_gbp (= referral_bonus_gbp) and match metadata.",
    ),
    (
        "mart_attribution_health",
        "Marts (Implemented / Sample)",
        "One row per (conversion_date, utm_source)",
        "Aggregates across the entire decided conversion population (including denied orders); calculates volume metrics (total_conversions, matched_conversions, unmatched_conversions, ambiguous_conversions), conversion rates (match_rate, unmatched_rate), and exact match counts by identifier type (gclid, fbclid, url_click).",
    ),
    (
        "fct_commission_daily_local",
        "Marts (Sample Proxy)",
        "One row per (conversion_date, firm_id)",
        "Local development proxy mart aggregating valid conversions by date and firm from the sample; computes conversion_count, commission_gbp, and sales_amount_gbp; stands in for the unprovided Google Sheet to enable local testing and visualization.",
    ),
    (
        "analytics_core.f_commission_daily",
        "Marts (Production Assumption)",
        "One row per (commission_date, firm_id)",
        "Production assumption: Target BigQuery reporting mart proposed to satisfy financial reconciliation, not fed by live files in this delivery. Publishes official daily commission figures fed by int_tracknow_commission_reconciliation where the Google Sheet commission has precedence; powers executive dashboards, financial reporting, and QuickBooks invoice reconciliation.",
    ),
)

# The investigation of the reported 18% gap (diagnostic queries, hypotheses,
# root-cause boundary) lives on the Area 2 "Investigation & monitoring" page
# (streamlit/sections/investigation.py), alongside the area's monitoring and
# reconciliation designs.


def _read_narrative_facts(connection) -> dict[str, int | float]:
    """Return the live relation totals the prose cites, in one read.

    Every quantity comes from the same dbt relations the analysis page reads:

    - marts.mart_attribution_health - the full decided population (including
      denied conversions) with match-status counts.
    - marts.fct_revenue_attribution - the revenue-valid population and its
      commission total.
    - intermediate.int_unmatched_conversions - the diagnostic reason taxonomy
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
    return str(value) if value is not None else "-"


def _limitation_notes(connection) -> list[tuple[str, str]]:
    """Return the limitation items, with warehouse-specific figures read live.

    Each limitation maps to a real boundary of this delivery; none is invented
    to look thorough. The first two carry numbers/dates that describe the
    *warehouse being evaluated*, so they are read from the same consumer
    relations the rest of the page reads (never from fixed delivered-sample
    totals, which would contradict a valid PFM_DUCKDB_PATH override):

    - marts.mart_attribution_health - the full decided conversion population
      (every TrackNow conversion the attribution engine decided, including
      denied rows) and its conversion-date span.
    - marts.fct_revenue_attribution - the revenue-valid conversion count (the
      subset the app's overview cites as "valid conversions").
    - intermediate.int_unmatched_conversions - the number of conversions the
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
            "The proposed pipeline across `stg_commission_daily`, `int_tracknow_commission_reconciliation`, "
            "and `analytics_core.f_commission_daily` is an unvalidated production assumption. "
            "The schema, join keys, logic, and data quality tests were designed from the prompt specification. "
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
        "Reference documentation for attribution logic across three areas: "
        "the target production design, deterministic rules used for this "
        "sample, and known data limitations. The investigation of the reported "
        "18% production gap is on the Area 2 Investigation & monitoring page. "
        "All transformation rules run inside dbt; this UI reports the resulting marts directly."
    )


def _rationale_section() -> None:
    st.subheader("Attribution rationale and data findings")
    st.write(
        "Before defining transformation models or matching rules, we evaluated the raw datasets to determine what identity linkages the data can genuinely support."
    )
    st.markdown(
        "* **Observations in the data**: PostHog records browsing sessions with session identifiers, distinct IDs, start timestamps, landing URLs, ad identifiers (`gclid`, `fbclid`), and marketing parameters. TrackNow records affiliate checkouts with conversion IDs, conversion dates, order values, commission amounts, outbound click IDs, affiliate session IDs, and user IDs.\n"
        "* **Viable matching keys**: The primary candidate keys connecting conversions to sessions are the click identifiers: TrackNow `click_id` compared against PostHog ad click IDs (`gclid`, `fbclid`) or URL parameters (`click_id_from_url`).\n"
        "* **Relationships that cannot be assumed**: TrackNow `affiliate_session_id` cannot be treated as equal to PostHog `session_id` because each platform generates its own session tokens without a shared contract. Similarly, `tracknow_user_id` cannot be equated to PostHog `distinct_id`. Furthermore, TrackNow supplies only a conversion date without an order timestamp, so intraday session sequence cannot be guessed.\n"
        "* **Why exact matching was chosen**: Exact identifier matching is the only deterministic, auditable standard supported by the data. Approximating keys or fabricating joins would risk misattributing revenue to unrelated marketing channels. When an identifier does not match exactly, leaving the record unmatched is the analytically sound decision.\n"
        "* **Evolution to the dbt architecture**: These findings directly structured our dbt design. Staging models clean and type cast raw records while preserving all rows. Intermediate models isolate candidate keys, apply deterministic exact matching hierarchy with recency tie breaks, and classify unmatched records into an auditable diagnostic taxonomy. Marts publish reconciled reporting for revenue attribution and tracking health."
    )


def _decision_lifecycle_section() -> None:
    st.subheader("Decision flow and attribution lifecycle")
    st.write(
        "To evaluate attribution deterministically, the pipeline executes a complete eight stage decision sequence:"
    )
    st.markdown(
        "1. **Source data**: Raw tables (`raw.posthog_sessions` and `raw.tracknow_checkouts`) ingest session events and affiliate purchases, cleaned into staging models with whitespace trimmed and types normalized without dropping rows.\n"
        "2. **Candidate identifiers**: Intermediate models unpivot candidate session identifiers (`gclid`, `fbclid`, `click_id_from_url`) and extract conversion click parameters (`click_id`, `affiliate_session_id`, `tracknow_user_id`).\n"
        "3. **Exact match**: The attribution engine joins candidates strictly where TrackNow `click_id` equals a PostHog click identifier value.\n"
        "4. **Temporal eligibility**: Matches are filtered to sessions dated on or before the conversion date (`session_date <= conversion_date`), preventing future sessions from claiming historical orders.\n"
        "5. **Priority and tie break**: When multiple eligible sessions match, typed ad identifiers (`gclid`/`fbclid`) take priority over generic URL parameters. Ties are resolved by selecting the latest session start timestamp.\n"
        "6. **Matched, ambiguous, or unmatched**: Each conversion resolves to exactly one deterministic state: `matched` (single winning session), `ambiguous` (unresolvable tie), or `unmatched` (no eligible session, projected into an auditable diagnostic view).\n"
        "7. **Marts**: Downstream marts publish consumption-ready reporting: `fct_revenue_attribution` for attributed marketing channel revenue and `mart_attribution_health` for overall tracking quality telemetry.\n"
        "8. **Monitoring and reconciliation**: Daily commission figures and tracking discrepancies reconcile against finance sources (implemented locally via proxy mart, designed for production via Google Sheets reconciliation and QuickBooks invoice auditing)."
    )


def _production_design_section() -> None:
    st.subheader("Production attribution design")
    st.write(
        "The core cross-system attribution challenge is namespace separation. "
        "PostHog tracks user browsing sessions using `distinct_id` and `session_id`. "
        "TrackNow manages affiliate conversions in a distinct platform, returning an outbound `click_id` upon checkout. "
        "Because neither system natively recognizes the other's internal tokens, reliable attribution cannot rely on guesswork. "
        "Production requires an explicit, persistent first-party identifier that traverses both environments from initial ad click to final purchase."
    )
    st.write(
        "The target architecture establishes a clean, end-to-end attribution loop:"
    )
    st.code(PRODUCTION_IDENTITY_FLOW, language=None)
    st.write("Flow summary:")
    st.markdown(
        "* **Capture ad-click identifier**: On the landing page, capture inbound ad parameters (`gclid` or `fbclid`).\n"
        "* **Associate with PostHog identity**: Attach the captured ad identifier to the active PostHog `session_id` and user `distinct_id`.\n"
        "* **Persist attribution key**: Store a persistent `attribution_click_id` in a first-party bridge table that survives session restarts.\n"
        "* **Pass to TrackNow**: Forward this `attribution_click_id` as the TrackNow `click_id` query parameter on outbound affiliate links.\n"
        "* **TrackNow records conversion**: When a purchase completes, TrackNow returns that exact `click_id` in the conversion record.\n"
        "* **Resolve the bridge**: The conversion `click_id` looks up the bridge table and deterministically resolves the original PostHog session and user."
    )
    st.write("Identifier roles across the systems:")
    for identifier, role in PRODUCTION_IDENTIFIER_ROLES:
        st.markdown(f"* **{identifier}**: {role}")
    st.write(
        "This architecture establishes two key constraints. First, `gclid` "
        "and `fbclid` captured on landing must persist alongside the PostHog "
        "`distinct_id` and session, then forward onto the affiliate outbound "
        "click so `attribution_click_id` closes the loop upon conversion. "
        "Second, `affiliate_session_id` is one of the keys to attribution in "
        "the TrackNow contract, without assuming that it equals "
        "`PostHog.session_id`. Its exact relationship must be explicitly "
        "documented by the integration team rather than assumed in SQL. "
        "Finally, `utm_content` is preserved for ad-level creative reporting "
        "(exposed as `ad_id` in `marts.fct_revenue_attribution`), never as a join key between tables."
    )
    st.write(
        "Production investigations and root cause diagnostics for the reported 18% gap are detailed on the Investigation & monitoring page."
    )
    st.markdown("##### Edge cases and data-model handling")
    st.write(
        "The following structural boundaries apply regardless of which "
        "production mechanism drives the reported gap. Each entry outlines an "
        "edge case, when it occurs, and how the data model handles it."
    )
    for case, when, handling in EDGE_CASES:
        st.markdown(f"* **{case}.** When: {when}. Handling: {handling}")


def _method_section() -> None:
    st.subheader("Sample implementation")
    st.write(
        "The local pipeline determines one deterministic outcome per "
        "conversion using four rules in `int_conversion_attribution`. These "
        "rules govern how orders match to PostHog sessions in this sample:"
    )
    for title, body in METHOD_RULES:
        st.markdown(f"**{title}**: {body}")
    st.markdown("**Outcome**: every conversion gets one of three states:")
    for state, meaning in DECISION_STATES:
        st.markdown(f"* **`{state}`**: {meaning}")


def _dbt_architecture_section() -> None:
    st.subheader("dbt transformation architecture")
    st.write(
        "With the decision logic and lifecycle defined above, the dbt transformation "
        "catalog serves as the technical reference for model implementation. Models are "
        "organized across Staging (source cleaning and interface stability), "
        "Intermediate (candidate preparation, deterministic attribution, "
        "unmatched diagnostics, and commission reconciliation), and Marts "
        "(consumer-facing reporting, financial aggregates, and operational telemetry)."
    )
    st.markdown(
        "**Implementation status labels:**\n\n"
        "* **Implemented / Sample**: fully implemented in dbt and executed against the delivered sample data.\n"
        "* **Sample Proxy**: local proxy mart created from sample data to emulate an external production source that was not provided.\n"
        "* **Production Assumption**: target production architecture, schema, join keys, and data quality tests designed from prompt requirements, not validated against live production files."
    )
    st.table(
        {
            "Model": [row[0] for row in DBT_ARCHITECTURE_TABLE],
            "Layer": [row[1] for row in DBT_ARCHITECTURE_TABLE],
            "Grain": [row[2] for row in DBT_ARCHITECTURE_TABLE],
            "Key Transformations": [row[3] for row in DBT_ARCHITECTURE_TABLE],
        }
    )


def _results_section(facts: dict[str, int | float]) -> None:
    st.subheader("Interpreting the observed results")
    st.write("Summary interpretations derived from the decided marts:")

    # The interpretation prose is built from the same live relation totals the
    # analysis page charts, so the text can never drift from the data.
    for title, body in _build_result_interpretations(facts):
        st.markdown(f"**{title}.** {body}")

    st.caption(
        f"Health mart totals over the decided population: "
        f"{int(facts['decided']):,} conversions - {int(facts['matched']):,} "
        f"matched, {int(facts['unmatched']):,} unmatched, "
        f"{int(facts['ambiguous']):,} ambiguous."
    )


def _limitations_section(connection) -> None:
    st.subheader("Limitations")
    st.write("What this delivery does not claim:")
    for title, body in _limitation_notes(connection):
        st.markdown(f"* **{title}**: {body}")


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
        "* **Raise click-id coverage at the source**: "
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
        "* **Propagate identifiers consistently**: "
        "Whatever id is captured at click time must survive redirects and be "
        "written into the session record, not only into the URL."
        + propagate_tail
    )

    st.markdown(
        "* **Persist identifiers between session and conversion**: "
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
        "* **Widen and monitor the PostHog window**: "
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

    _rationale_section()
    _decision_lifecycle_section()
    _production_design_section()
    _method_section()
    _dbt_architecture_section()
    _results_section(facts)
    _limitations_section(connection)
    _recommendations_section(facts)
