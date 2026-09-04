"""Headless AppTest render of the methodology page against real warehouses.

Drives the methodology section through AppTest.from_file. The default tests
use the real built dbt warehouse of this worktree (exposed through the
standard PFM_DUCKDB_PATH override); the reconciliation tests additionally
derive every asserted number from the same dbt relations the page reads, so a
warehouse with different totals (including the documented PFM_DUCKDB_PATH
override) can never be contradicted by the narrative.

These checks verify the Card-3 acceptance criteria on this page: the
attribution method is explained (exact click-id matching, temporal window,
identifier priority, recency), results carry textual interpretation tied to
real mart numbers, and limitations/recommendations are explicit.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "_methodology_driver.py"
WAREHOUSE = ROOT / "warehouse" / "pfm.duckdb"

# The methodology page imports streamlit/warehouse_bootstrap; expose the same
# module so tests can clear its st.cache_resource between warehouse switches.
STREAMLIT_DIR = ROOT / "streamlit"
import sys  # noqa: E402

sys.path.insert(0, str(STREAMLIT_DIR))

import warehouse_bootstrap as wb  # noqa: E402


def _render() -> AppTest:
    at = AppTest.from_file(str(DRIVER), default_timeout=60)
    at.run()
    return at


def _body(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.markdown)


def _captions(at: AppTest) -> str:
    return " ".join(str(c.value) for c in at.caption)


def _relation_totals(database_path: Path) -> dict[str, int | float]:
    """Read the exact relations the methodology page reads, as ground truth."""
    con = duckdb.connect(str(database_path), read_only=True)
    try:
        row = con.execute(
            "select coalesce(sum(total_conversions),0), "
            "coalesce(sum(matched_conversions),0), "
            "coalesce(sum(unmatched_conversions),0), "
            "coalesce(sum(ambiguous_conversions),0) "
            "from marts.mart_attribution_health"
        ).fetchone()
        rev = con.execute(
            "select count(*), coalesce(sum(commission_gbp),0) "
            "from marts.fct_revenue_attribution"
        ).fetchone()
        reasons = con.execute(
            "select unmatched_reason, count(*) "
            "from intermediate.int_unmatched_conversions "
            "group by unmatched_reason"
        ).fetchall()
    finally:
        con.close()
    return {
        "decided": int(row[0]),
        "matched": int(row[1]),
        "unmatched": int(row[2]),
        "ambiguous": int(row[3]),
        "valid": int(rev[0]),
        "commission_gbp": float(rev[1]),
        "reason_counts": {str(r): int(c) for r, c in reasons},
    }


def _assert_narrative_matches_relations(
    body: str, captions: str, facts: dict[str, int | float]
) -> None:
    """Assert every numeric claim in the narrative matches the live relations.

    The page reads the same three relations this helper queries, so any
    hard-coded or stale prose that disagrees with the warehouse is caught.
    """
    decided = int(facts["decided"])
    matched = int(facts["matched"])
    unmatched = int(facts["unmatched"])
    ambiguous = int(facts["ambiguous"])
    valid = int(facts["valid"])
    commission = float(facts["commission_gbp"])
    reasons = facts["reason_counts"]
    missing = int(reasons.get("missing_click_id", 0))
    not_found = int(reasons.get("click_id_not_found", 0))
    outside = int(reasons.get("outside_posthog_sample_window", 0))
    non_matched = sum(reasons.values())

    # Caption mirrors the health mart sums exactly.
    assert (
        f"{decided:,} conversions — {matched:,} matched, "
        f"{unmatched:,} unmatched, {ambiguous:,} ambiguous."
    ) in captions

    if decided and matched == 0 and valid:
        # The all-unmatched reading must cite the live decided/revenue totals.
        assert (
            f"Of the {decided:,} decided conversions, the health mart counts "
            f"{matched:,} matched and {unmatched + ambiguous:,} unmatched/ambiguous"
        ) in body
        assert f"({valid:,} valid conversions, £{commission:,.2f} of commission)" in body
        assert f"misattribute the whole £{commission:,.2f}" in body

    if missing and not_found:
        # Loss-cause prose lists both live reason counts, joined as items.
        assert (
            f"{missing:,} conversions have no click id at all" in body
            and f"a further {not_found:,} carry a click id" in body
        )
    elif missing:
        assert f"{missing:,} conversions have no click id at all" in body
    elif not_found:
        assert f"{not_found:,} carry a click id that the PostHog sample never records" in body

    if outside:
        assert f"{outside:,} conversions fall outside" in body

    # Recommendation tails carry the same reason counts when present.
    if missing:
        assert (
            f"In this sample, {missing:,} conversions arrived without one."
        ) in body
    if not_found:
        assert (
            f"In this sample, {not_found:,} conversions carried a click id "
            "the PostHog sample never saw."
        ) in body
    if outside:
        assert (
            f"In this sample, {outside:,} conversions fall outside the "
            "PostHog sample window."
        ) in body


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
    body = _body(at)
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


def test_methodology_page_lists_limitations_and_recommendations() -> None:
    at = _render()
    assert not at.exception, at.exception
    body = _body(at)
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


def test_methodology_prose_reconciles_with_live_marts() -> None:
    """Narrative numbers are derived from the real dbt relations, not literals.

    Expected values are read from the same relations here (never hard-coded),
    so a rebuilt warehouse with different totals can never make the narrative
    lie.
    """
    at = _render()
    assert not at.exception, at.exception
    _assert_narrative_matches_relations(
        _body(at), _captions(at), _relation_totals(WAREHOUSE)
    )


def test_methodology_narrative_renders_against_non_default_warehouse(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: a PFM_DUCKDB_PATH override with different totals is honored.

    Builds a *different valid warehouse* (non-default data: some matches,
    different commission, different reason mix) and proves the narrative
    switches to those live totals instead of quoting the delivered sample.
    This is the defect the review gate reported: hard-coded prose would keep
    claiming 100/0/£1,001.70 against a warehouse that says otherwise.
    """
    synthetic = tmp_path / "pfm.duckdb"
    _build_synthetic_warehouse(synthetic)
    facts = _relation_totals(synthetic)

    monkeypatch.setenv("PFM_DUCKDB_PATH", str(synthetic))
    # AppTest runs share one process-global st.cache_resource; clear the
    # connection cache so the override path is actually re-resolved.
    wb.get_warehouse_connection.clear()
    try:
        at = _render()
        assert not at.exception, at.exception
        body = _body(at)
        captions = _captions(at)

        # The narrative (caption + prose) reconciles to the synthetic relations.
        _assert_narrative_matches_relations(body, captions, facts)

        # The all-unmatched reading must NOT appear when the override has
        # matches; the delivered-sample totals must never leak into an
        # override render.
        if int(facts["matched"]) > 0:
            assert "The whole valid sample is unattributed" not in body
        assert "£1,001.70" not in body
        assert "100 conversions" not in captions
    finally:
        wb.get_warehouse_connection.clear()


def _build_synthetic_warehouse(path: Path) -> None:
    """Create a minimal-but-valid warehouse with non-default attribution totals.

    Schema mirrors the relations the methodology page reads (the three
    EXPECTED_MARTS plus the intermediate diagnostic view) so the app treats it
    as an already-provisioned warehouse. Data: 12 decided conversions with 3
    matched (some attribution exists), a reason taxonomy (missing=4,
    not_found=3, outside=2) that sums to the 9 non-matched decided rows, and
    revenue-valid rows with a distinct commission total. Note the revenue mart
    keeps only the revenue-valid population (here 10 of the 12 decided rows:
    3 matched + 5 unmatched + 2 ambiguous); the health mart counts all 12.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute("create schema marts")
        con.execute("create schema intermediate")

        con.execute(
            "create table marts.mart_attribution_health ("
            "conversion_date date, utm_source varchar, "
            "total_conversions int, matched_conversions int, "
            "unmatched_conversions int, ambiguous_conversions int, "
            "match_rate double, unmatched_rate double, "
            "gclid_exact_matches int, fbclid_exact_matches int, "
            "url_click_exact_matches int)"
        )
        # 12 decided = 3 matched + 7 unmatched + 2 ambiguous.
        con.execute(
            "insert into marts.mart_attribution_health values "
            "(date '2026-06-01', 'google', 12, 3, 7, 2, 0.25, 0.5833, 2, 1, 0)"
        )

        con.execute(
            "create table marts.fct_revenue_attribution ("
            "conversion_id varchar, conversion_date date, firm_id varchar, "
            "status varchar, commission_gbp double, match_status varchar, "
            "matched_session_id varchar, matched_distinct_id varchar, "
            "match_method varchar, utm_source varchar, utm_medium varchar, "
            "utm_campaign varchar, utm_content varchar)"
        )
        con.execute(
            "insert into marts.fct_revenue_attribution values "
            "('m1', date '2026-06-01', 'f1', 'active', 50.0, 'matched', 's1', 'd1', 'gclid_exact', 'google', 'cpc', 'camp1', NULL), "
            "('m2', date '2026-06-01', 'f1', 'active', 40.0, 'matched', 's2', 'd2', 'fbclid_exact', 'facebook', 'cpc', 'camp2', NULL), "
            "('m3', date '2026-06-01', 'f2', 'active', 25.0, 'matched', 's3', 'd3', 'gclid_exact', 'google', 'cpc', 'camp3', NULL), "
            "('u1', date '2026-06-01', 'f1', 'active', 60.0, 'unmatched', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('u2', date '2026-06-01', 'f2', 'active', 30.0, 'unmatched', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('u3', date '2026-06-02', 'f1', 'active', 20.0, 'unmatched', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('u4', date '2026-06-02', 'f2', 'active', 15.0, 'unmatched', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('a1', date '2026-06-02', 'f1', 'active', 10.0, 'ambiguous', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('a2', date '2026-06-02', 'f2', 'active', 10.0, 'ambiguous', NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
            "('u5', date '2026-06-03', 'f1', 'active', 10.75, 'unmatched', NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        )

        con.execute(
            "create table marts.fct_commission_daily_local ("
            "conversion_date date, firm_id varchar, conversion_count int, "
            "commission_gbp double, sales_amount_gbp double)"
        )

        con.execute(
            "create table intermediate.int_unmatched_conversions ("
            "conversion_id varchar, unmatched_reason varchar)"
        )
        con.execute(
            "insert into intermediate.int_unmatched_conversions values "
            "('u1', 'missing_click_id'), ('u2', 'missing_click_id'), "
            "('u3', 'missing_click_id'), ('u4', 'missing_click_id'), "
            "('u5', 'click_id_not_found'), ('a1', 'click_id_not_found'), "
            "('a2', 'click_id_not_found'), "
            "('x1', 'outside_posthog_sample_window'), "
            "('x2', 'outside_posthog_sample_window')"
        )
    finally:
        con.close()
