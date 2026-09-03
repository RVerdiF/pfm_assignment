-- Singular data test: the TrackNow candidates model must emit exactly one row
-- per conversion. This is the card's grain contract: no fan-out is introduced
-- when preparing candidates (flag columns do not multiply rows).

select conversion_id
from {{ ref('int_tracknow_attribution_candidates') }}
group by conversion_id
having count(*) <> 1
