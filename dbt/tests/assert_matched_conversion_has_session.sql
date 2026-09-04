-- Singular data test: a matched conversion must reference the session that
-- attribution chose, and a conversion that carries an attributed session must
-- be reported 'matched'. Enforced on fct_revenue_attribution, the revenue
-- consumption mart, where the decision columns are renamed from the
-- attribution layer:
--   match_status       = int_conversion_attribution.attribution_status
--   matched_session_id = int_conversion_attribution.attribution_session_id
--
-- The attribution engine populates attribution_session_id only for 'matched'
-- decisions, so a revenue row that violates either direction signals a broken
-- grain or an invented join in the mart (or its upstream): a matched
-- conversion would silently lose the session that explains its revenue, or a
-- non-matched conversion would carry a session attribution never chose -
-- which would mis-credit revenue to a channel/session. Both directions are
-- guarded here.

with revenue as (
    select conversion_id, match_status, matched_session_id
    from {{ ref('fct_revenue_attribution') }}
)

-- 1. matched conversions must carry the attributed session
select 'matched without session' as check_name, conversion_id
from revenue
where match_status = 'matched' and matched_session_id is null

union all

-- 2. no conversion outside 'matched' may fabricate an attributed session
select 'session on non-matched conversion' as check_name, conversion_id
from revenue
where matched_session_id is not null and match_status <> 'matched'
