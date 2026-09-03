-- Singular data test: the cleaned interface must publish the card's flag
-- expression verbatim for every row:
--   is_valid_conversion = (status <> 'denied')
-- evaluated on the NORMALIZED status the model publishes. IS DISTINCT FROM
-- makes the comparison NULL-aware: a row whose flag was coalesced to a boolean
-- default when status is NULL (e.g. coalesce(status <> 'denied', false))
-- differs from the nullable expression and fails here. This also catches any
-- regression that computes the flag from a different (untrimmed) status than
-- the one it publishes (e.g. whitespace-padded ' denied ' -> published
-- 'denied' with flag true).

select conversion_id, status, is_valid_conversion
from {{ ref('stg_tracknow_checkouts') }}
where (status <> 'denied') is distinct from is_valid_conversion
