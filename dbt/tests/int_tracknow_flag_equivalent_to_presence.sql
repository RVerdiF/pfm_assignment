-- Singular data test: the presence flags on the TrackNow candidates model must
-- be exactly equivalent to their source identifier being non-null. A flag that
-- is true while the identifier is null (or vice versa) means the model is
-- misreporting which links are possible and would mislead downstream matching.

select conversion_id, click_id, has_click_id
from {{ ref('int_tracknow_attribution_candidates') }}
where (click_id is not null) is distinct from has_click_id

union all

select conversion_id, affiliate_session_id, has_affiliate_session_id
from {{ ref('int_tracknow_attribution_candidates') }}
where (affiliate_session_id is not null) is distinct from has_affiliate_session_id

union all

select conversion_id, tracknow_user_id, has_tracknow_user_id
from {{ ref('int_tracknow_attribution_candidates') }}
where (tracknow_user_id is not null) is distinct from has_tracknow_user_id
