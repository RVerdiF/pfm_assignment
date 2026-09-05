"""Headless AppTest render of the overview page against a real warehouse.

Drives the overview section through AppTest.from_file (a real Streamlit script
that imports the section module). The warehouse is the real built dbt warehouse
of this worktree, exposed through the standard PFM_DUCKDB_PATH override.

These checks verify the Card-3 acceptance criteria that live on this page:
an evaluator understands the problem and the real architecture without opening
the code — the page explains the context in prose, renders an architecture
diagram whose labels match the real pipeline stages, and connects read-only to
the published consumer relations (marts + the ADR-8 diagnostic view).
"""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_overview_driver.py"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _architecture_diagram_specs(at: AppTest) -> list[str]:
    mermaid = [
        str(el.value)
        for el in at.markdown
        if "flowchart" in str(el.value) or "mermaid" in str(el.value)
    ]
    graphviz = [gv.proto.spec for gv in at.get("graphviz_chart")]
    return mermaid + graphviz


def test_overview_page_renders_with_real_warehouse() -> None:
    at = _render()
    assert not at.exception, at.exception
    assert at.title[0].value == "PFM conversion attribution — walkthrough"
    headers = {h.value for h in at.subheader}
    assert "Purpose of this walkthrough" in headers
    assert "Architecture" in headers
    assert "Relations this walkthrough reads" in headers


def test_overview_page_states_the_problem_in_prose() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = " ".join(str(el.value) for el in at.markdown)
    assert "TrackNow records every conversion" in body
    assert "which session drove each conversion" in body


def test_overview_page_separates_reported_gap_from_sample_rate() -> None:
    """Card 1 reframe: two populations, clearly labelled (ADR 11).

    The page must present the assignment's reported production 18% gap and
    the sample's observed deterministic match rate as different populations,
    and must never suggest one recalculates or validates the other.
    """
    at = _render()
    assert not at.exception, at.exception
    headers = {h.value for h in at.subheader}
    assert "The reported production problem" in headers
    assert "What this executable sample demonstrates" in headers
    body = " ".join(str(el.value) for el in at.markdown)
    # The 18% is cited as an assignment premise, not a sample measurement.
    assert "18% of TrackNow conversions in the last 30 days" in body
    assert "input premise" in body
    # The sample side keeps the factual local observation, scoped to the file.
    assert "anonymised, bounded extract" in body
    assert "not a measurement of production" in body


def test_overview_renders_architecture_diagram_with_real_stages() -> None:
    """The diagram must list the stages that actually exist in the repo."""
    at = _render()
    assert not at.exception, at.exception
    specs = _architecture_diagram_specs(at)
    assert specs, "expected an architecture diagram on the overview page"
    joined = " ".join(specs)
    # The DOT payload carries the node labels; assert the real pipeline
    # vocabulary appears so a stale diagram cannot pass silently.
    for stage in [
        "Ingestion (Polars)",
        "DuckDB raw",
        "dbt staging",
        "dbt intermediate",
        "dbt marts",
        "Streamlit",
    ]:
        assert stage in joined
