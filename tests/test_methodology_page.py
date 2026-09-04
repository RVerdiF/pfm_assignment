"""Headless AppTest render of the methodology page against a real warehouse.

Drives the methodology section through AppTest.from_file. The warehouse is the
real built dbt warehouse of this worktree, exposed through the standard
PFM_DUCKDB_PATH override.

These checks verify the Card-3 acceptance criteria on this page: the attribution
method is explained (exact click-id matching, temporal window, identifier
priority, recency), results carry textual interpretation tied to real mart
numbers, and limitations/recommendations are explicit.
"""
from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_methodology_driver.py"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def test_methodology_page_renders_with_real_warehouse() -> None:
    at = _render()
    assert not at.exception, at.exception
    headers = {h.value for h in at.subheader}
    assert "Attribution method" in headers
    assert "Interpreting the observed results" in headers
    assert "Limitations" in headers
    assert "Recommendations" in headers


def test_methodology_page_explains_the_method() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = " ".join(str(el.value) for el in at.markdown)
    for phrase in [
        "Exact match only",
        "Temporal window",
        "Identifier priority",
        "Recency tie-break",
        "`matched`",
        "`ambiguous`",
        "`unmatched`",
    ]:
        assert phrase in body


def test_methodology_page_has_textual_results_interpretation() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = " ".join(str(el.value) for el in at.markdown)
    # The real sample: every conversion is unattributed and the reasons are
    # stated in prose, matching the diagnosis panel on the analysis page.
    assert "The whole valid sample is unattributed" in body
    assert "no TrackNow click id equals a PostHog identifier" in body
    assert "Reporting revenue by channel is not possible yet" in body


def test_methodology_page_lists_limitations_and_recommendations() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = " ".join(str(el.value) for el in at.markdown)
    for phrase in [
        "Small sample",
        "Limited PostHog window",
        "TrackNow gives a conversion date, not a timestamp",
        "No authoritative daily commission source",
        "No fuzzy rules or undocumented bridges",
        "Raise click-id coverage at the source",
        "Propagate identifiers consistently",
        "Persist identifiers between session and conversion",
        "Widen and monitor the PostHog window",
    ]:
        assert phrase in body


def test_methodology_health_caption_reconciles_to_real_marts() -> None:
    """The prose cites live health-mart totals, so text cannot drift."""
    at = _render()
    assert not at.exception, at.exception
    captions = " ".join(str(c.value) for c in at.caption)
    # Real built warehouse totals for this worktree.
    assert "100 conversions" in captions
    assert "0 matched" in captions
    assert "100 unmatched" in captions
