-- Singular data test: the cleaned interface must keep the invariant
--   is_valid_conversion = (status <> 'denied')
-- for every published row. Because the model derives the flag from the same
-- normalized status it publishes, this holds regardless of whether the raw
-- status arrived whitespace-padded (' denied ') or NULL (treated as not
-- denied via coalesce). A failing row indicates a regression that computes the
-- flag from a different (untrimmed) status than the one it publishes.

select conversion_id, status, is_valid_conversion
from {{ ref('stg_tracknow_checkouts') }}
where coalesce(status <> 'denied', false) <> is_valid_conversion
