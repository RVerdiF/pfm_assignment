"""Unit tests for the Streamlit attribution analysis page.

Scope: the *data-shaping helpers* that turn dbt relations into the frames the
page renders — not the Streamlit widgets themselves (rendering is exercised
separately with a real warehouse via AppTest). The tests build a small DuckDB
warehouse with the same schema shape as the real dbt marts and assert that the
helpers:

- zero-fill every taxonomy reason and every match method the dbt vocabulary
  declares (so an absent category is visible, not silently dropped);
- keep percentages reconciling to 100%;
- expose the full reason vocabulary, so a dbt taxonomy drift is caught at
  test time instead of silently showing an incomplete audit panel.

These helpers must read only dbt-published relations. No attribution rule is
re-implemented: the queries are plain group-by aggregations over views whose
shapes mirror the dbt relations the app reads.
"""
from __future__ import annotations

import duckdb
import pandas as pd
import pytest

import sys
from pathlib import Path

_STREAMLIT_DIR = Path(__file__).resolve().parents[1] / "streamlit"
sys.path.insert(0, str(_STREAMLIT_DIR))

import sections.analysis as analysis  # noqa: E402


@pytest.fixture()
def connection(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with marts shaped like the real dbt relations.

    Only the columns the analysis helpers select are needed. The taxonomy rows
    deliberately cover a strict subset of the declared vocabulary so the tests
    can prove the zero-fill behaviour.
    """
    con = duckdb.connect(str(tmp_path / "test.duckdb"))
    con.execute("create schema marts")
    con.execute("create schema intermediate")

    con.execute(
        """
        create table marts.fct_revenue_attribution as
        select * from (values
            ('c1', date '2026-05-09', 'active', 10.00, 'unmatched', null,   null,           null),
            ('c2', date '2026-05-09', 'active', 20.00, 'matched',   's1', 'gclid_exact',  'google'),
            ('c3', date '2026-05-10', 'refunded', 5.00, 'ambiguous', null, null,           null),
            ('c4', date '2026-05-10', 'active', 7.50, 'matched',   's2', 'fbclid_exact', 'facebook'),
            ('c5', date '2026-05-11', 'active', 3.25, 'unmatched', null, null,           null)
        ) as t(
            conversion_id, conversion_date, status, commission_gbp,
            match_status, matched_session_id, match_method, utm_source
        )
        """
    )

    con.execute(
        """
        create table intermediate.int_unmatched_conversions as
        select * from (values
            ('c1', date '2026-05-09', 'unmatched', 'click_id_not_found'),
            ('c3', date '2026-05-10', 'ambiguous', 'multiple_candidates'),
            ('c5', date '2026-05-11', 'unmatched', 'missing_click_id')
        ) as t(conversion_id, conversion_date, attribution_status, unmatched_reason)
        """
    )

    con.execute(
        """
        create table marts.mart_attribution_health as
        select * from (values
            (date '2026-05-09', 'google',   1, 1, 0, 0),
            (date '2026-05-09', null,       2, 0, 2, 0),
            (date '2026-05-10', 'facebook', 1, 1, 0, 0),
            (date '2026-05-10', null,       1, 0, 0, 1)
        ) as t(
            conversion_date, utm_source, total_conversions,
            matched_conversions, unmatched_conversions, ambiguous_conversions
        )
        """
    )

    con.execute(
        """
        create table marts.fct_commission_daily_local as
        select * from (values
            (date '2026-05-09', 'f1', 2, 30.00, 300.00),
            (date '2026-05-10', 'f2', 1, 7.50, 75.00)
        ) as t(
            conversion_date, firm_id, conversion_count,
            commission_gbp, sales_amount_gbp
        )
        """
    )
    return con


def test_overview_metrics_are_pure_aggregates(connection) -> None:
    metrics = analysis._overview_metrics(connection)
    assert metrics["conversions"] == 5
    assert metrics["commission_gbp"] == pytest.approx(45.75)
    assert metrics["matched"] == 2
    assert metrics["unmatched"] == 2
    assert metrics["ambiguous"] == 1
    assert metrics["total_decided"] == 5
    assert metrics["match_rate"] == pytest.approx(0.4)
    assert metrics["unmatched_rate"] == pytest.approx(0.4)


def test_unmatched_reason_counts_zero_fill_entire_vocabulary(connection) -> None:
    frame = analysis._unmatched_reason_counts(connection)
    # The synthetic sample has only three reasons; the taxonomy declares five.
    assert set(frame["unmatched_reason"]) == set(analysis.UNMATCHED_REASONS)
    by_reason = dict(zip(frame["unmatched_reason"], frame["conversions"], strict=True))
    assert by_reason["click_id_not_found"] == 1
    assert by_reason["multiple_candidates"] == 1
    assert by_reason["missing_click_id"] == 1
    assert by_reason["outside_posthog_sample_window"] == 0
    assert by_reason["unknown"] == 0


def test_unmatched_reason_percentages_reconcile_to_100(connection) -> None:
    frame = analysis._unmatched_reason_counts(connection)
    assert frame["conversions"].sum() == 3
    assert frame["percent"].sum() == pytest.approx(100.0)


def test_unmatched_reason_counts_empty_relation_returns_zero_percentages(
    connection,
) -> None:
    """An all-matched warehouse has an empty int_unmatched_conversions view.

    The diagnosis must still render a complete taxonomy with valid 0.0%
    percentages — never NaN from a 0/0 division and never a silently dropped
    reason vocabulary.
    """
    connection.execute("delete from intermediate.int_unmatched_conversions")
    frame = analysis._unmatched_reason_counts(connection)
    assert set(frame["unmatched_reason"]) == set(analysis.UNMATCHED_REASONS)
    assert frame["conversions"].sum() == 0
    assert frame["percent"].sum() == pytest.approx(0.0)
    assert frame["percent"].notna().all()
    assert (frame["percent"] == 0.0).all()


def test_match_method_counts_zero_fill_entire_vocabulary(connection) -> None:
    frame = analysis._match_method_counts(connection)
    # The synthetic sample has two matched conversions attributed through
    # gclid_exact and fbclid_exact; url_click_exact is absent and must stay a
    # visible zero row.
    assert set(frame["match_method"]) == set(analysis.MATCH_METHODS)
    by_method = dict(zip(frame["match_method"], frame["conversions"], strict=True))
    assert by_method["gclid_exact"] == 1
    assert by_method["fbclid_exact"] == 1
    assert by_method["url_click_exact"] == 0


def test_marketing_attribution_groups_unattributed(connection) -> None:
    frame = analysis._marketing_attribution(connection)
    by_source = dict(zip(frame["utm_source"], frame["conversions"], strict=True))
    assert by_source["google"] == 1
    assert by_source["facebook"] == 1
    # unmatched + ambiguous conversions roll into the explicit Unattributed
    # bucket; no channel is invented for them.
    assert by_source["Unattributed"] == 3
    assert frame["conversions"].sum() == 5


def test_commission_view_groups_attributed_vs_unattributed(connection) -> None:
    frame = analysis._commission_view(connection)
    by_status = dict(
        zip(frame["attribution_status"], frame["commission_gbp"], strict=True)
    )
    assert by_status["Attributed"] == pytest.approx(27.50)
    assert by_status["Unattributed"] == pytest.approx(18.25)
    assert by_status["Attributed"] + by_status["Unattributed"] == pytest.approx(45.75)
