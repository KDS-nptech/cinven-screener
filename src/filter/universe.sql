-- Stage 2: size-and-age filter.
--
-- Executed by src/filter/universe.py, which registers two views before running
-- this file:
--   software_companies  active software-SIC companies (Stage 1a)
--   accounts_wide       one row per filed period (Stage 1b)
-- and binds the named parameters below from config.yaml (block `target`):
--   $employees_min, $employees_max           integers
--   $incorporated_on_or_before              ISO date string
--   $exclude_account_categories             list of upper-case strings
--   $software_sic                           list of target SIC codes (informational flag only)
--   $computed_at                            UTC ISO timestamp
--
-- Output: one row per software company, whether or not it passes, with the
-- latest accounts row joined on and one boolean per rule. exclusion_reason is
-- the first failing rule in the order size, age, category, or NULL.

WITH latest AS (
    SELECT
        company_number,
        TRY_CAST(period_end AS DATE)                 AS latest_period_end,
        TRY_CAST(employees AS BIGINT)                AS latest_employees,
        TRY_CAST(turnover AS DOUBLE)                 AS latest_turnover,
        TRY_CAST(share_premium AS DOUBLE)            AS latest_share_premium,
        TRY_CAST(share_capital AS DOUBLE)            AS latest_share_capital,
        accounts_type                                AS latest_accounts_type
    FROM accounts_wide
    -- latest_for_company is the Stage 1b marker; period_end breaks any tie so
    -- exactly one row survives per company even if the marker is duplicated.
    QUALIFY row_number() OVER (
        PARTITION BY company_number
        ORDER BY COALESCE(latest_for_company, FALSE) DESC, TRY_CAST(period_end AS DATE) DESC NULLS LAST
    ) = 1
),
joined AS (
    SELECT
        c.company_number,
        c.name,
        c.status,
        c.inc_date,
        c.account_category,
        c.post_town,
        c.postcode,
        c.sic1, c.sic2, c.sic3, c.sic4,
        c.is_software_sic,
        -- is_software_sic matches any of the four SIC slots; this flag says whether the
        -- primary code is a software code. Informational, not a filter (see open-questions).
        COALESCE(list_contains($software_sic, CAST(c.sic1 AS VARCHAR)), FALSE)
                                                     AS software_sic_primary,
        c.charges_outstanding,
        l.latest_period_end,
        l.latest_employees,
        l.latest_turnover,
        l.latest_share_premium,
        l.latest_share_capital,
        l.latest_accounts_type,
        l.company_number IS NOT NULL                 AS has_accounts
    FROM software_companies c
    LEFT JOIN latest l USING (company_number)
),
rules AS (
    SELECT
        *,
        -- Provisional: a FULL, GROUP or MEDIUM filer with no parsed accounts yet (its PDF is
        -- queued for OCR). These categories cannot be small companies, so the company is very
        -- likely inside or above the band; it is carried as `size_unverified` until OCR lands.
        (NOT has_accounts OR latest_employees IS NULL) AND upper(trim(account_category)) IN ('FULL', 'GROUP', 'MEDIUM')
                                                     AS provisional,
        -- Rule S: headcount inside the target band. NULL employees fail unless provisional.
        COALESCE(latest_employees BETWEEN $employees_min AND $employees_max, FALSE)
            OR ((NOT has_accounts OR latest_employees IS NULL) AND upper(trim(account_category)) IN ('FULL', 'GROUP', 'MEDIUM'))
                                                     AS passes_size,
        -- Rule A: incorporated on or before the cut-off. NULL inc_date fails.
        COALESCE(inc_date <= CAST($incorporated_on_or_before AS DATE), FALSE)
                                                     AS passes_age,
        -- Rule C: account category not in the excluded list. NULL category passes
        -- (the category is a filing label, absence is not evidence of size).
        NOT COALESCE(list_contains($exclude_account_categories, upper(trim(account_category))), FALSE)
                                                     AS passes_category
    FROM joined
)
SELECT
    *,
    passes_size AND passes_age AND passes_category   AS passes_all,
    CASE
        WHEN provisional AND passes_age AND passes_category THEN NULL
        WHEN NOT has_accounts                        THEN 'no_accounts'
        WHEN latest_employees IS NULL                THEN 'employees_missing'
        WHEN latest_employees < $employees_min       THEN 'employees_below_min'
        WHEN latest_employees > $employees_max       THEN 'employees_above_max'
        WHEN inc_date IS NULL                        THEN 'inc_date_missing'
        WHEN NOT passes_age                          THEN 'incorporated_too_recently'
        WHEN NOT passes_category                     THEN 'account_category_excluded'
        ELSE NULL
    END                                              AS exclusion_reason,
    $computed_at                                     AS computed_at
FROM rules
ORDER BY company_number
