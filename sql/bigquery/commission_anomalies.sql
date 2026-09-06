-- BigQuery Standard SQL: Commission Anomaly Detection (Area 1, Question 3)
-- Replace `project_id` with your GCP project ID before execution.
--
-- Contract:
--   Source: analytics_core.f_commission_daily (authoritative production relation)
--   Fields: commission_date, firm_id, commission_amount
--   Grain:  one row per (commission_date, firm_id)
--
-- Purpose:
--   For each firm_id and day in the last 30 days, compare today's commission against
--   its trailing 7-day average (excluding the current day). Classify rows as 'anomaly'
--   when the absolute percentage swing exceeds 40% (|pct_change| > 0.40), otherwise 'normal'.
--
-- Edge cases & date arithmetic handled:
--   1. Calendar-day window: Uses `ORDER BY UNIX_DATE(commission_date) RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING`
--      rather than a naive `ROWS BETWEEN` frame. At the declared daily grain, counting seven
--      non-null values in this frame proves that all seven preceding calendar days are usable.
--   2. Current day exclusion: The upper window boundary `1 PRECEDING` ensures today's commission
--      does not contaminate its own baseline.
--   3. Zero baseline / missing history: A baseline is usable only when all seven preceding
--      calendar days have non-null amounts. `SAFE_DIVIDE` protects against a zero average;
--      either case is marked 'unavailable', rather than being treated as 'normal'.
--   4. Strictly 30-day reporting extent: Evaluates `INTERVAL 29 DAY` lookback from CURRENT_DATE
--      (exactly 30 discrete dates: [CURRENT_DATE - 29, CURRENT_DATE]).
--   5. Origin scan: Scans 36 days lookback (`INTERVAL 36 DAY`, spanning 37 discrete dates)
--      from the source so the earliest evaluated day (CURRENT_DATE - 29) has its complete
--      7 preceding calendar days [CURRENT_DATE - 36, CURRENT_DATE - 30] available.

WITH daily_source AS (
    SELECT
        commission_date,
        firm_id,
        commission_amount
    FROM `project_id.analytics_core.f_commission_daily`
    WHERE commission_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 36 DAY) AND CURRENT_DATE()
),

with_baseline AS (
    SELECT
        commission_date,
        firm_id,
        commission_amount AS commission_today,
        AVG(commission_amount) OVER (
            PARTITION BY firm_id
            ORDER BY UNIX_DATE(commission_date)
            RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS commission_7d_avg,
        COUNT(commission_amount) OVER (
            PARTITION BY firm_id
            ORDER BY UNIX_DATE(commission_date)
            RANGE BETWEEN 7 PRECEDING AND 1 PRECEDING
        ) AS prior7_nonnull_days
    FROM daily_source
),

scored AS (
    SELECT
        commission_date,
        firm_id,
        commission_today,
        commission_7d_avg,
        SAFE_DIVIDE(
            commission_today - commission_7d_avg,
            commission_7d_avg
        ) AS raw_pct_change_vs_7d_avg,
        prior7_nonnull_days
    FROM with_baseline
    WHERE commission_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 29 DAY)
),

classified AS (
    SELECT
        commission_date,
        firm_id,
        commission_today,
        commission_7d_avg,
        CASE
            WHEN prior7_nonnull_days = 7 THEN raw_pct_change_vs_7d_avg
        END AS pct_change_vs_7d_avg,
        CASE
            WHEN prior7_nonnull_days = 7 THEN ABS(commission_today - commission_7d_avg)
        END AS absolute_revenue_impact,
        CASE
            WHEN prior7_nonnull_days <> 7 OR raw_pct_change_vs_7d_avg IS NULL
                THEN 'unavailable'
            WHEN ABS(raw_pct_change_vs_7d_avg) > 0.40
                THEN 'anomaly'
            ELSE 'normal'
        END AS anomaly
    FROM scored
)

SELECT
    commission_date,
    firm_id,
    commission_today,
    commission_7d_avg,
    pct_change_vs_7d_avg,
    absolute_revenue_impact,
    anomaly
FROM classified
WHERE anomaly = 'anomaly'
ORDER BY absolute_revenue_impact DESC;
