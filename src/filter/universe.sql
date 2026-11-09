-- Stage 2: size filter for the buyout universe.
--
-- Executed by src/filter/universe.py, which registers two views before running this file:
--   candidate_companies  Active companies whose last accounts were FULL, GROUP or MEDIUM (Stage 1a)
--   accounts_wide        one row per filed period, consolidated figures preferred (Stage 1b)
-- and binds the named parameters below from config.yaml (block `target`):
--   $universe_turnover_min_gbp, $universe_employees_min, $universe_employees_max
--   $rank_turnover_min_gbp, $ebitda_early_floor_gbp
--   $exclude_account_categories, $exclude_sic
--   $computed_at
--
-- Output: one row per candidate company, whether or not it passes, with the latest accounts row
-- joined on, the prior period for growth, an EBITDA proxy, one boolean per rule and
-- exclusion_reason (first failing rule) or NULL. A FULL or GROUP filer with no parsed accounts is
-- `provisional`: it cannot be a small company, so it is carried as size-unverified until the
-- document API read lands (src/ingest/accounts_api.py).

WITH fixed AS (
    SELECT
        *,
        -- Filer error seen in the register: scale="3" applied to a head count (9,348,000 staff).
        CASE WHEN employees > 50000 AND employees % 1000 = 0 THEN employees / 1000 ELSE employees END AS employees_fixed,
        employees > 50000 AND employees % 1000 = 0                                              AS employees_scale_fixed
    FROM accounts_wide
),
ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY company_number
            ORDER BY comparative ASC, TRY_CAST(period_end AS DATE) DESC NULLS LAST,
                     COALESCE(consolidated, FALSE) DESC
        ) AS rn
    FROM fixed
    WHERE TRY_CAST(period_end AS DATE) IS NOT NULL
),
latest AS (
    SELECT
        company_number,
        TRY_CAST(period_end AS DATE)                 AS latest_period_end,
        TRY_CAST(period_start AS DATE)               AS latest_period_start,
        period_days                                  AS latest_period_days,
        TRY_CAST(employees_fixed AS BIGINT)          AS latest_employees,
        employees_scale_fixed,
        TRY_CAST(turnover AS DOUBLE)                 AS latest_turnover,
        TRY_CAST(gross_profit AS DOUBLE)             AS latest_gross_profit,
        TRY_CAST(operating_profit AS DOUBLE)         AS latest_operating_profit,
        TRY_CAST(pbt AS DOUBLE)                      AS latest_pbt,
        TRY_CAST(profit AS DOUBLE)                   AS latest_profit,
        TRY_CAST(depreciation AS DOUBLE)             AS latest_depreciation,
        TRY_CAST(amortisation AS DOUBLE)             AS latest_amortisation,
        TRY_CAST(interest_payable AS DOUBLE)         AS latest_interest_payable,
        TRY_CAST(staff_costs AS DOUBLE)              AS latest_staff_costs,
        TRY_CAST(dividends AS DOUBLE)                AS latest_dividends,
        TRY_CAST(net_assets AS DOUBLE)               AS latest_net_assets,
        TRY_CAST(cash AS DOUBLE)                     AS latest_cash,
        TRY_CAST(bank_borrowings AS DOUBLE)          AS latest_bank_borrowings,
        TRY_CAST(creditors_after_one_year AS DOUBLE) AS latest_creditors_after_one_year,
        TRY_CAST(creditors_within_one_year AS DOUBLE) AS latest_creditors_within_one_year,
        TRY_CAST(intangible_assets AS DOUBLE)        AS latest_intangible_assets,
        TRY_CAST(amounts_owed_to_group AS DOUBLE)    AS latest_amounts_owed_to_group,
        TRY_CAST(net_cash_from_ops AS DOUBLE)        AS latest_net_cash_from_ops,
        TRY_CAST(share_premium AS DOUBLE)            AS latest_share_premium,
        TRY_CAST(share_capital AS DOUBLE)            AS latest_share_capital,
        COALESCE(consolidated, FALSE)                AS latest_consolidated,
        pl_exempt                                    AS latest_pl_exempt,
        accounts_type                                AS latest_accounts_type,
        accounting_standard                          AS latest_accounting_standard,
        entity_name                                  AS latest_entity_name,
        source_file                                  AS latest_source_file
    FROM ranked
    WHERE rn = 1
),
prior AS (
    -- the period immediately before the latest one, for growth
    SELECT r.company_number,
           TRY_CAST(r.period_end AS DATE)     AS prior_period_end,
           TRY_CAST(r.employees_fixed AS BIGINT) AS prior_employees,
           TRY_CAST(r.turnover AS DOUBLE)     AS prior_turnover,
           TRY_CAST(r.operating_profit AS DOUBLE) AS prior_operating_profit
    FROM fixed r
    JOIN latest l ON l.company_number = r.company_number
    WHERE TRY_CAST(r.period_end AS DATE) < l.latest_period_end
    QUALIFY row_number() OVER (PARTITION BY r.company_number ORDER BY TRY_CAST(r.period_end AS DATE) DESC,
                               COALESCE(r.consolidated, FALSE) DESC) = 1
),
joined AS (
    SELECT
        c.company_number,
        c.name,
        c.status,
        c.category,
        c.inc_date,
        c.account_category,
        c.last_made_up_date,
        c.post_town,
        c.postcode,
        c.county,
        c.sic1, c.sic2, c.sic3, c.sic4,
        c.sic_text1,
        c.charges_outstanding,
        c.charges_total,
        c.charges_satisfied,
        c.previous_name,
        l.* EXCLUDE (company_number),
        p.prior_period_end, p.prior_employees, p.prior_turnover, p.prior_operating_profit,
        l.company_number IS NOT NULL                 AS has_accounts,
        -- EBITDA proxy: operating profit plus depreciation and amortisation where disclosed; operating
        -- profit alone when neither is disclosed (labelled as such in ebitda_basis).
        CASE WHEN l.latest_operating_profit IS NOT NULL
             THEN l.latest_operating_profit + COALESCE(ABS(l.latest_depreciation), 0) + COALESCE(ABS(l.latest_amortisation), 0)
             END                                     AS ebitda_proxy,
        CASE WHEN l.latest_operating_profit IS NULL THEN NULL
             WHEN l.latest_depreciation IS NOT NULL AND l.latest_amortisation IS NOT NULL THEN 'operating profit + D + A'
             WHEN l.latest_depreciation IS NOT NULL THEN 'operating profit + depreciation'
             WHEN l.latest_amortisation IS NOT NULL THEN 'operating profit + amortisation'
             ELSE 'operating profit only' END       AS ebitda_basis,
        CASE WHEN p.prior_turnover > 0 AND l.latest_turnover IS NOT NULL
             THEN l.latest_turnover / p.prior_turnover - 1 END AS turnover_growth,
        CASE WHEN p.prior_employees > 0 AND l.latest_employees IS NOT NULL
             THEN l.latest_employees * 1.0 / p.prior_employees - 1 END AS employees_growth,
        CASE WHEN l.latest_turnover > 0 AND l.latest_operating_profit IS NOT NULL
             THEN l.latest_operating_profit / l.latest_turnover END AS operating_margin,
        CASE WHEN l.latest_turnover > 0 AND l.latest_gross_profit IS NOT NULL
             THEN l.latest_gross_profit / l.latest_turnover END AS gross_margin
    FROM candidate_companies c
    LEFT JOIN latest l USING (company_number)
    LEFT JOIN prior p USING (company_number)
),
rules AS (
    SELECT
        *,
        upper(trim(COALESCE(account_category, ''))) IN ('FULL', 'GROUP') AND (NOT has_accounts OR (latest_employees IS NULL AND latest_turnover IS NULL))
                                                     AS provisional,
        -- Rule S: a large company: head count at or above the floor, or turnover at or above the floor.
        COALESCE(latest_employees BETWEEN $universe_employees_min AND $universe_employees_max, FALSE)
            OR COALESCE(latest_turnover >= $universe_turnover_min_gbp, FALSE)
            OR (upper(trim(COALESCE(account_category, ''))) IN ('FULL', 'GROUP') AND (NOT has_accounts OR (latest_employees IS NULL AND latest_turnover IS NULL)))
                                                     AS passes_size,
        -- Rule C: account category not in the excluded list.
        NOT COALESCE(list_contains($exclude_account_categories, upper(trim(account_category))), FALSE)
                                                     AS passes_category,
        -- Rule L: a company with share capital (not a guarantee company, CIC or overseas branch).
        NOT (upper(COALESCE(category, '')) LIKE 'PRI/LBG%' OR upper(COALESCE(category, '')) LIKE 'PRI/LTD BY GUAR%'
             OR upper(COALESCE(category, '')) IN ('COMMUNITY INTEREST COMPANY', 'OTHER COMPANY TYPE', 'REGISTERED SOCIETY', 'CHARITABLE INCORPORATED ORGANISATION', 'SCOTTISH CHARITABLE INCORPORATED ORGANISATION', 'INDUSTRIAL AND PROVIDENT SOCIETY', 'ROYAL CHARTER COMPANY'))
                                                     AS passes_legal_form,
        -- Rule I: primary SIC not a bank, insurer, pension fund, public body or household code.
        NOT COALESCE(list_contains($exclude_sic, CAST(sic1 AS VARCHAR)), FALSE)
                                                     AS passes_sic,
        -- Rule P: not a pure P&L-exempt subsidiary with no head count (nothing to screen).
        NOT (COALESCE(latest_pl_exempt, FALSE) AND latest_employees IS NULL AND latest_turnover IS NULL AND has_accounts)
                                                     AS passes_disclosure,
        -- Ranked-list gates (informational here; rankings apply them): turnover or EBITDA at scale.
        COALESCE(latest_turnover >= $rank_turnover_min_gbp, FALSE)
            OR COALESCE(CASE WHEN latest_operating_profit IS NOT NULL
                             THEN latest_operating_profit + COALESCE(ABS(latest_depreciation), 0) + COALESCE(ABS(latest_amortisation), 0) END
                        >= $ebitda_early_floor_gbp, FALSE)
                                                     AS at_scale
    FROM joined
)
SELECT
    *,
    passes_size AND passes_category AND passes_sic AND passes_disclosure AND passes_legal_form AS passes_all,
    CASE
        WHEN NOT passes_legal_form                   THEN 'legal_form_excluded'
        WHEN NOT passes_sic                          THEN 'sic_excluded'
        WHEN NOT passes_category                     THEN 'account_category_excluded'
        WHEN NOT passes_disclosure                   THEN 'pl_exempt_no_disclosure'
        WHEN provisional                             THEN NULL
        WHEN NOT has_accounts                        THEN 'no_accounts'
        WHEN latest_employees IS NULL AND latest_turnover IS NULL THEN 'size_missing'
        WHEN NOT passes_size                         THEN 'below_size_floor'
        ELSE NULL
    END                                              AS exclusion_reason,
    $computed_at                                     AS computed_at
FROM rules
ORDER BY company_number
