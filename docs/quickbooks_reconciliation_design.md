# QuickBooks → BigQuery → dbt reconciliation design (Area 2)

Design answer for **Area 2: Investigation, Integration & Monitoring** - how
QuickBooks invoices would be reconciled against TrackNow commission daily.
This document is a **design only**: no QuickBooks connection, Airbyte
workspace, BigQuery dataset, or dbt model from it is implemented in this
repository, and no figures in it are real data. The only executable part of
this repo stays the local DuckDB sample pipeline. The TrackNow side of this
design has two deliberately different inputs: an operational daily
commission aggregate and the authoritative daily commission published by the
Google Sheet. The local proxy here is
`marts.fct_commission_daily_local` (grain `conversion_date, firm_id`); it is
not the missing authoritative Google Sheet.

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
    |                                            TrackNow operational
    |                                            raw.tracknow_checkouts
    |                                                |
    |                                            dbt stg_tracknow_checkouts
    |                                                |
    |                                            fct_tracknow_commission_daily (daily)
    |                                                |
    v                                                v
dbt  int_quickbooks_tracknow_reconciliation  (aggregate by firm, explicit period, currency)
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
| Mapping | `dim_firm_accounting_mapping` | One row per (`firm_id`, `valid_from`) - SCD-style temporal versions | dbt seed (curated) |
| Staging | `stg_quickbooks_invoices` | One row per current invoice | View |
| TrackNow operational | `fct_tracknow_commission_daily` | One row per (`commission_date`, `firm_id`, `currency_code`) | Table |
| Intermediate | `int_quickbooks_tracknow_reconciliation` | One row per (`firm_id`, explicit `period_start`/`period_end`, `currency_code`) | Table |
| Mart | `mart_finance_reconciliation_alerts` | One row per active reconciliation failure | Table |

## 3. Airbyte source

- **Connector:** QuickBooks Online (Airbyte certified connector).
- **Streams:** `Invoices` is the minimum required stream. `Payments` and
  `Credit Memos` are added only if Finance needs invoiced-vs-paid distinction
  or refund handling; `Customers` only to enrich names for the mapping review
  workflow - never to join.
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
invoice, staging deduplicates - the raw layer never does.

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

The billing period is an explicit source field, preferably extracted from
line-item service dates or an agreed invoice period field. It is not inferred
from `TxnDate`. A row with no complete start and end dates has
`period_start = null`, `period_end = null`, and `period_status =
'missing_period'`; it remains visible for review and is never silently put in
the invoice month. Currency is required on both sides before amounts are
compared.

## 5. dbt models

### 5.1 `dim_firm_accounting_mapping`

The core of the design: getting from a QuickBooks customer to a PFM
`firm_id` **without assuming the IDs match and without joining on name**.

- **Grain:** one row per (`firm_id`, `valid_from`) - SCD-style temporal versions, so a firm can be remapped over time without losing history.
- **Fields:** `firm_id`, `firm_name`, `quickbooks_customer_id`, optional
  `quickbooks_customer_name`, `valid_from`, optional `valid_to` (open-ended
  when `valid_to` is null - the mapping is current until a newer row supersedes
  it).
- **Implementation:** a dbt seed - a small, manually curated CSV reviewed by
  Finance - because the mapping is a business fact no source system owns.
  Enforced tests: `unique` on (`firm_id`, `valid_from`) (a firm can be
  remapped over time, but not twice from the same date), `not_null` on
  `firm_id`, `quickbooks_customer_id`, and `valid_from`, and non-overlap of
  `[valid_from, valid_to)` ranges for both `firm_id` and
  `quickbooks_customer_id`. The invoice join uses the invoice's accounting
  date as the mapping-effective date and records a mapping count; zero is
  `unmapped_firm`, more than one is `ambiguous_firm_mapping`. This prevents
  temporal mapping fanout from multiplying invoice amounts.

### 5.2 `stg_quickbooks_invoices`

- **Grain:** one row per current invoice.
- **Transformations:** deduplicate by `invoice_id` keeping the latest
  `last_updated_at` version; type dates and numerics; normalize currency
  codes; derive `invoice_status`; expose `quickbooks_customer_id`; preserve
  `doc_number`; extract line-item period boundaries only when present. Set
  `period_status` to `explicit` only when both boundaries are present and
  valid; otherwise use `missing_period`. No invoice-month fallback and no
  reconciliation logic in this layer.
- **Fields:** `invoice_id`, `doc_number`, `quickbooks_customer_id`,
  `invoice_date`, `due_date`, `currency_code`, `invoice_total`,
  `open_balance`, `invoice_status`, `period_start`, `period_end`,
  `period_status`, `updated_at`, `loaded_at`.

### 5.3 `int_quickbooks_tracknow_reconciliation`

- **Grain:** one row per (`firm_id`, `period_start`, `period_end`,
  `currency_code`). Both sides are aggregated to this key before they are
  joined. Two £500 invoices for one firm and one explicit billing period are
  therefore one £1,000 invoice-side amount; neither invoice is compared with
  the full firm total a second time.
- **Mapping segregation:** invoices with no mapping (`mapping_match_count = 0`)
  and invoices with ambiguous mapping (`mapping_match_count > 1`) are kept in
  separate groups and never collapsed together under `firm_id = null`.
- **Billing-period contract:** only a complete period extracted from the
  invoice source is an explicit billing period. The invoice date/month is not
  a fallback. A row with missing or incomplete boundaries stays
  `period_status = 'missing_period'` and is retained for review without being
  assigned to an invented period.
- **Source semantics:** `tracknow_commission_amount` is the operational
  TrackNow value used for the QuickBooks comparison. The authoritative Google
  Sheet daily value is a separate financial source and is not silently
  substituted into this field or allocated back to conversions.

```sql
with invoice_mapping_candidates as (
    select
        i.*,
        i.invoice_id,
        m.firm_id as mapped_firm_id,
        count(m.firm_id) over (partition by i.invoice_id) as mapping_match_count,
        row_number() over (partition by i.invoice_id order by m.firm_id nulls last) as mapping_candidate_rank
    from {{ ref('stg_quickbooks_invoices') }} i
    left join {{ ref('dim_firm_accounting_mapping') }} m
      on i.quickbooks_customer_id = m.quickbooks_customer_id
     and i.invoice_date is not null
     and i.invoice_date >= m.valid_from
     and (m.valid_to is null or i.invoice_date < m.valid_to)
),

invoice_rows as (
    -- Keep one physical row per invoice before summing. An overlapping
    -- mapping is reported by mapping_match_count but cannot multiply money.
    select *
    from invoice_mapping_candidates
    where mapping_candidate_rank = 1
),

invoice_groups as (
    -- Distinct mapping outcomes (unmapped vs ambiguous) are kept in separate
    -- groups so max(mapping_match_count) cannot hide unmapped invoices.
    select
        case when mapping_match_count = 1 then mapped_firm_id end as firm_id,
        period_start,
        period_end,
        currency_code,
        sum(invoice_total) as quickbooks_invoice_amount,
        count(distinct invoice_id) as invoice_count,
        case
            when mapping_match_count = 0 then 0
            when mapping_match_count > 1 then 2
            else 1
        end as mapping_match_count
    from invoice_rows
    where period_status = 'explicit'
    group by 1, 2, 3, 4, 7
),

tracknow_by_period as (
    select
        i.firm_id,
        i.period_start,
        i.period_end,
        i.currency_code,
        sum(t.commission_gbp) as tracknow_commission_amount,
        count(t.commission_date) as tracknow_row_count
    from invoice_groups i
    left join {{ ref('fct_tracknow_commission_daily') }} t
      on i.firm_id = t.firm_id
     and t.commission_date between i.period_start and i.period_end
     and t.currency_code = i.currency_code
    where i.firm_id is not null
    group by 1, 2, 3, 4
),

period_reconciled as (
    select
        i.firm_id,
        i.period_start,
        i.period_end,
        i.currency_code,
        i.quickbooks_invoice_amount,
        i.invoice_count,
        i.mapping_match_count,
        t.tracknow_commission_amount,
        t.tracknow_row_count
    from invoice_groups i
    left join tracknow_by_period t using (firm_id, period_start, period_end, currency_code)
),

unknown_period as (
    select
        case when mapping_match_count = 1 then mapped_firm_id end as firm_id,
        null as period_start,
        null as period_end,
        currency_code,
        sum(invoice_total) as quickbooks_invoice_amount,
        count(distinct invoice_id) as invoice_count,
        case
            when mapping_match_count = 0 then 0
            when mapping_match_count > 1 then 2
            else 1
        end as mapping_match_count,
        null as tracknow_commission_amount,
        null as tracknow_row_count
    from invoice_rows
    where period_status = 'missing_period'
    group by 1, 4, 7
),

uncovered_tracknow as (
    -- Source-coverage check: operational TrackNow daily rows not covered by
    -- any explicit invoice billing period are retained as missing_period
    -- without inventing a fabricated commission month.
    select
        t.firm_id,
        null as period_start,
        null as period_end,
        t.currency_code,
        null as quickbooks_invoice_amount,
        null as invoice_count,
        1 as mapping_match_count,
        sum(t.commission_gbp) as tracknow_commission_amount,
        count(t.commission_date) as tracknow_row_count
    from {{ ref('fct_tracknow_commission_daily') }} t
    where not exists (
        select 1
        from invoice_groups i
        where i.firm_id = t.firm_id
          and i.currency_code = t.currency_code
          and t.commission_date between i.period_start and i.period_end
    )
    group by 1, 4
)

select
    r.*,
    r.quickbooks_invoice_amount - r.tracknow_commission_amount as signed_delta,
    abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount) as absolute_delta,
    case when r.quickbooks_invoice_amount > 0
         then abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount)
              / r.quickbooks_invoice_amount
    end as pct_delta,
    case
        when r.currency_code <> 'GBP' then 'currency_mismatch'
        when r.mapping_match_count > 1 then 'ambiguous_firm_mapping'
        when r.mapping_match_count = 0 then 'unmapped_firm'
        when r.period_start is null or r.period_end is null then 'missing_period'
        when r.invoice_count is null then 'missing_quickbooks'
        when r.tracknow_row_count = 0 then 'missing_tracknow'
        when abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount)
             <= {{ var('reconciliation_tolerance_amount', 5) }}
          or abs(r.quickbooks_invoice_amount - r.tracknow_commission_amount)
             / nullif(r.quickbooks_invoice_amount, 0)
             <= {{ var('reconciliation_tolerance_pct', 0.01) }} then 'matched'
        else 'variance'
    end as reconciliation_status
from (
    select * from period_reconciled
    union all
    select * from unknown_period
    union all
    select * from uncovered_tracknow
) r
```

The join emits `missing_tracknow` when an explicit invoice period has no
operational TrackNow daily rows. Operational TrackNow rows not covered by any
explicit invoice billing period are retained via the source-coverage CTE
(`uncovered_tracknow`) as `missing_period` rather than silently disappearing or
fabricating an invoice month. A `missing_quickbooks` row is valid when an upstream
commission source supplies its own explicit billing period with no covering
invoice; the daily source described here does not, so uncovered daily rows
remain `missing_period`. This is a deliberate boundary of the design: the model
cannot infer an invoice period from a commission date.

The grouped row keeps an audit list or count of its contributing `invoice_id`
values. Finance can therefore trace the £1,000 aggregate back to two £500
invoices without changing the reconciliation grain.

The local per-conversion contract is also explicit. Operational TrackNow
commission is `referral_bonus_gbp` summed only for valid conversions;
`denied` conversions are excluded, while refunded conversions are retained
because no rule here says to reverse their commission. The authoritative
Google Sheet daily value is not allocated back to individual conversions, and
its daily adjustments remain at daily-source grain.

### 5.4 `mart_finance_reconciliation_alerts`

- **Grain:** one row per active reconciliation failure (every row of
  `int_quickbooks_tracknow_reconciliation` whose `reconciliation_status`
  is actionable - i.e. anything other than `matched`).
- **Fields:** `firm_id`, `firm_name`, `period_start`, `period_end`,
  `currency_code`, `invoice_count`, `quickbooks_invoice_amount`,
  `tracknow_commission_amount`, `signed_delta`, `absolute_delta`, `pct_delta`,
  `reconciliation_status`, `severity`,
  `detected_at`. The grouped invoice IDs remain available through the audit
  relation/count; the alert grain is never one row per invoice.
- **Notification:** a post-build step (Cloud Run Job step / orchestrator
  task) queries the mart and posts new/changed rows to Slack (or PagerDuty /
  email for high severity). The mart is the single output contract; the
  notifier holds no logic.

## 6. Reconciliation statuses

Evaluated in this order (first match wins):

| Status | Rule |
| --- | --- |
| `currency_mismatch` | Invoice currency is not GBP and no conversion contract is defined. |
| `ambiguous_firm_mapping` | More than one mapping row is effective for the invoice accounting date; the invoice amount is retained once and never fanned out. |
| `unmapped_firm` | `quickbooks_customer_id` has no row in `dim_firm_accounting_mapping`. |
| `missing_period` | Either side lacks a complete explicit billing period. No invoice month or commission month is invented. |
| `missing_tracknow` | `tracknow_row_count = 0` - explicit invoice period with no operational TrackNow daily rows (distinguishes no rows from rows summing to zero). |
| `missing_quickbooks` | Reserved for a commission source that supplies an explicit billing period with no covering invoice; a daily row without that period remains `missing_period`. |
| `matched` | `absolute_delta <= £5 OR pct_delta <= 1%` using the operational TrackNow daily amount (example tolerance - **to validate with Finance**, configured as dbt vars, never hard-coded). |
| `variance` | Difference above tolerance. |

## 7. Data quality checks per layer

| # | Layer | Check | Implementation |
| --- | --- | --- | --- |
| 1 | Airbyte / raw | Freshness | dbt source freshness on `raw_quickbooks.invoices` |
| 2 | Airbyte / raw | Invoice primary key not null | `not_null` on `invoice_id` |
| 3 | Airbyte / raw | Schema drift on critical fields | Airbyte schema-drift notification + dbt model contract |
| 4 | Staging | Invoice uniqueness | `unique` on `invoice_id` |
| 5 | Staging | Numeric/currency/period validity | `not_null`/accepted values on currency, amounts >= 0; complete dates required for `explicit` periods |
| 6 | Staging | Customer mapping coverage | Singular test: share of invoices with no mapping is reported (unmapped is an alert state, never a silent drop) |
| 7 | Reconciliation | Aggregate grain | Singular test: the reconciliation key is unique and invoice totals are summed before any daily commission join |
| 8 | Reconciliation | Mapping fanout | Singular test: no invoice has more than one effective mapping; ambiguous rows are retained once and classified |
| 9 | Reconciliation | Amount variance | Variance rows must satisfy the status rule (no `matched` row above tolerance); `signed_delta` is available for directional monitoring |
| 10 | Reconciliation | Missing side/period | Explicit invoice periods with no TrackNow rows are visible; rows without explicit periods are `missing_period`, with no fabricated month |
| 11 | Alert mart | Alert freshness | `detected_at` within one scheduled run of now |

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

I would run dbt only after the Airbyte sync completes successfully - a
scheduler dependency (Airbyte completion webhook, or the orchestrator task
that triggers both), never a fixed clock time, so dbt never reconciles
against a half-loaded raw table. Failures at any step block the notification
step, which reads only `mart_finance_reconciliation_alerts`.

## 9. Assumptions

1. QuickBooks line items or another source field provide complete billing
   periods. Where they do not, the period is unavailable and is classified as
   `missing_period`; Finance must define the contract before implementation.
2. GBP is the functional currency; any non-GBP invoice is
   `currency_mismatch` until Finance defines a conversion contract. Amounts
   are never compared across currency codes.
3. The `firm_id` ↔ `quickbooks_customer_id` mapping is maintained manually
   as a curated seed and reviewed by Finance; it is never derived from
   customer names. Effective ranges must not overlap for either key.
4. The tolerance (`£5` / `1%`) is an illustrative placeholder, explicitly to
   be validated with Finance, and configured via dbt vars.
5. The operational source is `fct_tracknow_commission_daily`; the
   authoritative Google Sheet daily source is `stg_commission_daily` and is
   not reconstructed from conversions. Its adjustments are not allocated to
   individual conversions.
6. Nothing in this design is implemented in this repository: there is no
   QuickBooks connection, Airbyte workspace, BigQuery dataset, or any of the
   dbt models above. The repo's only executable pipeline remains the local
   DuckDB sample (see the README).
