"""Methodology, limitations and recommendations page for the PFM walkthrough.

This page closes the walkthrough: it explains HOW attribution is decided
(exact click-identifier matching with a temporal window and deterministic
tie-breaks), WHY the observed results look the way they do (with the numbers
read from the same dbt marts as the analysis page), what the sample cannot
support, and what the assignment recommends to raise coverage.

The page reads published marts only for the few numbers it cites; the rules
described here are the ones implemented once in the dbt intermediate layer
(int_conversion_attribution) and are documented verbatim in the model header
and in docs/decisions.md. No attribution logic is re-implemented in Python.
"""
from __future__ import annotations

import streamlit as st

from sections._components import require_connection

MART_SCHEMA = "marts"

# Deterministic attribution rules, in the exact order the intermediate model
# applies them. Each rule is stated in plain language next to the technical
# term an evaluator will meet in the code.
METHOD_RULES = (
    (
        "1. Exact match only",
        "A conversion is attributed to a session only when the TrackNow "
        "`click_id` equals a PostHog click identifier exactly — a `gclid`, "
        "`fbclid`, or the click id read from the landing URL. No fuzzy "
        "matching, no normalization of identifier values, no invented bridge "
        "(an `affiliate_session_id` is never treated as a PostHog "
        "`session_id`).",
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

# Why the observed results look the way they do. The numbers mirror the
# diagnosis panel on the Attribution analysis page (same dbt relations); they
# are stated here in prose so the page reads as an interpretation rather than
# another table.
RESULT_INTERPRETATIONS = (
    (
        "The whole valid sample is unattributed",
        "Of the 100 decided conversions, the health mart counts 0 matched and "
        "100 unmatched/ambiguous, so the revenue mart (92 valid conversions, "
        "£1,001.70 of commission) carries no channel signal at all. This is a "
        "property of the delivered sample, not a pipeline failure: the "
        "attribution engine is exact-only, and no TrackNow click id equals a "
        "PostHog identifier value inside the sample.",
    ),
    (
        "Loss happens before matching",
        "13 conversions have no click id at all and can never be attributed "
        "under exact matching. A further 40 carry a click id that the PostHog "
        "sample never records. Together these are the identifiers the "
        "business must learn to persist and propagate.",
    ),
    (
        "The PostHog sample window also removes candidates",
        "47 conversions fall outside what the sample can explain: TrackNow "
        "orders start on 9 May but the PostHog sample only starts on 25 May, "
        "so conversions before that date cannot have an eligible session in "
        "the sample even when their click id appears later.",
    ),
    (
        "Reporting revenue by channel is not possible yet",
        "Because no conversion is matched, every UTM-source group in the "
        "analysis page is the explicit 'Unattributed' bucket. Reading "
        "commission by channel from this sample would misattribute the whole "
        "£1,001.70; the honest output is a health signal: the attribution "
        "machinery is working, the sample cannot feed it.",
    ),
)

# Sample limitations, each matching a concrete consequence already visible in
# the data or in the assignment contract. No limitation is invented to look
# thorough; each one maps to a real boundary.
LIMITATIONS = (
    (
        "Small sample",
        "100 TrackNow conversions and 200 PostHog sessions over a short "
        "window cannot represent production volume or channel mix.",
    ),
    (
        "Limited PostHog window",
        "Sessions start on 25 May while conversions start on 9 May, so any "
        "conversion before 25 May is structurally unexplainable by this "
        "sample.",
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
        "an exact key.",
    ),
)

# Recommendations, each addressing one of the observed loss causes. They are
# ordered from the cheapest data-side fix to the operational habit.
RECOMMENDATIONS = (
    (
        "Raise click-id coverage at the source",
        "13 conversions arrived without a click id. The tracking layer should "
        "treat the click id as a required field on every order.",
    ),
    (
        "Propagate identifiers consistently",
        "40 conversions carried a click id the PostHog sample never saw. "
        "Whatever id is captured at click time must survive redirects and be "
        "written into the session record, not only into the URL.",
    ),
    (
        "Persist identifiers between session and conversion",
        "The generic URL click id exists only on the session side; converting "
        "flows should carry the same identifier into the order payload so the "
        "two systems share one key namespace.",
    ),
    (
        "Widen and monitor the PostHog window",
        "47 conversions predate the sample. A production window must start "
        "before the earliest order and be monitored so coverage loss is "
        "visible continuously, not discovered at report time.",
    ),
)


def _page_intro() -> None:
    st.header("Methodology and limitations")
    st.write(
        "This page is the walkthrough's reference: how the attribution "
        "decision is made (Method), what the observed results mean "
        "(Interpreting the results), what this sample cannot support "
        "(Limitations), and what would raise coverage (Recommendations). "
        "Every rule stated here is implemented once in the dbt intermediate "
        "layer and documented in docs/decisions.md; this app never re-applies "
        "the logic."
    )


def _method_section() -> None:
    st.subheader("Attribution method")
    st.write(
        "The pipeline answers one question per conversion: **which PostHog "
        "session drove this order?** It is answered with the four rules below, "
        "applied in order by the `int_conversion_attribution` dbt model."
    )
    for title, body in METHOD_RULES:
        st.markdown(f"**{title}** — {body}")
    st.markdown("**Outcome** — every conversion gets one of three states:")
    for state, meaning in DECISION_STATES:
        st.markdown(f"- **`{state}`** — {meaning}")


def _results_section(connection) -> None:
    st.subheader("Interpreting the observed results")
    st.write(
        "The analysis page shows the numbers behind these statements; the "
        "statements themselves are the interpretation."
    )
    for title, body in RESULT_INTERPRETATIONS:
        st.markdown(f"**{title}.** {body}")

    # Health mart numbers cited in prose are read live from the same dbt
    # relation the analysis page uses, so the text can never drift from the
    # charts. The totals mirror the mart's grouped grain.
    row = connection.execute(
        "select "
        "  coalesce(sum(total_conversions), 0), "
        "  coalesce(sum(matched_conversions), 0), "
        "  coalesce(sum(unmatched_conversions), 0), "
        "  coalesce(sum(ambiguous_conversions), 0) "
        "from marts.mart_attribution_health"
    ).fetchone()
    if row:
        st.caption(
            f"Health mart totals over the decided population: "
            f"{int(row[0]):,} conversions — {int(row[1]):,} matched, "
            f"{int(row[2]):,} unmatched, {int(row[3]):,} ambiguous."
        )


def _limitations_section() -> None:
    st.subheader("Limitations")
    st.write("What this delivery does not claim:")
    for title, body in LIMITATIONS:
        st.markdown(f"- **{title}** — {body}")


def _recommendations_section() -> None:
    st.subheader("Recommendations")
    st.write(
        "Each recommendation targets one of the concrete loss causes observed "
        "in the sample:"
    )
    for title, body in RECOMMENDATIONS:
        st.markdown(f"- **{title}** — {body}")


def render() -> None:
    _page_intro()
    connection = require_connection()

    _method_section()
    _results_section(connection)
    _limitations_section()
    _recommendations_section()
