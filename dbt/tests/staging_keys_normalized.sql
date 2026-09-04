-- Singular data test: declared string grain keys must never be published with
-- surrounding whitespace. The staging models normalize keys with
-- trim + empty-string-to-NULL, so a padded value here means a regression in
-- that normalization. Blank/whitespace-only values normalize to NULL and are
-- caught by the not_null schema tests on the same keys.

select conversion_id as key_value
from {{ ref('stg_tracknow_checkouts') }}
where conversion_id is not null and conversion_id <> trim(conversion_id)

union all

select session_id as key_value
from {{ ref('stg_posthog_sessions') }}
where session_id is not null and session_id <> trim(session_id)
