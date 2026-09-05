"""Headless AppTest render of the analysis page against a real warehouse.

Drives the analysis section through AppTest.from_file (a real Streamlit script
that imports the section module, so ``st`` globals resolve exactly as they do
in the running app). The warehouse is the real built dbt warehouse of this
worktree, exposed through the standard PFM_DUCKDB_PATH override.

These are functional render checks — they verify the acceptance criterion that
the numbers shown come from the dbt marts and reconcile to them.
"""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_analysis_driver.py"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _chart_specs(at: AppTest) -> list[dict]:
    """Return the Vega-Lite spec dicts of every chart rendered on the page."""
    return [json.loads(chart.proto.spec) for chart in at.get("vega_lite_chart")]


def test_analysis_page_renders_with_real_warehouse() -> None:
    at = _render()
    assert not at.exception, at.exception
    headers = {h.value for h in at.subheader}
    assert "Attribution overview" in headers
    assert "What the provided sample can diagnose" in headers
    assert "Marketing attribution" in headers
    assert "Revenue and commission" in headers


def test_analysis_page_diagnosis_is_sample_scoped() -> None:
    """Card 1 reframe guard: the diagnosis panel describes only the sample.

    The page must not claim the sample's identifiers prove the production
    root cause, and must not resurrect the old 'better join'/'honest result'
    narrative. The reported 18% production gap belongs to the Overview and
    Investigation & monitoring pages as an assignment premise.
    """
    at = _render()
    assert not at.exception, at.exception
    body = " ".join(str(el.value) for el in at.markdown)
    captions = " ".join(str(c.value) for c in at.caption)
    # Sample-scoped framing is present.
    assert "diagnoses the anonymised sample" in captions
    assert "property of this sample" in body
    # The old universal-claim narrative is gone.
    for banned in [
        "the honest result, not a missing step",
        "not places where a better join would help",
    ]:
        assert banned not in body
        assert banned not in captions


def test_analysis_page_kpis_reconcile_to_marts() -> None:
    at = _render()
    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    # Ground truth from the freshly built dbt marts of this worktree.
    assert metrics["Valid conversions"] == "92"
    assert metrics["Commission (GBP)"] == "£1,001.70"
    assert metrics["Matched"] == "0"
    assert metrics["Unmatched"] == "92"
    assert metrics["Ambiguous"] == "0"
    assert metrics["Match rate"] == "0.0%"
    assert metrics["Unmatched rate"] == "100.0%"
    # Audit strip reconciles the decided population (100 = 92 valid + 8 denied).
    assert metrics["Decided conversions (all)"] == "100"
    assert metrics["Denied (excluded from revenue)"] == "8"


def test_analysis_page_diagnosis_shows_reason_breakdown() -> None:
    at = _render()
    assert not at.exception, at.exception
    captions = " ".join(str(c.value) for c in at.caption)
    assert "Total non-matched conversions: 100" in captions
    # The reason taxonomy is presented as a chart + dataframe; captions carry
    # the reconciliation note. The no-matched-method explanation is rendered
    # as markdown because it is an empty-state message.
    body_text = " ".join(str(el.value) for el in at.markdown)
    assert "No conversions were matched in this sample" in body_text


def test_analysis_page_shows_both_source_bars() -> None:
    """Marketing attribution renders bars for conversions AND commission."""
    at = _render()
    assert not at.exception, at.exception
    specs = _chart_specs(at)
    source_bars = [
        spec
        for spec in specs
        if spec.get("encoding", {}).get("y", {}).get("field") == "utm_source"
    ]
    assert len(source_bars) == 2, "expected conversions + commission source bars"
    x_fields = {spec["encoding"]["x"]["field"] for spec in source_bars}
    assert x_fields == {"conversions", "commission_gbp"}


def test_analysis_page_has_no_reimplemented_join() -> None:
    """The consumer must never read raw/staging relations directly."""
    source = (ROOT / "streamlit" / "sections" / "analysis.py").read_text()
    assert "raw." not in source
    assert "staging." not in source
    # ADR 8: the only intermediate read is the pre-computed unmatched_reason
    # diagnostic view. Decided totals come from marts.mart_attribution_health.
    assert "intermediate.int_conversion_attribution" not in source
    assert "intermediate.int_unmatched_conversions" in source
