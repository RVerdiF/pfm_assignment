-- Singular data test: every matched_session_id referenced by the revenue mart
-- must exist in the staged PostHog sessions table. The mart's matched session
-- is attribution's chosen session, which must always resolve to a real
-- session; a dangling reference would mean the revenue row points at a session
-- that never existed (broken provenance for the UTM/channel context) or that
-- the mart joined to a non-session source.

select f.conversion_id, f.matched_session_id
from {{ ref('fct_revenue_attribution') }} as f
left join {{ ref('stg_posthog_sessions') }} as s
    on f.matched_session_id = s.session_id
where f.matched_session_id is not null
  and s.session_id is null
