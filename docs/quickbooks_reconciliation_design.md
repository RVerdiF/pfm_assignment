# QuickBooks → BigQuery → dbt reconciliation design (Area 2)

Design answer for **Area 2: Investigation, Integration & Monitoring** — how
QuickBooks invoices would be reconciled against TrackNow commission daily.
This document is a **design only**: no QuickBooks connection, Airbyte
workspace, BigQuery dataset, or dbt model from it is implemented in this
repository, and no figures in it are real data. The only executable part of
this repo stays the local DuckDB sample pipeline; the TrackNow side of this
design refers to the production `fct_commission_daily` concept, whose local
proxy here is `marts.fct_commission_daily_local` (grain
`conversion_date, firm_id`).

## 1. Goal

Finance invoices affiliate commissions out of QuickBooks while TrackNow
records commission per conversion per day. Two systems answer "how much does
firm X earn for period Y" and can drift apart. The goal is a daily automated
reconciliation that compares both sides at the same grain, classifies every
difference into an actionable taxonomy, and alerts Finance only when action
is needed.

## 2. Architecture

```text
QuickBooks Online
    |
    v
Airbyte source (QuickBooks Online connector, incremental)
    |
    v
BigQuery  raw_quickbooks.invoices          (raw, Airbyte-managed)
    |
    v
dbt  stg_quickbooks_invoices               (staging: dedupe + type)
    |                                            TrackNow
    |                                            raw.tracknow_checkouts
    |                                                |
    |                                            dbt stg_tracknow_checkouts
    |                                                |
    |                                            fct_commission_daily
    |                                                |
    v                                                v
dbt  int_quickbooks_tracknow_reconciliation  (join via dim_firm_accounting_mapping)
    |
    v
dbt  mart_finance_reconciliation_alerts
    |
    v
Slack / PagerDuty / email
```

| Layer | Relation | Grain | Materialization |
| --- | --- | --- | --- |
| Raw (Airbyte) | `raw_quickbooks.invoices` | One row per raw invoice record/version as delivered by Airbyte | BigQuery table owned by Airbyte |
| Mapping | `dim_firm_accounting_mapping` | One row per (`firm_id`, `valid_from`) — SCD-style temporal versions | dbt seed (curated) |
| Staging | `stg_quickbooks_invoices` | One row per current invoice | View |
| TrackNow | `fct_commission_daily` | One row per (`commission_date`, `firm_id`) | Table |
| Intermediate | `int_quickbooks_tracknow_reconciliation` | One row per (`invoice_id`, `firm_id`) with `period_start`/`period_end` | Table |
| Mart | `mart_finance_reconciliation_alerts` | One row per active reconciliation failure | Table |

## 3. Airbyte source

- **Connector:** QuickBooks Online (Airbyte certified connector).
- **Streams:** `Invoices` is the minimum required stream. `Payments` and
  `Credit Memos` are added only if Finance needs invoiced-vs-paid distinction
  or refund handling; `Customers` only to enrich names for the mapping review
  workflow — never to join.
- **Sync mode:** incremental, cursor `MetaData.LastUpdatedTime` (the
  connector's reported updated-at field), primary key `Id`.
- **Frequency:** daily, scheduled before the dbt run. Hourly only if Finance
  asks for intra-day visibility.
- **Destination:** BigQuery dataset `raw_quickbooks`, table `invoices`, with
  Airbyte metadata columns (`_airbyte_extracted_at`, `_airbyte_updated_at`,
  `_airbyte_raw_id`) retained for lineage and freshness checks.

## 4. Raw table contract

`raw_quickbooks.invoices` is source-shaped: one row per record/version the
connector delivers. If the connector appends multiple versions of the same
invoice, staging deduplicates — the raw layer never does.

Expected fields:

```text
Id                    invoice_id            (string, QuickBooks Id)
DocNumber             doc_number
CustomerRef.value     customer_id
CustomerRef.name      customer_name         (display only, never a join key)
TxnDate               transaction_date
DueDate               due_date
TotalAmt              total_amount
Balance               balance
CurrencyRef.value     currency
EmailStatus / etc.    status inputs
MetaData.LastUpdatedTime  last_updated_at
Line                  line items (JSON), incl. per-item period/description when present
PrivateNote           memo/reference fields
_airbyte_extracted_at ingestion timestamp
```

## 5. dbt models

### 5.1 `dim_firm_accounting_mapping`

The core of the design: getting from a QuickBooks customer to a PFM
`firm_id` **without assuming the IDs match and without joining on name**.

- **Grain:** one row per (`firm_id`, `valid_from`) — SCD-style temporal versions, so a firm can be remapped over time without losing history.
- **Fields:** `firm_id`, `firm_name`, `quickbooks_customer_id`, optional
  `quickbooks_customer_name`, `valid_from`, optional `valid_to` (open-ended
  when `valid_to` is null — the mapping is current until a newer row supersedes
  it).
- **Implementation:** a dbt seed — a small, manually curated CSV reviewed by
  Finance — because the mapping is a business fact no source system owns.
  Enforced tests: `unique` on (`firm_id`, `valid_from`) (a firm can be
  remapped over time, but not twice from the same date), `not_null` on
  `firm_id`, `quickbooks_customer_id`, and `valid_from`, and a non-overlap
  dbt expectation that no two rows for the same `firm_id` have overlapping
  `[valid_from, valid_to)` ranges.

### 5.2 `stg_quickbooks_invoices`

- **Grain:** one row per current invoice.
- **Transformations:** deduplicate by `invoice_id` keeping the latest
  `last_updated_at` version; type dates and numerics; normalize currency
  codes; derive `invoice_status`; expose `quickbooks_customer_id`; preserve
  `doc_number`; extract line-item period boundaries only when present. No
  reconciliation logic in this layer.
- **Fields:** `invoice_id`, `doc_number`, `quickbooks_customer_id`,
  `invoice_date`, `due_date`, `currency_code`, `invoice_total`,
  `open_balance`, `invoice_status`, `period_start`, `period_end`,
  `updated_at`, `loaded_at`.

### 5.3 `int_quickbooks_tracknow_reconciliation`

- **Grain hypothesis (documented, to confirm with Finance):** invoices
  consolidate a billing period, so the preferred grain is one row per
  (`invoice_id`, `firm_id`) with `period_start` / `period_end` taken from the
  line items when they carry period dates, falling back to the invoice's
  own month. If Finance confirms invoices are strictly daily, the grain
  degrades simply to (`invoice_date`, `firm_id`).

```sql
with invoices as (
    select
        i.invoice_id,
        m.firm_id,
        i.period_start,
        i.period_end,
        i.currency_code,
        i.invoice_total
    from {{ ref('stg_quickbooks_invoices') }} i
    left join {{ ref('dim_firm_accounting_mapping') }} m
      on i.quickbooks_customer_id = m.quickbooks_customer_id
     and coalesce(i.invoice_date >= m.valid_from, true)
     and coalesce(i.invoice_date <  m.valid_to,   true)
),

tracknow as (
    select
        firm_id,
        commission_date,
        sum(tracknow_commission_gbp) as commission_amount
    from {{ ref('fct_commission_daily') }}
    group by 1, 2
),

reconciled as (
    select
        i.invoice_id,
        i.firm_id,
        i.period_start,
        i.period_end,
        i.invoice_total as quickbooks_invoice_amount,
        coalesce(sum(t.commission_amount), 0) as tracknow_commission_amount,
        count(t.commission_date) as tracknow_row_count,
        i.currency_code
    from invoices i
    left join tracknow t
      on i.firm_id = t.firm_id
     and t.commission_date between i.period_start and i.period_end
    group by
        i.invoice_id,
        i.firm_id,
        i.period_start,
        i.period_end,
        i.invoice_total,
        i.currency_code
)

select
    r.*,
    abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount) as absolute_delta,
    case when r.quickbooks_invoice_amount > 0
         then abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount)
              / r.quickbooks_invoice_amount
    end as pct_delta,
    -- reconciliation_status: see section 6
    ...
from reconciled r
```

The inverse direction (`missing_quickbooks`) is unioned into the same model:
commission months per firm that are **not** covered by any invoice whose
period contains them become rows with `invoice_id = null` for that
`period_start`/`period_end`, so a missing side is an alert row, not silence.

### 5.4 `mart_finance_reconciliation_alerts`

- **Grain:** one row per active reconciliation failure (every row of
  `int_quickbooks_tracknow_reconciliation` whose `reconciliation_status`
  is actionable — i.e. anything other than `matched`).
- **Fields:** `reconciliation_date`, `firm_id`, `firm_name`, `invoice_id`,
  `period_start`, `period_end`, `quickbooks_amount`, `tracknow_amount`,
  `absolute_delta`, `pct_delta`, `reconciliation_status`, `severity`,
  `detected_at`.
- **Notification:** a post-build step (Cloud Run Job step / orchestrator
  task) queries the mart and posts new/changed rows to Slack (or PagerDuty /
  email for high severity). The mart is the single output contract; the
  notifier holds no logic.

## 6. Reconciliation statuses

Evaluated in this order (first match wins):

| Status | Rule |
| --- | --- |
| `currency_mismatch` | Invoice currency is not GBP and no conversion contract is defined. |
| `unmapped_firm` | `quickbooks_customer_id` has no row in `dim_firm_accounting_mapping`. |
| `missing_tracknow` | `tracknow_row_count = 0` — invoice whose period contains no TrackNow commission rows (distinguishes "no rows" from "rows summing to zero"). |
| `missing_quickbooks` | Commission period with no covering invoice (inverse-direction rows). |
| `matched` | `absolute_delta <= £5 OR pct_delta <= 1%` (example tolerance — **to validate with Finance**, configured as dbt vars, never hard-coded). |
| `variance` | Difference above tolerance. |

## 7. Data quality checks per layer

| # | Layer | Check | Implementation |
| --- | --- | --- | --- |
| 1 | Airbyte / raw | Freshness | dbt source freshness on `raw_quickbooks.invoices` |
| 2 | Airbyte / raw | Invoice primary key not null | `not_null` on `invoice_id` |
| 3 | Airbyte / raw | Schema drift on critical fields | Airbyte schema-drift notification + dbt model contract |
| 4 | Staging | Invoice uniqueness | `unique` on `invoice_id` |
| 5 | Staging | Numeric/currency validity | `not_null`/accepted values on currency, amounts >= 0 |
| 6 | Staging | Customer mapping coverage | Singular test: share of invoices with no mapping is reported (unmapped is an alert state, never a silent drop) |
| 7 | Reconciliation | Join coverage | Singular test: every invoice row ends in exactly one reconciliation row with a status |
| 8 | Reconciliation | Amount variance | Variance rows must satisfy the status rule (no `matched` row above tolerance) |
| 9 | Reconciliation | Missing side | Both directions present: invoice-centric and commission-month rows |
| 10 | Alert mart | Alert freshness | `detected_at` within one scheduled run of now |

## 8. Orchestration

```text
Airbyte sync success
    |
    v
dbt build --select stg_quickbooks_invoices+   (seed, staging, reconciliation, alerts, tests)
    |
    v
reconciliation tests
    |
    v
alert model
    |
    v
notification (Slack / PagerDuty / email)
```

I would run dbt only after the Airbyte sync completes successfully — a
scheduler dependency (Airbyte completion webhook, or the orchestrator task
that triggers both), never a fixed clock time, so dbt never reconciles
against a half-loaded raw table. Failures at any step block the notification
step, which reads only `mart_finance_reconciliation_alerts`.

## 9. Assumptions

1. Invoices consolidate commission periods (the grain hypothesis in 5.3);
   to be confirmed with Finance before implementation.
2. GBP is the functional currency; any non-GBP invoice is
   `currency_mismatch` until Finance defines a conversion contract.
3. The `firm_id` ↔ `quickbooks_customer_id` mapping is maintained manually
   as a curated seed and reviewed by Finance; it is never derived from
   customer names.
4. The tolerance (`£5` / `1%`) is an illustrative placeholder, explicitly to
   be validated with Finance, and configured via dbt vars.
5. Nothing in this design is implemented in this repository: there is no
   QuickBooks connection, Airbyte workspace, BigQuery dataset, or any of the
   dbt models above. The repo's only executable pipeline remains the local
   DuckDB sample (see the README).
