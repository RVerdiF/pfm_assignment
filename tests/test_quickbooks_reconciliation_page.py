"""Headless AppTest render of the "QuickBooks reconciliation" page.

Drives the Area-2 design section through AppTest.from_file (a real Streamlit
script that imports the section module). Like the "What I'd do next" page,
this section is pure prose by design — it reads no warehouse relation and
renders no chart — so the checks assert the card's acceptance criteria: the
architecture with Airbyte -> BigQuery raw -> dbt staging -> reconciliation ->
alerts, an explicit grain per layer, the QuickBooks-customer -> firm_id
mapping strategy (never a name join), the reconciliation status taxonomy with
missing sides and variance, per-layer DQ checks, an alert output with fields
and grain, the orchestration ordering, and the boundary that no real
QuickBooks integration is implemented and no invented data is presented.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_quickbooks_reconciliation_driver.py"
APP = ROOT / "streamlit" / "app.py"
DESIGN_DOC = ROOT / "docs" / "quickbooks_reconciliation_design.md"
README = ROOT / "README.md"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _body(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.caption)


def test_quickbooks_page_renders() -> None:
    at = _render()
    assert not at.exception, at.exception
    headers = {h.value for h in at.header}
    assert "QuickBooks reconciliation pipeline" in headers
    subheaders = {h.value for h in at.subheader}
    assert "Architecture" in subheaders
    assert "Firm mapping strategy" in subheaders
    assert "Reconciliation statuses" in subheaders
    assert "Data quality checks" in subheaders


def test_quickbooks_page_is_registered_in_app_navigation() -> None:
    app_source = APP.read_text()
    assert "quickbooks_reconciliation" in app_source
    nav_block = app_source[
        app_source.index("pages = [") : app_source.index(
            "navigation = st.navigation"
        )
    ]
    assert "QuickBooks reconciliation" in nav_block


def test_quickbooks_page_shows_full_architecture_with_grains() -> None:
    at = _render()
    assert not at.exception, at.exception
    # The architecture diagram contains both sides converging on the
    # reconciliation model.
    code_blocks = " ".join(str(c.value) for c in at.code)
    for hop in [
        "QuickBooks Online",
        "Airbyte source",
        "raw_quickbooks.invoices",
        "stg_quickbooks_invoices",
        "fct_commission_daily",
        "int_quickbooks_tracknow_reconciliation",
        "mart_finance_reconciliation_alerts",
        "Slack / PagerDuty / email",
    ]:
        assert hop in code_blocks
    # Layer/grain table covers every layer with an explicit grain (the table
    # element's value is a pandas DataFrame).
    table = at.get("table")[0].value
    assert list(table["Layer"]) == [
        "Airbyte / raw",
        "Mapping",
        "Staging",
        "TrackNow",
        "Intermediate",
        "Mart",
    ]
    grains = list(table["Grain"])
    assert "One row per raw invoice record/version" in grains[0]
    assert "One row per (firm_id, valid_from)" in grains[1]
    assert "One row per current invoice" in grains[2]
    assert "(commission_date, firm_id)" in grains[3]
    assert "(invoice_id, firm_id)" in grains[4]
    assert "active reconciliation failure" in grains[5]


def test_quickbooks_page_maps_customer_to_firm_without_name_join() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    assert "dim_firm_accounting_mapping" in body
    assert "quickbooks_customer_id" in body
    assert "never a join key" in body.replace("``", "").replace("\n", " ")


def test_quickbooks_page_states_full_status_taxonomy_and_tolerance() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    for status in [
        "matched",
        "variance",
        "missing_tracknow",
        "missing_quickbooks",
        "unmapped_firm",
        "currency_mismatch",
    ]:
        assert f"`{status}`" in body
    # Tolerance is presented as an example to validate with Finance.
    assert "£5" in body
    assert "to validate with Finance" in body


def test_quickbooks_page_covers_dq_checks_and_orchestration() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    # DQ check themes per layer.
    for theme in ["freshness", "invoice_id unique", "join coverage"]:
        assert theme in body
    # Orchestration: dbt strictly after the Airbyte sync.
    assert (
        "dbt only after the Airbyte sync completes successfully" in body
    )


def test_quickbooks_page_reads_no_warehouse_relation() -> None:
    at = _render()
    assert not at.exception, at.exception
    # Pure prose: no metrics, no charts.
    assert not at.metric
    assert not at.get("vega_lite_chart")
    source = (
        ROOT / "streamlit" / "sections" / "quickbooks_reconciliation.py"
    ).read_text()
    assert "execute(" not in source
    assert "read_relation(" not in source
    assert "require_connection(" not in source
    assert "connection_for_app(" not in source


def test_quickbooks_page_never_presents_design_as_implemented() -> None:
    at = _render()
    assert not at.exception, at.exception
    combined = _body(at) + " " + _captions(at)
    assert "Nothing in this design is implemented" in combined
    assert "no QuickBooks connection" in combined
    assert "no Airbyte workspace" in combined
    assert "no BigQuery dataset" in combined


def test_design_doc_exists_with_required_structure_and_readme_link() -> None:
    assert DESIGN_DOC.is_file()
    doc = DESIGN_DOC.read_text()
    for section in [
        "## 1. Goal",
        "## 2. Architecture",
        "## 3. Airbyte source",
        "## 4. Raw table contract",
        "## 5. dbt models",
        "## 6. Reconciliation statuses",
        "## 7. Data quality checks per layer",
        "## 8. Orchestration",
        "## 9. Assumptions",
    ]:
        assert section in doc
    # Card-required design elements.
    for element in [
        "dim_firm_accounting_mapping",
        "quickbooks_customer_id",
        "reconciliation_status",
        "absolute_delta",
        "pct_delta",
        "fct_commission_daily",
    ]:
        assert element in doc
    readme = README.read_text()
    assert "docs/quickbooks_reconciliation_design.md" in readme
