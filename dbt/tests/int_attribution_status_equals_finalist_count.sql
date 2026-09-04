-- Singular data test: attribution status must be exactly determined by the
-- number of finalist sessions. Every 'matched' row must have exactly one
-- finalist (one eligible session surviving the priority+recency ordering) and
-- every 'ambiguous' row must have at least two. This pins the semantic
-- contract of the status derivation and makes the decision auditable.

with finalist_counts as (
    -- Re-derive finalist count per conversion directly from the raw match
    -- universe with the same rules (window + priority + recency tie),
    -- enriched from the staged session table exactly like the model does.
    select
        conversion_id,
        count(*) as n_finalists
    from (
        select
            m.conversion_id,
            m.session_id,
            m.session_date,
            m.session_start_at,
            m.identifier_priority,
            rank() over (
                partition by m.conversion_id
                order by m.identifier_priority asc, m.session_start_at desc nulls last
            ) as match_rank
        from (
            -- eligible sessions (exact click match within the date window)
            select
                cv.conversion_id,
                cs.session_id,
                s.session_date,
                s.session_start_at,
                min(case when cs.identifier_type in ('gclid', 'fbclid') then 0 else 1 end) as identifier_priority
            from {{ ref('int_tracknow_attribution_candidates') }} as cv
            join {{ ref('int_posthog_attribution_candidates') }} as cs
                on cv.click_id = cs.identifier_value
            left join {{ ref('stg_posthog_sessions') }} as s
                on cs.session_id = s.session_id
            where cv.has_click_id
              and s.session_date is not null
              and s.session_date <= cv.conversion_date
            group by cv.conversion_id, cs.session_id, s.session_date, s.session_start_at
        ) as m
    ) as ranked
    where match_rank = 1
    group by conversion_id
)

select a.conversion_id
from {{ ref('int_conversion_attribution') }} as a
left join finalist_counts as f
    on a.conversion_id = f.conversion_id
where (a.attribution_status = 'matched' and coalesce(f.n_finalists, 0) <> 1)
   or (a.attribution_status = 'ambiguous' and coalesce(f.n_finalists, 0) < 2)
   or (a.attribution_status = 'unmatched' and coalesce(f.n_finalists, 0) > 0)
