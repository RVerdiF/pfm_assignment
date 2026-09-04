-- Singular data test: only rows with a non-null click_id can be matched or
-- ambiguous. A conversion without a click_id cannot equal any PostHog
-- identifier value (matching is exact equality only), so it must be reported
-- 'unmatched'. No bridge (affiliate_session_id = session_id,
-- tracknow_user_id = distinct_id) is ever inferred here.

select conversion_id
from {{ ref('int_conversion_attribution') }}
where has_click_id = false
  and attribution_status in ('matched', 'ambiguous')
