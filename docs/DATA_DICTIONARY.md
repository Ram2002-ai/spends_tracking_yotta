# Data dictionary

Generated from `hfsynth/schema.py` (single source of truth). Money is USD with 2 decimals; dates are ISO-8601; booleans are 0/1; NULL is an empty CSV cell.

## Relationships and cardinality

| Parent | Child | Cardinality | Optional | Note |
|---|---|---|---|---|
| user_profile | account | 1:N | no | every user has checking + savings, ~55% also a credit card |
| account | transaction | 1:N | no | ledger rows |
| merchant | transaction | 1:N | yes | NULL when the descriptor is not in the alias table |
| merchant | merchant_alias | 1:N | no |  |
| merchant | category (via merchant_category) | N:M | no | bridge table; ambiguous merchants span categories |
| category | transaction | 1:N | no | system-assigned |
| category | category (parent_code) | 1:N | yes | two-level tree |
| category_rule | transaction | 1:N | no | rule that fired; rules are effective-dated |
| transaction | transaction (refund_of_txn_id) | 1:N | yes | one purchase may be refunded once |
| transaction | transaction (transfer_group_id) | 1:2 | yes | two legs of an internal transfer |
| user_profile | recurring_series | 1:N | no |  |
| recurring_series | recurring_series_event | 1:N | no | CREATED / AMOUNT_CHANGED / CANCELLED |
| user_profile | budget | 1:N | no | one row per category per month |
| budget | budget_event | 1:N | yes | adjustments; history is never overwritten |
| user_profile | insight | 1:N | no | derived |
| budget | insight | 1:N | yes |  |
| user_profile | exception_case | 1:N | no | subject is a transaction, budget line or series occurrence |
| exception_case | case_event | 1:N | no | OPENED -> ASSIGNED -> RESOLVED |

Retained history: `transaction`, `recurring_series_event`, `budget_event`, `case_event` are append-only; no row is overwritten. Budget category codes are intentionally *not* FK-enforced (edge case E5).

## Input tables

### category

Category taxonomy (2-level tree). Master data.

Primary key: `category_code`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| category_code | string | yes |  |  | yes |  | Immutable 3-letter code.; pattern ^[A-Z]{3}$ |
| category_name | string | yes |  |  | yes |  | Display name. |
| parent_code | string | no |  |  |  | category.category_code | Parent node; NULL for roots. |
| category_type | string | yes | EXPENSE, INCOME, TRANSFER, SYSTEM |  |  |  | Nature of the category. |
| is_spending | bool | yes |  |  |  |  | 1 if rows in this category count as household spending.; UNC is spending=1 on purpose (conservative default). |
| is_budgetable | bool | yes |  |  |  |  | 1 if a monthly budget may be set for it. |

### user_profile

Synthetic account holder. No real personal data.

Primary key: `user_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| user_id | string | yes |  |  | yes |  | USR-000001 style.; pattern ^USR-\d{6}$ |
| age_band | string | yes | 18-24, 25-34, 35-44, 45-54, 55-64, 65+ |  |  |  |  |
| region_code | string | yes | US-EAST, US-CENTRAL, US-MOUNTAIN, US-WEST |  |  |  |  |
| home_timezone | string | yes | America/New_York, America/Chicago, America/Denver, America/Los_Angeles |  |  |  | IANA zone; determines local date of every txn. |
| household_size | int | yes |  |  |  |  | People in the household.; 1..6 |
| monthly_net_income | decimal | yes |  | USD |  |  | Nominal net monthly income.; > 0 |
| pay_frequency | string | yes | BIWEEKLY, SEMI_MONTHLY, MONTHLY |  |  |  |  |
| signup_date | date | yes |  |  |  |  | <= first account open date + 60d and < year start |
| status | string | yes | ACTIVE |  |  |  | Lifecycle state. |

### account

Bank / card account owned by a user. 1:N from user_profile.

Primary key: `account_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| account_id | string | yes |  |  | yes |  | ACC-<user-id>-NN; 01 checking, 02 savings, 03 credit card.; pattern ^ACC-USR-\d{6}-\d{2}$ |
| user_id | string | yes |  |  |  | user_profile.user_id | pattern ^USR-\d{6}$ |
| account_type | string | yes | CHECKING, SAVINGS, CREDIT_CARD |  |  |  |  |
| currency | string | yes | USD |  |  |  |  |
| open_date | date | yes |  |  |  |  | <= first transaction date |
| opening_balance | decimal | yes |  | USD |  |  | Balance before the first ledger row. |
| closing_balance | decimal | yes |  | USD |  |  | DERIVED: opening + sum(amount).; must equal last transaction.balance_after |
| status | string | yes | ACTIVE |  |  |  |  |

### merchant

Canonical counterparty (retailer, employer, landlord, biller...).

Primary key: `merchant_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| merchant_id | string | yes |  |  | yes |  | pattern ^MER-\d{6}$ |
| canonical_name | string | yes |  |  | yes |  | Fictional business name. |
| merchant_type | string | yes | RETAILER, RESTAURANT, TRANSPORT, FUEL, ENTERTAINMENT, HEALTHCARE, TRAVEL, EDUCATION, MULTI_CATEGORY, SUBSCRIPTION, UTILITY, INSURER, LANDLORD, EMPLOYER |  |  |  |  |
| mcc | string | no |  |  |  |  | Merchant category code (NULL for employers). |
| default_category_code | string | yes |  |  |  | category.category_code | Category used by the alias rule. |
| is_multi_category | bool | yes |  |  |  |  | 1 = ambiguous merchant (sells several categories). |
| opened_date | date | yes |  |  |  |  |  |
| closed_date | date | no |  |  |  |  | no transaction after this date |
| status | string | yes | ACTIVE, CLOSED |  |  |  |  |

### merchant_alias

Descriptor aliases that resolve to a merchant. 1:N from merchant.

Primary key: `alias_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| alias_id | string | yes |  |  | yes |  | pattern ^ALI-\d{6}$ |
| merchant_id | string | yes |  |  |  | merchant.merchant_id | pattern ^MER-\d{6}$ |
| alias_text | string | yes |  |  | yes |  | Normalised (upper-case, no digits) descriptor text. |
| alias_type | string | yes | FULL, SHORT_NAME |  |  |  |  |

### merchant_category

BRIDGE (N:M) merchant <-> category. Ambiguous merchants have several rows.

Primary key: `merchant_id, category_code`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| merchant_id | string | yes |  |  |  | merchant.merchant_id | pattern ^MER-\d{6}$ |
| category_code | string | yes |  |  |  | category.category_code | pattern ^[A-Z]{3}$ |
| share | decimal | yes |  |  |  |  | Share of the merchant's baskets (approximate).; 0 < share <= 1; sums to 1 |
| is_default | bool | yes |  |  |  |  | 1 = category the alias rule assigns. |

### category_rule

Versioned categorisation rules with effective dating.

Primary key: `rule_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| rule_id | string | yes |  |  | yes |  | pattern ^RUL-\d{6}$ |
| rule_type | string | yes | TXN_TYPE, KEYWORD, MERCHANT_ALIAS, FALLBACK |  |  |  |  |
| match_value | string | yes |  |  |  |  | txn types (|-separated), a descriptor token, or *. |
| category_code | string | no |  |  |  | category.category_code | NULL for MERCHANT_ALIAS (uses merchant default).; pattern ^[A-Z]{3}$ |
| priority | int | yes |  |  |  |  | Lower wins. Unique among rules active at the same time (a retired rule and its successor share one). |
| effective_from | date | yes |  |  |  |  |  |
| effective_to | date | no |  |  |  |  | exclusive upper bound; > effective_from |
| status | string | yes | ACTIVE, RETIRED |  |  |  |  |

### transaction

Immutable signed ledger row (debits negative). Never updated.

Primary key: `txn_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| txn_id | string | yes |  |  | yes |  | TXN-2026-00000001, chronological by UTC time.; pattern ^TXN-\d{4}-\d{8}$ |
| account_id | string | yes |  |  |  | account.account_id | pattern ^ACC-USR-\d{6}-\d{2}$ |
| merchant_id | string | no |  |  |  | merchant.merchant_id | System-resolved merchant; NULL if descriptor unresolved.; pattern ^MER-\d{6}$ |
| category_code | string | yes |  |  |  | category.category_code | System-assigned (rule engine) category.; pattern ^[A-Z]{3}$ |
| category_rule_id | string | yes |  |  |  | category_rule.rule_id | Rule that fired. |
| txn_ts_utc | datetime | yes |  |  |  |  | UTC timestamp, ISO-8601 with Z. |
| utc_offset_min | int | yes |  | minutes |  |  | Offset in force for the user's zone.; local = utc + offset |
| txn_date | date | yes |  |  |  |  | LOCAL calendar date (budget bucketing uses this). |
| descriptor | string | yes |  |  |  |  | Raw bank descriptor. |
| amount | decimal | yes |  | USD |  |  | Signed: debit < 0, credit > 0.; <> 0 |
| currency | string | yes | USD |  |  |  |  |
| txn_type | string | yes | PURCHASE, REFUND, RECURRING_DEBIT, INCOME, TRANSFER_OUT, TRANSFER_IN |  |  |  |  |
| channel | string | yes | CARD_POS, CARD_ONLINE, ACH, BILL_PAY, TRANSFER |  |  |  |  |
| transfer_group_id | string | no |  |  |  |  | Links the two legs of an internal transfer.; pattern ^TRG-\d{8}$ |
| refund_of_txn_id | string | no |  |  |  | transaction.txn_id | Original purchase of a (correctly typed) refund. |
| balance_after | decimal | yes |  | USD |  |  | DERIVED running balance of the account. |

### recurring_series

Registered recurring schedule (salary, rent, bills, subscriptions).

Primary key: `series_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| series_id | string | yes |  |  | yes |  | pattern ^REC-\d{6}$ |
| user_id | string | yes |  |  |  | user_profile.user_id | pattern ^USR-\d{6}$ |
| account_id | string | yes |  |  |  | account.account_id | Account the payment posts to.; pattern ^ACC-USR-\d{6}-\d{2}$ |
| counterparty_account_id | string | no |  |  |  | account.account_id | Receiving account for internal transfers. |
| merchant_id | string | no |  |  |  | merchant.merchant_id | NULL for savings transfers.; pattern ^MER-\d{6}$ |
| series_type | string | yes | SALARY, RENT, UTILITY, INSURANCE, SUBSCRIPTION, SAVINGS_TRANSFER |  |  |  |  |
| category_code | string | yes |  |  |  | category.category_code | pattern ^[A-Z]{3}$ |
| cadence | string | yes | BIWEEKLY, SEMI_MONTHLY, MONTHLY, ANNUAL |  |  |  |  |
| anchor_date | date | yes |  |  |  |  | One real occurrence; the schedule is derived from it. |
| start_date | date | yes |  |  |  |  |  |
| end_date | date | no |  |  |  |  | set iff status = CANCELLED |
| direction | string | yes | CREDIT, DEBIT, TRANSFER |  |  |  |  |
| amount_type | string | yes | FIXED, VARIABLE |  |  |  |  |
| initial_amount | decimal | yes |  | USD |  |  |  |
| current_amount | decimal | yes |  | USD |  |  | DERIVED from the AMOUNT_CHANGED events. |
| status | string | yes | ACTIVE, CANCELLED |  |  |  |  |

### recurring_series_event

Append-only history of series state changes.

Primary key: `event_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| event_id | string | yes |  |  | yes |  | pattern ^SEV-\d{6}$ |
| series_id | string | yes |  |  |  | recurring_series.series_id | pattern ^REC-\d{6}$ |
| event_type | string | yes | CREATED, AMOUNT_CHANGED, CANCELLED |  |  |  |  |
| event_date | date | yes |  |  |  |  |  |
| old_amount | decimal | no |  | USD |  |  |  |
| new_amount | decimal | no |  | USD |  |  |  |

### budget

Monthly budget line (user x category x month).

Primary key: `budget_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| budget_id | string | yes |  |  | yes |  | BUD-<user-id>-2026-01-<category-code>; pattern ^BUD-USR-\d{6}-\d{4}-\d{2}-[A-Z]{3,10}$ |
| user_id | string | yes |  |  |  | user_profile.user_id | pattern ^USR-\d{6}$ |
| category_code | string | yes |  |  |  | category.category_code (not enforced) | Normally a taxonomy code. Legacy codes (edge case E5) are NOT in the taxonomy. |
| period | string | yes |  |  |  |  | YYYY-MM; pattern ^\d{4}-\d{2}$ |
| period_start | date | yes |  |  |  |  |  |
| period_end | date | yes |  |  |  |  | >= period_start |
| amount | decimal | yes |  | USD |  |  | Current budget after adjustments.; > 0 |
| currency | string | yes | USD |  |  |  |  |
| revision | int | yes |  |  |  |  | 1 + number of ADJUSTED events. |
| status | string | yes | ACTIVE, CLOSED |  |  |  | CLOSED once the period ended (as-of 31 Dec). |

### budget_event

Append-only budget adjustments.

Primary key: `event_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| event_id | string | yes |  |  | yes |  | pattern ^BEV-\d{7}$ |
| budget_id | string | yes |  |  |  | budget.budget_id | pattern ^BUD-USR-\d{6}-\d{4}-\d{2}-[A-Z]{3,10}$ |
| event_type | string | yes | ADJUSTED |  |  |  |  |
| event_date | date | yes |  |  |  |  | within the budget period |
| old_amount | decimal | yes |  | USD |  |  |  |
| new_amount | decimal | yes |  | USD |  |  |  |

### insight

Derived insight produced from ledger + budget aggregations.

Primary key: `insight_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| insight_id | string | yes |  |  | yes |  | pattern ^INS-\d{8}$ |
| user_id | string | yes |  |  |  | user_profile.user_id | pattern ^USR-\d{6}$ |
| period | string | yes |  |  |  |  | pattern ^\d{4}-\d{2}$ |
| insight_type | string | yes | BUDGET_OVER, BUDGET_NEAR, MONTHLY_SUMMARY, BUDGET_CATEGORY_UNMAPPED |  |  |  |  |
| category_code | string | no |  |  |  | category.category_code | pattern ^[A-Z]{3}$ |
| budget_id | string | no |  |  |  | budget.budget_id | pattern ^BUD-USR-\d{6}-\d{4}-\d{2}-[A-Z]{3,10}$ |
| metric_value | decimal | yes |  |  |  |  | Actual spend (USD) or count of unmapped lines. |
| threshold_value | decimal | no |  |  |  |  | Budget amount (USD) or income for summaries. |
| ratio | decimal | no |  |  |  |  | metric / threshold. |
| severity | string | yes | INFO, WARN, ALERT |  |  |  |  |
| generated_by_rule | string | yes | IN1, IN2, IN3, IN4 |  |  |  |  |
| created_date | date | yes |  |  |  |  |  |

### exception_case

Review case raised by a detection rule (exception path).

Primary key: `case_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| case_id | string | yes |  |  | yes |  | pattern ^CASE-\d{7}$ |
| case_type | string | yes | TRANSFER_DOUBLE_COUNT, CREDIT_AS_PURCHASE, UNCATEGORIZED_HIGH_VALUE, BUDGET_CATEGORY_UNMAPPED, RECURRING_MISSED |  |  |  |  |
| subject_type | string | yes | TRANSACTION, BUDGET, SERIES |  |  |  |  |
| subject_id | string | yes |  |  |  |  |  |
| user_id | string | yes |  |  |  | user_profile.user_id | pattern ^USR-\d{6}$ |
| reference_date | date | yes |  |  |  |  |  |
| detected_by_rule | string | yes | CR1, CR2, CR3, CR4, CR5 |  |  |  |  |
| severity | string | yes | LOW, MEDIUM, HIGH |  |  |  |  |
| status | string | yes | OPEN, ASSIGNED, RESOLVED |  |  |  |  |
| assigned_role | string | no | OPS_ANALYST, RISK_REVIEWER, SYSTEM_ADMIN |  |  |  |  |
| opened_at | datetime | yes |  |  |  |  |  |
| closed_at | datetime | no |  |  |  |  | >= opened_at; set iff RESOLVED |
| resolution_code | string | no |  |  |  |  |  |

### case_event

Append-only history of case state changes.

Primary key: `event_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| event_id | string | yes |  |  | yes |  | pattern ^CEV-\d{8}$ |
| case_id | string | yes |  |  |  | exception_case.case_id | pattern ^CASE-\d{7}$ |
| event_type | string | yes | OPENED, ASSIGNED, RESOLVED |  |  |  |  |
| event_ts | datetime | yes |  |  |  |  |  |
| actor_role | string | yes | SYSTEM, OPS_ANALYST, RISK_REVIEWER, SYSTEM_ADMIN |  |  |  |  |
| note_code | string | yes |  |  |  |  |  |

## Ground-truth tables (separate folder, never features)

### gt_transaction

Ground-truth label per ledger row. NEVER use as a model feature.

Primary key: `txn_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| txn_id | string | yes |  |  | yes | transaction.txn_id | pattern ^TXN-\d{4}-\d{8}$ |
| true_category_code | string | yes |  |  |  | category.category_code |  |
| true_merchant_id | string | no |  |  |  | merchant.merchant_id |  |
| true_txn_type | string | yes | PURCHASE, REFUND, RECURRING_DEBIT, INCOME, TRANSFER_OUT, TRANSFER_IN, TRANSFER_DUPLICATE |  |  |  |  |
| true_spend_amount | decimal | yes |  | USD |  |  | Signed spending effect (refunds negative; transfers/income 0). |
| expected_period | string | yes |  |  |  |  | Correct LOCAL month YYYY-MM. |
| issue_type | string | yes | NONE, TRANSFER_DOUBLE_COUNT, REFUND_MISCLASSIFIED, RECURRING_SKIPPED, TZ_BOUNDARY, BUDGET_CATEGORY_MISMATCH |  |  |  |  |
| merchant_resolvable | bool | yes |  |  |  |  | Descriptor is in the alias table. |
| is_ambiguous_merchant | bool | yes |  |  |  |  |  |
| related_txn_id | string | no |  |  |  | transaction.txn_id |  |
| series_id | string | no |  |  |  | recurring_series.series_id | pattern ^REC-\d{6}$ |

### gt_issue

Registry of every injected edge case.

Primary key: `issue_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| issue_id | string | yes |  |  | yes |  | pattern ^ISS-\d{7}$ |
| issue_type | string | yes | TRANSFER_DOUBLE_COUNT, REFUND_MISCLASSIFIED, RECURRING_SKIPPED, TZ_BOUNDARY, BUDGET_CATEGORY_MISMATCH |  |  |  |  |
| entity_type | string | yes | TRANSACTION, SERIES_OCCURRENCE, BUDGET |  |  |  |  |
| entity_id | string | yes |  |  |  |  |  |
| user_id | string | yes |  |  |  | user_profile.user_id |  |
| expected_value | string | no |  |  |  |  |  |
| observed_value | string | no |  |  |  |  |  |
| note | string | no |  |  |  |  |  |

### gt_recurring_occurrence

Every scheduled occurrence and whether it posted.

Primary key: `series_id, occurrence_no`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| series_id | string | yes |  |  |  | recurring_series.series_id | pattern ^REC-\d{6}$ |
| occurrence_no | int | yes |  |  |  |  |  |
| expected_date | date | yes |  |  |  |  |  |
| expected_amount | decimal | yes |  | USD |  |  |  |
| status | string | yes | POSTED, SKIPPED |  |  |  |  |
| txn_id | string | no |  |  |  | transaction.txn_id | pattern ^TXN-\d{4}-\d{8}$ |
| actual_date | date | no |  |  |  |  |  |

### gt_user_latent

Latent generation parameters (not observable features).

Primary key: `user_id`

| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |
|---|---|---|---|---|---|---|---|
| user_id | string | yes |  |  | yes | user_profile.user_id | pattern ^USR-\d{6}$ |
| persona | string | yes | FRUGAL, BALANCED, SPENDER |  |  |  |  |
| spend_factor | decimal | yes |  |  |  |  |  |
