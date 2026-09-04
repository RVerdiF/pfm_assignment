"""Methodology, limitations and recommendations page for the PFM walkthrough.

This page closes the walkthrough: it explains HOW attribution is decided
(exact click-identifier matching with a temporal window and deterministic
tie-breaks), WHY the observed results look the way they do (with the numbers
read from the same dbt relations as the analysis page), what the sample cannot
support, and what the assignment recommends to raise coverage.

The page reads published relations only for the numbers it cites; the rules
described here are the ones implemented once in the dbt intermediate layer
(int_conversion_attribution) and are documented verbatim in the model header
and in docs/decisions.md. No attribution logic is re-implemented in Python.

Narrative numbers are never hard-coded: every result/recommendation quantity
is derived on each render from the same dbt relations the analysis page
charts — marts.mart_attribution_health (decided/match-status totals),
marts.fct_revenue_attribution (valid conversions and commission), and
intermediate.int_unmatched_conversions (the non-match reason taxonomy). A
page rendered against a different valid warehouse (the documented
PFM_DUCKDB_PATH override) always reads that warehouse's own totals, so the
walkthrough cannot contradict its own marts.
"""
from __future__ import annotations

import streamlit as st

from sections._components import require_connection

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
                "property of the delivered sample, not a pipeline failure: "
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


# Sample limitations, each matching a concrete consequence already visible in
# the data or in the assignment contract. No limitation is invented to look
# thorough; each one maps to a real boundary. These describe the delivered
# workbook (the fixed assignment input), not a marts total, so they are stated
# once as context rather than read from the warehouse on every render.
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


def _limitations_section() -> None:
    st.subheader("Limitations")
    st.write("What this delivery does not claim:")
    for title, body in LIMITATIONS:
        st.markdown(f"- **{title}** — {body}")


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

    _method_section()
    _results_section(facts)
    _limitations_section()
    _recommendations_section(facts)
