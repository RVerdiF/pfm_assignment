-- Singular data test: fct_revenue_attribution must carry the staging values
-- through unchanged - commission_gbp is the per-order referral_bonus_gbp (the
-- Data Dictionary's correct PFM commission metric) and never re-derived or
-- zeroed; conversion_date and firm_id are the same clean values the mart's
-- grain is built on. A mart that recomputes commission (e.g. from a different
-- column), swaps firm assignment, or mutates the conversion date fails here.

select 'value mismatch' as check_name, m.conversion_id
from {{ ref('fct_revenue_attribution') }} as m
join {{ ref('stg_tracknow_checkouts') }} as s
    on m.conversion_id = s.conversion_id
where abs(m.commission_gbp - s.commission_gbp) > 1e-6
   or m.firm_id is distinct from s.firm_id
   or m.conversion_date is distinct from s.conversion_date
