-- Singular data test: every conversion must appear exactly once (grain is
-- conversion_id) and every attribution_status must be one of the declared
-- values. This pins the acceptance criterion
--   count(distinct conversion_id) = count(*)
-- directly on the model output.

select conversion_id
from {{ ref('int_conversion_attribution') }}
group by conversion_id
having count(*) > 1

union all

select conversion_id
from {{ ref('int_conversion_attribution') }}
where attribution_status not in ('matched', 'ambiguous', 'unmatched')
