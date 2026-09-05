"""Headless AppTest render of the "Data quality monitoring" design page.

Drives the Area-2 monitoring design section through AppTest.from_file (a real
Streamlit script that imports the section module). Like the other design
pages, this section is pure prose by design — it reads no warehouse relation
and renders no chart — so the checks assert the card's acceptance criteria:
exactly five checks, each with what it validates, a threshold, a P1/P2/P3
severity, an implementation, and an on-call notification; the first-check
rationale; the alerting flow and channels; the alert payload; the monitoring
architecture; and the design-only boundary.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_monitoring_design_driver.py"
APP = ROOT / "streamlit" / "app.py"
DESIGN_DOC = ROOT / "docs" / "commission_monitoring_design.md"
README = ROOT / "README.md"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _body(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.caption)


def test_monitoring_page_renders_with_five_checks() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    # Exactly the five checks from the card, each named.
    for check in [
        "Check 1 — Commission source freshness",
        "Check 2 — Duplicate / invalid TrackNow conversions",
        "Check 3 — Attribution unmatched-rate regression",
        "Check 4 — Commission reconciliation variance",
        "Check 5 — Firm / accounting mapping coverage",
    ]:
        assert check in body
    assert "Check 6" not in body


def test_monitoring_page_check_covers_all_required_fields() -> None:
    at = _render()
    body = _body(at)
    # Each check carries the six required facets.
    required_labels = [
        "*Validates:*",
        "*Metric:*",
        "*Threshold:*",
        "*Severity:*",
        "*Implementation:*",
        "*On-call:*",
    ]
    label_counts = [body.count(label) for label in required_labels]
    assert all(count == 5 for count in label_counts), label_counts


def test_monitoring_page_states_thresholds_and_severities() -> None:
    at = _render()
    body = _body(at)
    # Threshold anchors from the card.
    assert "10:00 UTC" in body
    assert "25%" in body
    assert "5 percentage points" in body
    assert "£500" in body
    # The reported 18% is treated as an observation, never a hardcoded SLA.
    assert "not a hardcoded SLA" in body
    # All three severities are used and routed.
    assert "P1" in body and "P2" in body and "P3" in body


def test_monitoring_page_names_the_first_check_with_rationale() -> None:
    at = _render()
    body = _body(at)
    assert "Build Check 1 (Commission source freshness) first" in body
    # The grain check follows immediately, with the card's reason.
    assert "uniqueness/grain checks (Check 2)" in body
    assert "duplicate financial rows" in body
    assert "silently overstate revenue" in body


def test_monitoring_page_covers_alerting_and_payload() -> None:
    at = _render()
    body = _body(at)
    code_blocks = " ".join(str(c.value) for c in at.code)
    # The alerting flow stages.
    for stage in [
        "dbt build + monitoring queries",
        "monitoring table",
        "threshold evaluation",
        "notification",
    ]:
        assert stage in code_blocks
    # The routing sentence required by the card.
    assert (
        "route P1 to the on-call paging system and P2/P3 to a dedicated "
        "data-alerts Slack channel" in body
    )
    assert "Finance copied on reconciliation-specific issues" in body
    # Every alert payload field from the card.
    for field in [
        "check_name",
        "severity",
        "detected_at",
        "affected_date/period",
        "firm_id",
        "observed_value",
        "threshold",
        "query/model",
        "run_id",
        "suggested first action",
    ]:
        assert field in code_blocks


def test_monitoring_page_covers_architecture() -> None:
    at = _render()
    code_blocks = " ".join(str(c.value) for c in at.code)
    for stage in [
        "Airbyte / source loads",
        "BigQuery raw",
        "dbt tests + monitoring models",
        "monitoring mart",
        "scheduled evaluation",
        "Slack / paging",
    ]:
        assert stage in code_blocks


def test_monitoring_page_reads_no_warehouse_relation() -> None:
    at = _render()
    assert not at.exception, at.exception
    # Pure prose: no metrics, no charts.
    assert not at.metric
    assert not at.get("vega_lite_chart")
    source = (
        ROOT / "streamlit" / "sections" / "monitoring_design.py"
    ).read_text()
    assert "execute(" not in source
    assert "read_relation(" not in source
    assert "require_connection(" not in source
    assert "connection_for_app(" not in source


def test_monitoring_page_never_presents_design_as_implemented() -> None:
    at = _render()
    assert not at.exception, at.exception
    combined = _body(at) + " " + _captions(at)
    assert "Nothing in this design is implemented" in combined
    assert "no Airbyte connection" in combined
    assert "no BigQuery deployment" in combined
    assert "no Slack/paging integration" in combined


def test_monitoring_page_is_registered_in_area2_navigation() -> None:
    app_source = APP.read_text()
    assert "monitoring_design" in app_source
    nav_block = app_source[
        app_source.index("pages = {") : app_source.index(
            "navigation = st.navigation"
        )
    ]
    area2 = nav_block[nav_block.index("Area 2") :]
    assert "Data quality monitoring" in area2
    assert 'url_path="monitoring-design"' in area2


def test_monitoring_design_doc_exists_with_card_elements_and_readme_link() -> None:
    assert DESIGN_DOC.is_file()
    doc = DESIGN_DOC.read_text()
    for element in [
        "### Check 1 — Commission source freshness",
        "### Check 2 — Duplicate / invalid TrackNow conversions",
        "### Check 3 — Attribution unmatched-rate regression",
        "### Check 4 — Commission reconciliation variance",
        "### Check 5 — Firm / accounting mapping coverage",
        "P1",
        "P2",
        "P3",
        "trailing 7-day baseline",
        "dim_firm_accounting_mapping",
        "mart_attribution_health",
        "suggested first action",
        "Immediately after freshness",
    ]:
        assert element in doc
    readme = README.read_text()
    assert "docs/commission_monitoring_design.md" in readme
