-- Singular data test: a NULL normalized status (blank/whitespace-only in the
-- raw source) must yield a NULL is_valid_conversion flag. The card's
-- expression is `status <> 'denied'` verbatim; under SQL three-valued logic a
-- NULL status makes the flag UNKNOWN, not false and not true. A row returned
-- here means the model collapsed the unknown case into a boolean default
-- (e.g. coalesce(..., false)), which would conflate 'no status' with 'denied'
-- and silently classify a data-quality anomaly as a known-invalid conversion.

select conversion_id, status, is_valid_conversion
from {{ ref('stg_tracknow_checkouts') }}
where status is null and is_valid_conversion is not null
