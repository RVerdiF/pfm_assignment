-- Singular data test: commissions must never be negative.
-- The raw sample data confirms this rule (min referral_bonus_gbp = 0.0), so we
-- enforce it on the staging model. A failing row would indicate bad source data.

select conversion_id, commission_gbp
from {{ ref('stg_tracknow_checkouts') }}
where commission_gbp < 0
