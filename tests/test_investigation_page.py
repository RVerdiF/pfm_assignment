"""Headless AppTest render of the Area 2 "Investigation & monitoring" page.

Drives the investigation section through AppTest.from_file. The section is
pure prose by design — it reads no warehouse relation and renders no chart —
so the checks assert the card's Area-2 navigation/content contract: the page
exists in the Area 2 navigation group, carries the six required elements
(reported 18% gap, investigation queries, hypotheses/fixes on this page;
QuickBooks reconciliation design, five monitoring checks, alerting/on-call on
the area's companion pages), and keeps the design-only boundary.
"""

from __future__ import annotations

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_investigation_driver.py"
APP = ROOT / "streamlit" / "app.py"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _body(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.caption)


def _code(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.code)


def test_investigation_page_renders_the_reported_gap() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    headers = {h.value for h in at.subheader}
    # Element 1: the reported 18% gap, framed as the assignment premise.
    assert "The reported 18% gap" in headers
    assert "18% of TrackNow conversions in the last 30 days" in body
    assert "assignment premise" in body
    assert "never " in body and "re-derived from the sample" in body


def test_investigation_page_renders_the_six_diagnostic_queries() -> None:
    at = _render()
    body = _body(at)
    code = _code(at)
    # Element 2: the six diagnostic queries, each with its SQL sketch.
    for phrase in [
        "Query 1 — Daily baseline of the gap",
        "Query 2 — Identifier coverage",
        "Query 3 — Gap by channel",
        "Query 4 — Gap by TrackNow-side dimensions",
        "Query 5 — Conversion lag (cross-session loss)",
        "Query 6 — Attribution bridge propagation audit",
    ]:
        assert phrase in body
    # The sketches really are SQL over the documented production contract.
    assert "unmatched_rate" in code
    assert "tracknow.conversions" in code
    assert "posthog.sessions" in code


def test_investigation_query_5_respects_the_documented_tracknow_grain() -> None:
    """Query 5 must not invent a TrackNow conversion timestamp.

    The documented TrackNow contract exposes only date-grain created_date
    (ingestion/ingestion.md, staging.yml: conversion_date) — there is no
    created_at or any conversion timestamp at raw level. The page promises
    that no column is invented, so the executable part of Query 5 must run
    at the documented date grain, and an hour-level lag may appear only as
    an explicitly hypothetical future-contract field (t.conversion_at).
    """
    from sections.investigation import INVESTIGATION_QUERIES

    title, purpose, sketch = next(
        (q for q in INVESTIGATION_QUERIES if q[0].startswith("Query 5"))
    )
    lowered = sketch.lower()
    prose = purpose.lower()

    # No undocumented TrackNow timestamp column anywhere in the sketch.
    assert "created_at" not in lowered
    assert "conversion_at" not in lowered.replace("t.conversion_at", "")

    # The executable part runs at the documented date grain.
    assert "t.created_date" in lowered
    assert "session_lag_days" in lowered

    # Hour-level lag exists only as an explicitly hypothetical
    # future-contract field, with its cannot-run boundary stated.
    assert "hypothetical field: t.conversion_at" in lowered
    assert "cannot run against the supplied contract" in lowered
    assert "future-production-contract extension" in prose

    # The lag is measured against the live PostHog session through the
    # bridge (same live-session semantics as Queries 1-4), not against an
    # undocumented bridge timestamp column.
    assert "date_diff(ph.session_start_at" not in lowered
    assert "cast(t.created_date as timestamp)" not in lowered
    assert "bridge.session_start_at" not in lowered
    assert "attribution_generated" not in lowered
    assert "left join posthog.sessions ph" in lowered

    # BigQuery date/timestamp function choice and end-start direction:
    # the executable day-grain lag is DATE_DIFF over DATE values with the
    # conversion date as the end and the session start as the start (a
    # conversion after its session is positive); the hypothetical
    # hour-grain lag is TIMESTAMP_DIFF over timestamps with the same
    # direction. Timestamps must never be passed to date_diff.
    day_diffs = re.findall(
        r"date_diff\(([^,()]+(?:\([^)]*\))?)\s*,"
        r"\s*([^,()]+(?:\([^)]*\))?)\s*,\s*day\s*\)",
        lowered,
    )
    assert day_diffs == [
        ("t.created_date", "date(ph.session_start_at)")
    ], day_diffs
    hour_diffs = re.findall(
        r"timestamp_diff\(([^,]+),\s*([^,]+),\s*hour\s*\)", lowered
    )
    assert hour_diffs == [("t.conversion_at", "ph.session_start_at")], (
        hour_diffs
    )
    assert "date_diff(" in lowered  # executable part stays at date grain
    assert "date_diff(t.conversion_at" not in lowered  # no DATE/TIMESTAMP mix


def test_investigation_page_renders_hypotheses_with_tests_and_fixes() -> None:
    at = _render()
    body = _body(at)
    # Element 3: six hypotheses, each with a test and a fix.
    for phrase in [
        "Hypothesis 1 — Identifier lost before the bridge",
        "Hypothesis 2 — Cross-session conversion",
        "Hypothesis 3 — Cross-device / cookie reset / incognito",
        "Hypothesis 4 — Redirect stripping / affiliate integration issue",
        "Hypothesis 5 — Consent / ad blocker / PostHog collection gap",
        "Hypothesis 6 — Ingestion latency / freshness",
        "**Test:**",
        "**Fix:**",
    ]:
        assert phrase in body
    # The root-cause boundary is stated.
    assert (
        "The provided anonymised sample does not contain a deterministic "
        "cross-system identity overlap" in body
    )


def test_investigation_page_maps_the_six_area2_elements() -> None:
    """The area map points to the six required elements without duplication."""
    at = _render()
    body = _body(at)
    for element in [
        "Reported 18% gap",
        "Investigation queries",
        "Hypotheses and fixes",
        "QuickBooks reconciliation design",
        "Five monitoring checks",
        "Alerting / on-call",
    ]:
        assert element in body


def test_investigation_page_is_registered_first_in_area2_navigation() -> None:
    """Navigation contract: the page exists inside the Area 2 group."""
    app_source = APP.read_text()
    assert "investigation" in app_source
    nav_block = app_source[
        app_source.index("pages = {") : app_source.index(
            "navigation = st.navigation"
        )
    ]
    area2 = nav_block[nav_block.index("Area 2") :]
    assert "Investigation & monitoring" in area2
    assert 'url_path="investigation-monitoring"' in area2
    # It is the first page of the group (before the design pages).
    assert area2.index("investigation-monitoring") < area2.index(
        "monitoring-design"
    )
    assert area2.index("investigation-monitoring") < area2.index(
        "quickbooks-reconciliation"
    )


def test_investigation_page_reads_no_warehouse_relation() -> None:
    at = _render()
    assert not at.exception, at.exception
    # Pure prose: no metrics, no charts.
    assert not at.metric
    assert not at.get("vega_lite_chart")
    source = (ROOT / "streamlit" / "sections" / "investigation.py").read_text()
    assert "execute(" not in source
    assert "read_relation(" not in source
    assert "require_connection(" not in source
    assert "connection_for_app(" not in source


def test_investigation_page_never_presents_investigation_as_executed() -> None:
    at = _render()
    combined = _body(at) + " " + _captions(at)
    # The premise/boundary framing: production tables were not delivered.
    assert "not delivered" in combined
    assert "cannot confirm or refute" in combined
    # Design-only boundary naming the repository boundary explicitly.
    assert "not implemented in this repository" in combined
