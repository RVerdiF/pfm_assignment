-- Staging model for TrackNow checkout orders.
-- Grain: one row per TrackNow conversion order (conversion_id).
-- Clean, stable interface over the raw TrackNow data. Attribution is NOT
-- performed in this layer. Denied orders are preserved for audit; the flag
-- is_valid_conversion identifies them without dropping the record.

with source as (
    select * from {{ source('raw', 'tracknow_checkouts') }}
),

normalized as (
    select
        -- String keys are trimmed so the cleaned interface never exposes keys
        -- with stray whitespace; values that are empty (or whitespace-only)
        -- after trimming become NULL. Case is preserved: click IDs may be
        -- case-sensitive and are never lowercased or otherwise altered beyond
        -- the surrounding-space trim.
        nullif(trim(tracknow_order_id), '') as conversion_id,
        created_date as conversion_date,
        tracknow_user_id,
        click_id,
        affiliate_session_id,
        firm_id,
        -- status is normalized once here; the flag below is derived from this
        -- exact value, so the invariant
        --   is_valid_conversion = (status <> 'denied')
        -- holds even for whitespace-padded inputs (e.g. ' denied ' normalizes
        -- to 'denied' and is therefore NOT valid, exactly like 'denied').
        nullif(trim(status), '') as status,
        order_price_gbp,
        referral_bonus_gbp as commission_gbp,
        coupon_used,
        trading_platform,
        first_order,
        account_size
    from source
),

flagged as (
    -- A NULL status (after normalization) is treated as not denied by the
    -- standard SQL three-valued logic; coalesce keeps the flag strictly
    -- boolean (NULL <> 'denied' -> NULL would otherwise flow through).
    select
        *,
        coalesce(status <> 'denied', false) as is_valid_conversion
    from normalized
),

cleaned as (
    select
        conversion_id,
        -- date and monetary/flag columns already arrive typed from the raw
        -- loader; explicit casts keep the contract stable and readable.
        cast(conversion_date as date) as conversion_date,
        nullif(trim(tracknow_user_id), '') as tracknow_user_id,
        nullif(trim(click_id), '') as click_id,
        nullif(trim(affiliate_session_id), '') as affiliate_session_id,
        nullif(trim(firm_id), '') as firm_id,
        status,
        cast(order_price_gbp as double) as order_price_gbp,
        cast(commission_gbp as double) as commission_gbp,
        nullif(trim(coupon_used), '') as coupon_used,
        nullif(trim(trading_platform), '') as trading_platform,
        cast(first_order as boolean) as first_order,
        cast(account_size as bigint) as account_size,
        is_valid_conversion
    from flagged
)

select * from cleaned
