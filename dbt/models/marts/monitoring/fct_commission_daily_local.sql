{{ config(materialized='table') }}

-- Mart: local daily commission proxy.
-- Grain: one row per (conversion_date, firm_id).
--
-- This model is a LOCAL PROXY over the TrackNow sample only. It deliberately
-- is NOT named f_commission_daily: per the assignment schema, analytics_core
-- f_commission_daily is the authoritative daily-commission table sourced from
-- a Google Sheet that was NOT provided. This mart exists to demonstrate the
-- per-conversion pipeline (commission = referral_bonus_gbp) and must never be
-- presented as the authoritative source.
--
-- Population rule mirrors fct_revenue_attribution: only valid conversions
-- (staging is_valid_conversion = true, i.e. status <> 'denied' and status not
-- NULL/unknown). Refunded conversions are kept and their commission is counted
-- in the totals (no business rule was provided to exclude or reverse them).
-- These source-reported amounts are not confirmed net recognized commission.
--
-- Metrics:
--   conversion_count   number of valid conversions that day for the firm
--   commission_gbp     sum of referral_bonus_gbp over those conversions
--   sales_amount_gbp   sum of order price over those conversions

with revenue as (
    select
        conversion_id,
        conversion_date,
        firm_id,
        commission_gbp,
        order_price_gbp
    from {{ ref('stg_tracknow_checkouts') }}
    where is_valid_conversion
)

select
    conversion_date,
    firm_id,
    count(conversion_id) as conversion_count,
    sum(commission_gbp) as commission_gbp,
    sum(order_price_gbp) as sales_amount_gbp
from revenue
group by conversion_date, firm_id
