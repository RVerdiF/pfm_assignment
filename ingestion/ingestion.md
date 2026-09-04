# Ingestion

Step 1 of the pipeline: copy the analytical sheets of `data/source.xlsx` into
the `raw` schema of the local DuckDB warehouse
(`warehouse/pfm.duckdb`) using Polars.

## Sheet-to-table mapping

| Excel sheet                | DuckDB table                |
|----------------------------|-----------------------------|
| `Sample TrackNow Checkouts` | `raw.tracknow_checkouts`   |
| `Sample PostHog Sessions`   | `raw.posthog_sessions`     |

The mapping lives in `SHEET_TO_TABLE` inside `ingestion/load_excel.py`. A sheet
that is not mapped raises `ValueError("Sheet not mapped for ingestion: ...")`.

## Column contract: snake_case only

Column names are normalized to snake_case by `to_snake_case`. The rules:

- lower-case everything;
- split camelCase / PascalCase boundaries (`hasCheckoutStarted` ->
  `has_checkout_started`);
- convert spaces and punctuation (parentheses, hyphens, slashes) to
  underscores (`Order Price (GBP)` -> `order_price_gbp`);
- collapse repeated underscores and strip leading/trailing underscores;
- identifiers already in snake_case are untouched (`click_id` stays
  `click_id`).

Values are **not** transformed: values, nulls, and identifiers are preserved
intact. No rows are filtered, deduplicated, or imputed during ingestion.

## Fully null rows are preserved

Sheets are read with `polars.read_excel(..., drop_empty_rows=False)`.

The spreadsheet extent is the source contract: interior fully null rows that
exist inside a worksheet's used range are real records, not footers to trim.
Setting `drop_empty_rows=False` keeps them (the calamine default would collapse
them). The elevated test `test_load_retains_fully_null_interior_rows` pins this
behavior: a fully null interior row is ingested as a row of all nulls.

## Raw schema

The DuckDB database lives at `warehouse/pfm.duckdb` (gitignored; only the
directory placeholder is committed). Table creation:
`CREATE SCHEMA IF NOT EXISTS raw`, then each mapped sheet becomes
`CREATE TABLE raw.<table> AS SELECT * FROM <sheet frame>`.

Observed extent of the bundled sample (`data/source.xlsx`):

### raw.tracknow_checkouts (13 columns, 100 rows)

```text
tracknow_order_id, created_date, click_id, affiliate_session_id, firm_id,
status, order_price_gbp, referral_bonus_gbp, coupon_used, trading_platform,
first_order, account_size, tracknow_user_id
```

### raw.posthog_sessions (17 columns, 200 rows)

```text
session_id, posthog_distinct_id, session_date, session_start_at,
session_duration_seconds, click_id_from_url, fbclid, gclid, utm_source,
utm_medium, utm_campaign, utm_content, country_code, session_entry_pathname,
has_checkout_started, has_tracknow_conversion, events_in_session
```

## How to re-run

From the repository root with the virtual environment active:

```bash
python ingestion/load_excel.py
```

What it does:

1. reads `data/source.xlsx`;
2. creates/replaces `raw.tracknow_checkouts` and `raw.posthog_sessions` in
   `warehouse/pfm.duckdb`;
3. prints the created table names;
4. runs `validate` — a reconciliation that compares row counts, column counts,
   and snake_case-normalized column names between the Excel sheets and the
   DuckDB tables;
5. exits non-zero when reconciliation fails (`Reconciliation failed: Excel and
   DuckDB diverge.`).

Re-running is safe and idempotent: each mapped table is dropped and recreated.

## Tests

The ingestion contract is covered by `tests/test_load_excel.py` (unit tests for
`to_snake_case` and `sheet_to_table`, integration tests that build a small
Excel fixture, load it into a temporary DuckDB, and assert schema, row counts,
null preservation, and reconciliation).