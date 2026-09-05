"""Headless AppTest render of the "What I'd do next" page.

Drives the final walkthrough section through AppTest.from_file (a real
Streamlit script that imports the section module). Unlike the other pages this
one is pure prose by design - it reads no warehouse relation and renders no
chart - so the checks assert the Card-4 acceptance criteria: the section is a
real page at the end of the walkthrough, it names every production topic with
a clear purpose (BigQuery, dbt-bigquery, Terraform, Cloud Storage, Cloud Run
Jobs/Cloud Build, GitHub Actions, monitoring), it makes the change-vs-constant
split explicit, and it never presents the future architecture as implemented.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_next_steps_driver.py"
APP = ROOT / "streamlit" / "app.py"


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _body(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.caption)


def test_next_steps_page_renders() -> None:
    at = _render()
    assert not at.exception, at.exception
    headers = {h.value for h in at.header}
    assert "What I'd do next" in headers
    subheaders = {h.value for h in at.subheader}
    assert "Where this would go" in subheaders
    assert "What changes" in subheaders
    assert "What stays the same" in subheaders


def test_next_steps_page_is_last_page_in_app_navigation() -> None:
    """The outline page still closes the walkthrough navigation."""
    app_source = APP.read_text()
    assert "next_steps" in app_source
    nav_start = app_source.index("pages = {")
    nav_end = app_source.index("navigation = st.navigation")
    nav_block = app_source[nav_start:nav_end]
    assert "What I'd do next" in nav_block
    # The closing page sits in the Area 2 group, after the Area 1 pages and
    # after the Area 2 investigation and design pages.
    assert nav_block.rindex("url_path=\"next-steps\"") > nav_block.rindex(
        "url_path=\"methodology\""
    )
    assert nav_block.rindex("url_path=\"next-steps\"") > nav_block.rindex(
        "url_path=\"investigation-monitoring\""
    )
    assert nav_block.rindex("url_path=\"next-steps\"") > nav_block.rindex(
        "url_path=\"quickbooks-reconciliation\""
    )
    assert nav_block.rindex("url_path=\"next-steps\"") > nav_block.rindex(
        "url_path=\"monitoring-design\""
    )


def test_next_steps_states_local_today_and_production_message() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    assert (
        "**This implementation is intentionally local and self-contained.**"
    ) in body
    assert "preserve the same transformation contracts" in body
    assert "moving execution and storage to managed GCP services" in body


def test_next_steps_mentions_every_required_topic_with_purpose() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    # Every production topic the card lists must be present and tied to the
    # role it would play (not just dropped as a buzzword).
    required = [
        "**BigQuery**",
        "**dbt-bigquery**",
        "**Terraform**",
        "**Cloud Storage**",
        "**Cloud Run Jobs**",
        "Cloud Build",
        "**GitHub Actions**",
        "**Cloud Monitoring**",
    ]
    for topic in required:
        assert topic in body
    # Clear purpose for each: adapter keeps contracts; Terraform provisions;
    # Cloud Storage is the landing zone; Cloud Run/Cloud Build execute; CI/CD
    # lints/tests/validates/deploys; monitoring watches freshness/failures/
    # match-rate and unmatched/ambiguous shifts.
    for purpose in [
        "managed warehouse",
        "adapter-specific",
        "minimum permissions",
        "landing zone",
        "run ingestion",
        "controlled environment",
        "data freshness",
        "attribution match rate",
        "`unmatched` or `ambiguous`",
    ]:
        assert purpose in body


def test_next_steps_shows_production_architecture() -> None:
    at = _render()
    assert not at.exception, at.exception
    code_blocks = " ".join(str(c.value) for c in at.code)
    assert (
        "Source -> Cloud Storage/API -> BigQuery raw -> dbt -> BigQuery marts "
        "-> Streamlit/BI"
    ) in code_blocks
    support = _captions(at)
    assert "Terraform + GitHub Actions" in support
    assert "Cloud Run Jobs / Cloud Build" in support
    assert "Cloud Monitoring" in support


def test_next_steps_splits_changes_from_constants() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    # Explicit change-vs-constant framing required by the card.
    assert "What changes" in " ".join(str(h.value) for h in at.subheader)
    assert "What stays the same" in " ".join(str(h.value) for h in at.subheader)
    # The transformation contracts and mart shapes survive the move.
    assert "dbt models keep owning" in body
    assert "read-only consumer" in body
    assert "BigQuery-compatible" in body or "attribution_health.sql" in body


def test_next_steps_never_presents_future_infra_as_implemented() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
    captions = _captions(at)
    combined = body + " " + captions
    assert "Nothing on this page is implemented" in combined
    assert "no BigQuery datasets" in combined
    assert "no Terraform configuration" in combined
    # The page must read no warehouse relation: it renders no metrics, no
    # charts, and its source queries nothing.
    assert not at.metric
    assert not at.get("vega_lite_chart")
    source = (ROOT / "streamlit" / "sections" / "next_steps.py").read_text()
    assert "execute(" not in source
    assert "read_relation(" not in source
    assert "require_connection(" not in source
    assert "connection_for_app(" not in source
