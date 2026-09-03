-- Singular data test: fct_commission_daily_local must be unique at its
-- declared grain (conversion_date, firm_id) and its aggregates must reconcile
-- to the per-conversion revenue population (valid conversions only).
--
-- Enforced contracts:
--   1. Grain uniqueness: at most one row per (conversion_date, firm_id).
--   2. Aggregation reconciliation against stg_tracknow_checkouts restricted
--      to is_valid_conversion = true (the same population the model groups):
--        conversion_count = count of valid conversions per (date, firm)
--        commission_gbp   = sum of commission_gbp over that group
--        sales_amount_gbp = sum of order_price_gbp over that group
--      Values are compared with tolerance for floating-point sum order.
--      Any denied conversion counted, any valid conversion dropped, or any
--      wrong metric aggregation fails here.

with mart as (
    select conversion_date, firm_id, conversion_count, commission_gbp, sales_amount_gbp
    from {{ ref('fct_commission_daily_local') }}
),
expected as (
    select
        conversion_date,
        firm_id,
        count(conversion_id) as conversion_count,
        sum(commission_gbp) as commission_gbp,
        sum(order_price_gbp) as sales_amount_gbp
    from {{ ref('stg_tracknow_checkouts') }}
    where is_valid_conversion
    group by conversion_date, firm_id
)

-- 1. duplicated grain
select 'duplicate (conversion_date, firm_id)' as check_name, conversion_date, firm_id::varchar as detail
from mart
group by conversion_date, firm_id
having count(*) > 1

union all

-- 2a. mart group with no matching expected group (denied counted / fabricated)
select 'mart group not in expected population' as check_name, m.conversion_date, m.firm_id::varchar as detail
from mart as m
left join expected as e
    on m.conversion_date = e.conversion_date
    and m.firm_id = e.firm_id
where e.conversion_date is null

union all

-- 2b. expected group missing from mart (valid conversions dropped)
select 'expected group missing from mart' as check_name, e.conversion_date, e.firm_id::varchar as detail
from expected as e
left join mart as m
    on e.conversion_date = m.conversion_date
    and e.firm_id = m.firm_id
where m.conversion_date is null

union all

-- 2c. metric mismatches (row exists in both sides)
select 'metric mismatch' as check_name, m.conversion_date, m.firm_id::varchar as detail
from mart as m
join expected as e
    on m.conversion_date = e.conversion_date
    and m.firm_id = e.firm_id
where m.conversion_count <> e.conversion_count
   or abs(m.commission_gbp - e.commission_gbp) > 1e-6
   or abs(m.sales_amount_gbp - e.sales_amount_gbp) > 1e-6
