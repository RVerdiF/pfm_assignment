-- BigQuery anomaly-detection query over the authoritative production commission
-- table. Replace `project_id` with the target GCP project before execution.
--
-- Source: `analytics_core.f_commission_daily`
-- Grain:  one row per (commission_date, firm_id).
--
-- Business rules (Area 1 — Attribution & Data Modeling):
--   * For each firm-day in the last 30 days produce:
--       commission_today      the day's commission amount
--       commission_7d_avg     rolling 7-day average of the PREVIOUS 7 rows
--                             (current row excluded)
--       pct_change_vs_7d_avg  (commission_today - commission_7d_avg) /
--                             commission_7d_avg  (SAFE_DIVIDE)
--       flag                  'anomaly' when ABS(pct_change) > 40%, else
--                             'normal' (normal rows are filtered out below)
--   * Only anomalies are returned.
--   * Results are ordered by absolute revenue impact descending.
--
-- Implementation notes
-- --------------------
-- Window frame: ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
--   This considers up to 7 *records* preceding the current row, not 7
--   calendar days. If a firm has gaps (missing days), the window still
--   counts 7 rows; this is a deliberate simplification. A production-grade
--   solution would use a date spine per firm to handle calendar-day gaps
--   explicitly — but it would NOT assume a missing day is a zero-commission
--   day.
--
-- Baseline = zero:
--   SAFE_DIVIDE returns NULL (not a division-by-zero error) when the 7-day
--   average is zero. A row whose baseline is zero is therefore dropped from
--   the anomaly set rather than flagged as an anomaly. If the business
--   decides that a zero baseline with commission_today > 0 IS itself an
--   anomaly, that rule has to be added explicitly — it is not encoded
--   here by default because a zero baseline can mean a firm that was
--   inactive, not a broken-commission situation.
--
-- Read window:
--   The rolling average for the earliest day in the 30-day reporting
--   window needs the 7 days before it, so the source scan reads the last
--   37 days. The scored CTE trims the output back to the last 30 days.

with daily as (
    select
        commission_date,
        firm_id,
        firm_name,
        commission_amount
    from `project_id.analytics_core.f_commission_daily`
    where commission_date >= date_sub(current_date(), interval 37 day)
),

with_baseline as (
    select
        commission_date,
        firm_id,
        firm_name,
        commission_amount as commission_today,
        avg(commission_amount) over (
            partition by firm_id
            order by commission_date
            rows between 7 preceding and 1 preceding
        ) as commission_7d_avg
    from daily
),

scored as (
    select
        *,
        safe_divide(
            commission_today - commission_7d_avg,
            commission_7d_avg
        ) as pct_change_vs_7d_avg,
        abs(commission_today - commission_7d_avg) as absolute_revenue_impact
    from with_baseline
    where commission_date >= date_sub(current_date(), interval 30 day)
)

select
    commission_date,
    firm_id,
    firm_name,
    commission_today,
    commission_7d_avg,
    pct_change_vs_7d_avg,
    'anomaly' as flag
from scored
where abs(pct_change_vs_7d_avg) > 0.40
order by absolute_revenue_impact desc;
