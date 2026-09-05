"""Narrative-alignment guards for the Card 1 reframe (ADR 11).

The assignment's rework asks the delivery to stop presenting the sample as if
it measured production: the 18% unmatched figure is a reported production
premise, and the local 0% exact-match outcome is a property of the anonymised
sample. These guards pin that boundary statically (source-level checks) and
one render-level check proves the reported-gap callout actually renders.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_DIR = ROOT / "streamlit"

import sys  # noqa: E402

sys.path.insert(0, str(STREAMLIT_DIR))
import warehouse_bootstrap as wb  # noqa: E402

# Banned universal-rule phrasings. dbt comments and descriptions must not
# claim the sample's exact-click-id rule is the production architecture, and
# must not present affiliate_session_id as irrelevant to attribution.
_DBT_BANNED = [
    "affiliate_session_id is irrelevant",
    "should be ignored in production",
    "never considered",
    "never related to the PostHog flow",
    "is never a valid attribution key",
]

# The pages must never hardcode the production metric or claim the sample
# restates production.
_STREAMLIT_BANNED = [
    "Production unmatched rate = 100%",
    "production unmatched rate is 100%",
    "the sample proves the production",
    "not places where a better join would help",
    "the honest result, not a missing step",
]


def _read(*relative: str) -> str:
    return (ROOT.joinpath(*relative)).read_text()


def test_no_page_hardcodes_the_production_metric() -> None:
    """No Streamlit source hardcodes '100%' as a production unmatched rate."""
    for name in ["overview.py", "analysis.py", "methodology.py"]:
        source = _read("streamlit", "sections", name)
        for banned in _STREAMLIT_BANNED:
            assert banned not in source, f"{name}: found banned phrase {banned!r}"


def test_pages_cite_the_reported_production_gap_as_premise() -> None:
    """The 18% figure appears only as the reported production premise."""
    overview = _read("streamlit", "sections", "overview.py")
    methodology = _read("streamlit", "sections", "methodology.py")
    assert "18%" in overview
    assert "Reported production issue" in overview
    assert "Reported production gap" in overview
    assert "never re-derived from the sample" in overview
    assert "18%" in methodology
    assert "assignment premise" in methodology
    # The 18% must not be derived from any warehouse relation on the pages.
    assert "unmatched_rate * 18" not in overview
    assert "0.18" not in overview


def test_dbt_documentation_does_not_dismiss_affiliate_session_id() -> None:
    """dbt comments keep affiliate_session_id inside the production contract.

    The sample cannot use it as a join key, and the docs must say exactly
    that (a sample-scope constraint), never that the field is irrelevant to
    attribution.
    """
    sql = _read(
        "dbt", "models", "intermediate", "attribution",
        "int_conversion_attribution.sql",
    )
    schema_yml = _read(
        "dbt", "models", "intermediate", "attribution", "schema.yml"
    )
    decisions = _read("docs", "decisions.md")
    for source in (sql, schema_yml, decisions):
        for banned in _DBT_BANNED:
            assert banned not in source
    # The sample-constraint framing is present where the exact rule lives.
    assert "SAMPLE IMPLEMENTATION CONSTRAINT" in sql
    assert "no documented cross-system bridge is available in the delivered data" in sql
    assert "production" in sql.lower()


def test_no_fuzzy_bridge_is_added_to_the_sample_models() -> None:
    """The exact-match contract is unchanged: only click_id equality joins."""
    sql = _read(
        "dbt", "models", "intermediate", "attribution",
        "int_conversion_attribution.sql",
    )
    # The only join on identifiers remains exact click_id = identifier_value;
    # no similarity/normalized/fuzzy constructs may appear.
    lowered = sql.lower()
    for banned in ["levenshtein", "jaro", "soundex", "lower(", "translate("]:
        assert banned not in lowered, f"found fuzzy construct {banned!r}"
    assert "on cv.click_id = cs.identifier_value" in sql


def test_reported_gap_callout_renders_with_sample_rate_from_marts() -> None:
    """The overview callout shows the reported 18% next to the live rate.

    The sample-side number is read from marts.mart_attribution_health on
    render, so it reconciles with the warehouse (0% for the delivered
    sample); the 18% side is the assignment premise, never recomputed.
    """
    con = duckdb.connect(str(ROOT / "warehouse" / "pfm.duckdb"), read_only=True)
    try:
        decided, matched = con.execute(
            "select coalesce(sum(total_conversions), 0), "
            "coalesce(sum(matched_conversions), 0) "
            "from marts.mart_attribution_health"
        ).fetchone()
    finally:
        con.close()
    decided, matched = int(decided), int(matched)

    at = AppTest.from_file(
        str(ROOT / "tests" / "_overview_driver.py"), default_timeout=60
    )
    at.run()
    assert not at.exception, at.exception
    info_text = " ".join(str(i.value) for i in at.info)
    assert "Reported production gap: **18%**" in info_text
    assert "Observed deterministic match rate in provided anonymised sample" in info_text
    if decided:
        assert f"**{matched / decided:.0%}**" in info_text
    assert (
        "These numbers describe different populations and should not be "
        "compared as if one validates the other" in info_text
    )


def test_investigation_query_4_uses_tracknow_documented_fields() -> None:
    """Query 4 must use TrackNow's documented fields, not invented telemetry.

    The unmatched cohort has no PostHog session by definition, so the query
    that profiles it must use only TrackNow's own documented fields (firm_id,
    trading_platform, first_order) — never device/browser/os/country/consent
    (which TrackNow's staging schema does not carry), and never an identity
    bridge (affiliate_session_id = PostHog.session_id).
    """
    from sections.methodology import INVESTIGATION_QUERIES

    title, purpose, sketch = next(
        (q for q in INVESTIGATION_QUERIES if q[0].startswith("Query 4"))
    )
    lowered = sketch.lower()

    # No invented telemetry columns (TrackNow staging does not carry these).
    # Check for column references (t.os, t.device_type, etc.), not substrings.
    for invented in ["device_type", "browser", "os", "country_code", "consent_state"]:
        assert f"t.{invented}" not in lowered, f"invented column {invented!r} in Query 4"
    # No identity bridge is invented to source the dimensions.
    assert "affiliate_session_id = ph.session_id" not in lowered
    assert "on ph.session_id = t.affiliate_session_id" not in lowered
    # The sketch actually isolates the unmatched cohort.
    assert "ph.session_id is null" in lowered
    # Dimensions come from TrackNow's documented fields.
    for dimension in ["firm_id", "trading_platform", "first_order"]:
        assert dimension in lowered
    # The prose tells the reader where the dimensions come from.
    assert "TrackNow" in purpose
    assert "documented" in purpose.lower() or "firm" in purpose.lower()


def test_monitoring_pages_keep_the_18_percent_as_reported_gap() -> None:
    """The monitoring design treats 18% as the reported gap, not an SLA.

    The card forbids hardcoding the reported production gap as a definitive
    threshold: the check baseline must come from recent history, and the
    thresholds must be configuration.
    """
    monitoring = _read("streamlit", "sections", "monitoring_design.py")
    doc = _read("docs", "commission_monitoring_design.md")
    for source in (monitoring, doc):
        # Normalise markdown emphasis so bold prose does not dodge the guard.
        source = source.replace("**", "")
        # The figure may only be cited as the reported/observed production
        # gap, never as a fixed production truth or an SLA anchor: wherever
        # it appears, the not-an-SLA disclaimer appears in the same source.
        if "18%" in source:
            assert "not a hardcoded SLA" in source
            assert "reported" in source or "observed" in source
        assert "baseline" in source


def test_sample_100_percent_unmatched_stays_a_sample_observation() -> None:
    """The sample's 0% match rate must never be stated as production truth."""
    for name in ["overview.py", "analysis.py", "methodology.py", "monitoring_design.py"]:
        source = _read("streamlit", "sections", name)
        assert "production unmatched rate = 100%" not in source.lower()
        assert "production unmatched rate is 100%" not in source.lower()
        assert "100% unmatched in production" not in source.lower()
    # The overview states the sample outcome as a property of the sample file.
    overview = _read("streamlit", "sections", "overview.py")
    assert "a factual property of this file" in overview


def test_monitoring_pages_are_design_only() -> None:
    """The monitoring/reconciliation pages never claim implemented infrastructure."""
    for name in ["monitoring_design.py", "quickbooks_reconciliation.py", "next_steps.py"]:
        source = _read("streamlit", "sections", name)
        assert "implemented in this repository" in source
    # And the monitoring design doc states the same boundary up front.
    doc = _read("docs", "commission_monitoring_design.md")
    assert "design only" in doc.lower()
    assert "Nothing in this document is provisioned" in doc


def test_methodology_edge_cases_cover_the_assignment_minimum() -> None:
    """At least four attribution edge cases, each with failure and handling."""
    from sections.methodology import EDGE_CASES

    assert len(EDGE_CASES) >= 4
    for case, when, handling in EDGE_CASES:
        assert case and when and handling
    names = {case for case, _, _ in EDGE_CASES}
    # The card's required set.
    assert "Missing click_id on conversion" in names
    assert "Cross-session conversion" in names
    assert "Cookie reset / cross-device / incognito" in names
    assert "Multiple paid clicks before conversion" in names
    assert "Redirect strips parameters" in names
    assert "Late-arriving data" in names
