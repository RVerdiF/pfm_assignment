"""Testes da Etapa 1 — ingestão Excel -> DuckDB raw.

Foco comportamental:
- to_snake_case normaliza nomes de colunas sem quebrar os já snake_case.
- sheet_to_table mapeia aba -> nome de tabela (tracknow_checkouts / posthog_sessions).
- load_excel_into_duckdb grava schema raw + tabelas, sem registrar linhas vazias
  do rodapé e sem filtrar/deduplicar registros reais.
- validate reconhece reconciliação de linhas/colunas/nomes.
"""
import os

import duckdb
import openpyxl
import pytest

from ingestion import load_excel as le

# ---------------------------------------------------------------------------
# Unit: to_snake_case
# ---------------------------------------------------------------------------

def test_snake_case_keeps_existing_snake_case():
    assert le.to_snake_case("click_id") == "click_id"
    assert le.to_snake_case("order_price_gbp") == "order_price_gbp"
    assert le.to_snake_case("utm_source") == "utm_source"
    assert le.to_snake_case("has_tracknow_conversion") == "has_tracknow_conversion"
    assert le.to_snake_case("affiliate_session_id") == "affiliate_session_id"


def test_snake_case_normalizes_spaces_and_punctuation():
    assert le.to_snake_case("Click ID") == "click_id"
    assert le.to_snake_case("Order Price (GBP)") == "order_price_gbp"
    assert le.to_snake_case("  Session Duration Seconds  ") == "session_duration_seconds"
    assert le.to_snake_case("utm content") == "utm_content"


def test_snake_case_splits_camel_boundaries():
    assert le.to_snake_case("hasCheckoutStarted") == "has_checkout_started"
    assert le.to_snake_case("tracknowUserId") == "tracknow_user_id"


# ---------------------------------------------------------------------------
# Unit: sheet_to_table
# ---------------------------------------------------------------------------

def test_sheet_to_table_maps_target_sheets():
    assert le.sheet_to_table("Sample TrackNow Checkouts") == "tracknow_checkouts"
    assert le.sheet_to_table("Sample PostHog Sessions") == "posthog_sessions"


# ---------------------------------------------------------------------------
# Integration: cria xlsx minúsculo e carrega no duckdb
# ---------------------------------------------------------------------------

def _write_fixture_xlsx(path):
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Sample TrackNow Checkouts"
    ws1.append(["Click ID", "Order Price (GBP)"])
    ws1.append(["id-aaaa", 66.97])
    ws1.append(["id-bbbb", None])
    # rodapé vazio (linhas em branco até a 10) — não são registros
    for _ in range(8):
        ws1.append([])

    ws2 = wb.create_sheet("Sample PostHog Sessions")
    ws2.append(["Session ID", "click_id_from_url", "utm_source"])
    ws2.append(["sess-1", "click-1", "google"])
    ws2.append(["sess-2", None, "facebook"])
    ws2.append(["sess-3", "click-3", None])
    for _ in range(7):
        ws2.append([])

    wb.save(path)


@pytest.fixture()
def fixture_xlsx(tmp_path):
    p = tmp_path / "sample.xlsx"
    _write_fixture_xlsx(str(p))
    return str(p)


@pytest.fixture()
def duckdb_path(tmp_path):
    return str(tmp_path / "pfm.duckdb")


def test_load_creates_raw_tables(fixture_xlsx, duckdb_path):
    created = le.load_excel_into_duckdb(fixture_xlsx, duckdb_path)

    assert set(created) == {"tracknow_checkouts", "posthog_sessions"}

    con = duckdb.connect(duckdb_path)
    try:
        schemas = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='raw' ORDER BY table_name"
        ).fetchall()
        assert [r[0] for r in schemas] == ["posthog_sessions", "tracknow_checkouts"]
    finally:
        con.close()


def test_load_row_counts_exclude_only_empty_footer(fixture_xlsx, duckdb_path):
    le.load_excel_into_duckdb(fixture_xlsx, duckdb_path)
    con = duckdb.connect(duckdb_path)
    try:
        n_tracknow = con.execute(
            "SELECT count(*) FROM raw.tracknow_checkouts"
        ).fetchone()[0]
        n_posthog = con.execute(
            "SELECT count(*) FROM raw.posthog_sessions"
        ).fetchone()[0]
    finally:
        con.close()
    # registros reais preservados; rodapé em branco não entra
    assert n_tracknow == 2
    assert n_posthog == 3


def test_load_applies_snake_case_to_columns(fixture_xlsx, duckdb_path):
    le.load_excel_into_duckdb(fixture_xlsx, duckdb_path)
    con = duckdb.connect(duckdb_path)
    try:
        cols1 = [r[0] for r in con.execute("DESCRIBE raw.tracknow_checkouts").fetchall()]
        cols2 = [r[0] for r in con.execute("DESCRIBE raw.posthog_sessions").fetchall()]
    finally:
        con.close()
    assert cols1 == ["click_id", "order_price_gbp"]
    assert cols2 == ["session_id", "click_id_from_url", "utm_source"]


def test_load_preserves_identifier_values(fixture_xlsx, duckdb_path):
    le.load_excel_into_duckdb(fixture_xlsx, duckdb_path)
    con = duckdb.connect(duckdb_path)
    try:
        ids = con.execute(
            "SELECT click_id FROM raw.tracknow_checkouts WHERE click_id IS NOT NULL ORDER BY click_id"
        ).fetchall()
        sessions = con.execute(
            "SELECT session_id FROM raw.posthog_sessions ORDER BY session_id"
        ).fetchall()
    finally:
        con.close()
    assert [r[0] for r in ids] == ["id-aaaa", "id-bbbb"]
    assert [r[0] for r in sessions] == ["sess-1", "sess-2", "sess-3"]


def test_validate_reconciles_ok(fixture_xlsx, duckdb_path):
    le.load_excel_into_duckdb(fixture_xlsx, duckdb_path)
    report = le.validate(excel_path=fixture_xlsx, duckdb_path=duckdb_path)
    assert report["all_ok"] is True
    assert report["tables"]["tracknow_checkouts"]["rows"] == 2
    assert report["tables"]["tracknow_checkouts"]["cols"] == 2
    assert report["tables"]["posthog_sessions"]["rows"] == 3
    assert report["tables"]["posthog_sessions"]["cols"] == 3
    assert set(report["tables"]["tracknow_checkouts"]["columns"]) == {"click_id", "order_price_gbp"}
