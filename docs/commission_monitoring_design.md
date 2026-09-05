# Commission pipeline — data quality monitoring design

**Scope: design only.** Nothing in this document is provisioned or implemented
in this repository: there is no Airbyte connection, no BigQuery deployment, no
dbt Cloud job, and no alerting infrastructure. This is the monitoring answer to
**Area 2 (Investigation, Integration & Monitoring)** of the assignment,
complementing `docs/quickbooks_reconciliation_design.md` (the integration and
reconciliation design) and the investigation narrative on the Streamlit
"Investigation & monitoring" page of the same area.

The design assumes the production stack described in the README: the official
commission source lands in BigQuery raw (via the commission integration), dbt
builds the staging / intermediate / marts layers, and
`mart_attribution_health` plus the reconciliation output are the published
relations the checks below read.

---

## The five checks

Exactly five checks cover the commission pipeline. Each check names what it
validates, its metric, its threshold, its severity, its implementation, and
how on-call is notified.

### Check 1 — Commission source freshness

| | |
|---|---|
| **What it validates** | The official commission source arrived within SLA. |
| **Metric** | `max(commission_date)` and/or the ingestion timestamp of the commission raw table, compared to the expected delivery calendar. |
| **Threshold (example, configurable)** | **P1**: no new data by 10:00 UTC on the expected delivery day (daily financial reporting is unavailable). **P2**: arrival more than 2h later than the SLA, before the critical cutoff. |
| **Severity** | **P1** when the daily financial reporting is unavailable; P2 for partial delays inside the buffer window. |
| **Implementation** | dbt source freshness on the commission source, or a scheduled query over a pipeline metadata/ingestion-timestamp table; alert when freshness exceeds the threshold. |
| **On-call action** | Verify the commission integration sync, the source itself, the BigQuery load, and the last dbt run — in that order. |

### Check 2 — Duplicate / invalid TrackNow conversions

| | |
|---|---|
| **What it validates** | The grain of the conversion table: one row per conversion, primary conversion identifier present, statuses within the known set. |
| **Metric** | Count of duplicate `tracknow_order_id`; count of null conversion IDs; count of statuses outside the accepted set. |
| **Threshold** | Any duplicate ID > 0 → alert. Any null conversion ID > 0 → alert. Any invalid status > 0 → alert. |
| **Severity** | **P1** — duplicates can double-count revenue and commission, and silently overstate both. |
| **Implementation** | dbt tests: `unique` and `not_null` on `tracknow_order_id`, `accepted_values` on status, plus a singular test asserting the business grain. |
| **On-call action** | The mart publication is blocked or the run is marked failed; on-call decides whether to quarantine the batch and re-run ingestion. |

### Check 3 — Attribution unmatched-rate regression

| | |
|---|---|
| **What it validates** | Attribution quality has not regressed: conversions keep joining to tracking sessions at the expected rate. |
| **Metric** | `unmatched_rate = unmatched_conversions / total_conversions`, from `mart_attribution_health`. |
| **Threshold** | **P2** if the unmatched rate exceeds 25%, or rises more than 5 percentage points above the trailing 7-day baseline. The ~18% figure reported by the assignment is the observed production gap, **not** a hardcoded SLA — the baseline is computed from recent history, and thresholds are configuration. |
| **Severity** | **P2** by default. Escalates to **P1** if the unmatched rate exceeds 40% (hard ceiling) or reporting for a critical channel goes dark. |
| **Implementation** | Scheduled query over `mart_attribution_health` in production. Broken down by: total, channel, firm, and device/browser where available. |
| **On-call action** | Compare the rate against the baseline, check whether a specific channel or identifier source regressed, and hand off to the tracking/integration owner if the capture side broke. |

### Check 4 — Commission reconciliation variance

| | |
|---|---|
| **What it validates** | QuickBooks invoices and TrackNow-derived commission agree within materiality. |
| **Metric** | `absolute_delta` and `pct_delta` per `firm_id` and reconciliation period, from `int_quickbooks_tracknow_reconciliation`. |
| **Threshold (example, configurable)** | **P1**: absolute delta > £500. **P2**: pct delta > 5% **and** absolute delta > £50. **P3**: same sign delta for 3+ consecutive periods (regardless of materiality). |
| **Severity** | **P1/P2/P3** by materiality, as above. |
| **Implementation** | Monitoring query over `int_quickbooks_tracknow_reconciliation` (output of the reconciliation design in `docs/quickbooks_reconciliation_design.md`). |
| **On-call action** | The alert carries firm, period, both values, and both deltas, with a link to the reconciliation query for investigation; finance is notified for P1/P2. |

### Check 5 — Firm / accounting mapping coverage

| | |
|---|---|
| **What it validates** | Every QuickBooks invoice/customer resolves to a `firm_id` via the `dim_firm_accounting_mapping` bridge. |
| **Metric** | `unmapped_invoices / total_invoices` from the reconciliation output. |
| **Threshold** | Any new unmapped invoice → **P2**. More than 1% unmapped → **P1** if reconciliation is blocked. |
| **Severity** | **P2** by default; P1 only when reconciliation cannot close. |
| **Implementation** | dbt test / monitoring query over `dim_firm_accounting_mapping` and the reconciliation output (left-anti join for unmapped keys). |
| **On-call action** | Add the missing mapping (the bridge is customer-id → `firm_id`, never a name join), then re-run reconciliation. |

### Which check to build first — and why

**Check 1 (Commission source freshness) first.**

- If the source data has not arrived, every downstream check is unreliable —
  freshness is the precondition for the other four.
- It is simple to implement (one freshness query on one relation).
- It detects failure early, cutting time-to-diagnosis.
- It protects both reporting and reconciliation before anything else exists.

> Immediately after freshness, I would implement uniqueness/grain checks
> (Check 2) because duplicate financial rows can silently overstate revenue.

---

## Alerting / on-call

```text
data source / pipeline
    ↓
dbt build + monitoring queries
    ↓
monitoring table
    ↓
threshold evaluation
    ↓
notification
```

### Notification channels (proposed)

> In production I would route P1 to the on-call paging system and P2/P3 to a
> dedicated data-alerts Slack channel, with Finance copied on
> reconciliation-specific issues.

- **P1** → pager (PagerDuty/Opsgenie or equivalent): interrupts a human, 24/7.
- **P2/P3** → dedicated `data-alerts` Slack channel (P3 optionally in a daily
  digest).
- **Finance** copied on reconciliation-specific issues (Checks 4 and 5).
  These tool names are illustrative of the routing policy; the assignment
  does not state which tools the company uses.

### Alert payload

Every alert carries enough context to start diagnosis without re-deriving it:

```text
check_name
severity
detected_at
affected_date/period
firm_id (if applicable)
observed_value
threshold
query/model
run_id
suggested first action
```

---

## Monitoring architecture

```text
Airbyte / source loads
        ↓
BigQuery raw
        ↓
dbt tests + monitoring models
        ↓
monitoring mart
        ↓
scheduled evaluation
        ↓
Slack / paging
```

Implementation options, in the order I would reach for them: dbt tests and
dbt source freshness (run inside the existing dbt job), scheduled queries or
a dedicated monitoring model evaluated by the scheduler (Cloud Run job /
dbt Cloud job), and the platform's alerting surface (Cloud Monitoring or an
observability platform of choice). Nothing here is provisioned; the local
repository already exercises the equivalent contract with dbt tests and the
`mart_attribution_health` mart.
