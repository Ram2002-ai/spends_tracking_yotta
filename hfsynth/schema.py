"""Single source of truth for every table: drives the data dictionary, the SQL DDL,
the CSV loader and the generic validation checks (types, enums, PK/FK, patterns)."""
from dataclasses import dataclass, field
from typing import Optional

from . import ids


@dataclass
class Field:
    name: str
    dtype: str                      # string,int,decimal,date,datetime,bool
    required: bool = True
    desc: str = ""
    allowed: Optional[tuple] = None
    unit: str = ""
    unique: bool = False
    rule: str = ""
    fk: Optional[str] = None        # "table.column"
    pattern: Optional[str] = None
    fk_enforced: bool = True


@dataclass
class Table:
    name: str
    pk: tuple
    desc: str
    fields: list = field(default_factory=list)
    ground_truth: bool = False

    @property
    def cols(self):
        return [f.name for f in self.fields]

    def ix(self):
        return {f.name: i for i, f in enumerate(self.fields)}


def F(name, dtype, req=True, desc="", **kw):
    return Field(name, dtype, req, desc, **kw)


def _pat(col):
    return ids.PATTERNS.get(col)


def ID(name, desc="", **kw):
    return F(name, "string", True, desc, pattern=_pat(name), **kw)


def FK(name, ref, req=True, desc="", **kw):
    return F(name, "string", req, desc, fk=ref, pattern=_pat(name), **kw)


USD = "USD"
TXN_TYPES = ("PURCHASE", "REFUND", "RECURRING_DEBIT", "INCOME", "TRANSFER_OUT", "TRANSFER_IN")
SERIES_TYPES = ("SALARY", "RENT", "UTILITY", "INSURANCE", "SUBSCRIPTION", "SAVINGS_TRANSFER")
ISSUE_TYPES = ("TRANSFER_DOUBLE_COUNT", "REFUND_MISCLASSIFIED", "RECURRING_SKIPPED", "TZ_BOUNDARY",
               "BUDGET_CATEGORY_MISMATCH")
CASE_TYPES = ("TRANSFER_DOUBLE_COUNT", "CREDIT_AS_PURCHASE", "UNCATEGORIZED_HIGH_VALUE",
              "BUDGET_CATEGORY_UNMAPPED", "RECURRING_MISSED")
CR_RULES = ("CR1", "CR2", "CR3", "CR4", "CR5")

TABLES = [
    Table("category", ("category_code",), "Category taxonomy (2-level tree). Master data.", [
        ID("category_code", "Immutable 3-letter code.", unique=True),
        F("category_name", "string", desc="Display name.", unique=True),
        FK("parent_code", "category.category_code", False, "Parent node; NULL for roots."),
        F("category_type", "string", desc="Nature of the category.", allowed=("EXPENSE", "INCOME", "TRANSFER", "SYSTEM")),
        F("is_spending", "bool", desc="1 if rows in this category count as household spending.",
          rule="UNC is spending=1 on purpose (conservative default)."),
        F("is_budgetable", "bool", desc="1 if a monthly budget may be set for it."),
    ]),
    Table("user_profile", ("user_id",), "Synthetic account holder. No real personal data.", [
        ID("user_id", "USR-000001 style.", unique=True),
        F("age_band", "string", allowed=("18-24", "25-34", "35-44", "45-54", "55-64", "65+")),
        F("region_code", "string", allowed=("US-EAST", "US-CENTRAL", "US-MOUNTAIN", "US-WEST")),
        F("home_timezone", "string", desc="IANA zone; determines local date of every txn.",
          allowed=("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")),
        F("household_size", "int", desc="People in the household.", rule="1..6"),
        F("monthly_net_income", "decimal", unit=USD, desc="Nominal net monthly income.", rule="> 0"),
        F("pay_frequency", "string", allowed=("BIWEEKLY", "SEMI_MONTHLY", "MONTHLY")),
        F("signup_date", "date", rule="<= first account open date + 60d and < year start"),
        F("status", "string", allowed=("ACTIVE",), desc="Lifecycle state."),
    ]),
    Table("account", ("account_id",), "Bank / card account owned by a user. 1:N from user_profile.", [
        ID("account_id", "ACC-<user-id>-NN; 01 checking, 02 savings, 03 credit card.", unique=True),
        FK("user_id", "user_profile.user_id"),
        F("account_type", "string", allowed=("CHECKING", "SAVINGS", "CREDIT_CARD")),
        F("currency", "string", allowed=(USD,)),
        F("open_date", "date", rule="<= first transaction date"),
        F("opening_balance", "decimal", unit=USD, desc="Balance before the first ledger row."),
        F("closing_balance", "decimal", unit=USD, desc="DERIVED: opening + sum(amount).",
          rule="must equal last transaction.balance_after"),
        F("status", "string", allowed=("ACTIVE",)),
    ]),
    Table("merchant", ("merchant_id",), "Canonical counterparty (retailer, employer, landlord, biller...).", [
        ID("merchant_id", unique=True),
        F("canonical_name", "string", unique=True, desc="Fictional business name."),
        F("merchant_type", "string", allowed=("RETAILER", "RESTAURANT", "TRANSPORT", "FUEL", "ENTERTAINMENT",
                                              "HEALTHCARE", "TRAVEL", "EDUCATION", "MULTI_CATEGORY",
                                              "SUBSCRIPTION", "UTILITY", "INSURER", "LANDLORD", "EMPLOYER")),
        F("mcc", "string", False, "Merchant category code (NULL for employers)."),
        FK("default_category_code", "category.category_code", desc="Category used by the alias rule."),
        F("is_multi_category", "bool", desc="1 = ambiguous merchant (sells several categories)."),
        F("opened_date", "date"),
        F("closed_date", "date", False, rule="no transaction after this date"),
        F("status", "string", allowed=("ACTIVE", "CLOSED")),
    ]),
    Table("merchant_alias", ("alias_id",), "Descriptor aliases that resolve to a merchant. 1:N from merchant.", [
        ID("alias_id", unique=True),
        FK("merchant_id", "merchant.merchant_id"),
        F("alias_text", "string", unique=True, desc="Normalised (upper-case, no digits) descriptor text."),
        F("alias_type", "string", allowed=("FULL", "SHORT_NAME")),
    ]),
    Table("merchant_category", ("merchant_id", "category_code"),
          "BRIDGE (N:M) merchant <-> category. Ambiguous merchants have several rows.", [
        FK("merchant_id", "merchant.merchant_id"),
        FK("category_code", "category.category_code"),
        F("share", "decimal", desc="Share of the merchant's baskets (approximate).", rule="0 < share <= 1; sums to 1"),
        F("is_default", "bool", desc="1 = category the alias rule assigns."),
    ]),
    Table("category_rule", ("rule_id",), "Versioned categorisation rules with effective dating.", [
        ID("rule_id", unique=True),
        F("rule_type", "string", allowed=("TXN_TYPE", "KEYWORD", "MERCHANT_ALIAS", "FALLBACK")),
        F("match_value", "string", desc="txn types (|-separated), a descriptor token, or *."),
        FK("category_code", "category.category_code", False, "NULL for MERCHANT_ALIAS (uses merchant default)."),
        F("priority", "int", desc="Lower wins. Unique among rules active at the same time (a retired rule and its successor share one)."),
        F("effective_from", "date"),
        F("effective_to", "date", False, rule="exclusive upper bound; > effective_from"),
        F("status", "string", allowed=("ACTIVE", "RETIRED")),
    ]),
    Table("transaction", ("txn_id",), "Immutable signed ledger row (debits negative). Never updated.", [
        ID("txn_id", "TXN-2026-00000001, chronological by UTC time.", unique=True),
        FK("account_id", "account.account_id"),
        FK("merchant_id", "merchant.merchant_id", False, "System-resolved merchant; NULL if descriptor unresolved."),
        FK("category_code", "category.category_code", desc="System-assigned (rule engine) category."),
        FK("category_rule_id", "category_rule.rule_id", desc="Rule that fired."),
        F("txn_ts_utc", "datetime", desc="UTC timestamp, ISO-8601 with Z."),
        F("utc_offset_min", "int", unit="minutes", desc="Offset in force for the user's zone.",
          rule="local = utc + offset"),
        F("txn_date", "date", desc="LOCAL calendar date (budget bucketing uses this)."),
        F("descriptor", "string", desc="Raw bank descriptor."),
        F("amount", "decimal", unit=USD, desc="Signed: debit < 0, credit > 0.", rule="<> 0"),
        F("currency", "string", allowed=(USD,)),
        F("txn_type", "string", allowed=TXN_TYPES),
        F("channel", "string", allowed=("CARD_POS", "CARD_ONLINE", "ACH", "BILL_PAY", "TRANSFER")),
        F("transfer_group_id", "string", False, "Links the two legs of an internal transfer.",
          pattern=_pat("transfer_group_id")),
        FK("refund_of_txn_id", "transaction.txn_id", False, "Original purchase of a (correctly typed) refund."),
        F("balance_after", "decimal", unit=USD, desc="DERIVED running balance of the account."),
    ]),
    Table("recurring_series", ("series_id",), "Registered recurring schedule (salary, rent, bills, subscriptions).", [
        ID("series_id", unique=True),
        FK("user_id", "user_profile.user_id"),
        FK("account_id", "account.account_id", desc="Account the payment posts to."),
        FK("counterparty_account_id", "account.account_id", False, "Receiving account for internal transfers."),
        FK("merchant_id", "merchant.merchant_id", False, "NULL for savings transfers."),
        F("series_type", "string", allowed=SERIES_TYPES),
        FK("category_code", "category.category_code"),
        F("cadence", "string", allowed=("BIWEEKLY", "SEMI_MONTHLY", "MONTHLY", "ANNUAL")),
        F("anchor_date", "date", desc="One real occurrence; the schedule is derived from it."),
        F("start_date", "date"),
        F("end_date", "date", False, rule="set iff status = CANCELLED"),
        F("direction", "string", allowed=("CREDIT", "DEBIT", "TRANSFER")),
        F("amount_type", "string", allowed=("FIXED", "VARIABLE")),
        F("initial_amount", "decimal", unit=USD),
        F("current_amount", "decimal", unit=USD, desc="DERIVED from the AMOUNT_CHANGED events."),
        F("status", "string", allowed=("ACTIVE", "CANCELLED")),
    ]),
    Table("recurring_series_event", ("event_id",), "Append-only history of series state changes.", [
        F("event_id", "string", pattern=_pat("series_event_id"), unique=True),
        FK("series_id", "recurring_series.series_id"),
        F("event_type", "string", allowed=("CREATED", "AMOUNT_CHANGED", "CANCELLED")),
        F("event_date", "date"),
        F("old_amount", "decimal", False, unit=USD),
        F("new_amount", "decimal", False, unit=USD),
    ]),
    Table("budget", ("budget_id",), "Monthly budget line (user x category x month).", [
        ID("budget_id", "BUD-<user-id>-2026-01-<category-code>", unique=True),
        FK("user_id", "user_profile.user_id"),
        F("category_code", "string", desc="Normally a taxonomy code. Legacy codes (edge case E5) are NOT in the taxonomy.",
          fk="category.category_code", fk_enforced=False),
        F("period", "string", desc="YYYY-MM", pattern=r"^\d{4}-\d{2}$"),
        F("period_start", "date"),
        F("period_end", "date", rule=">= period_start"),
        F("amount", "decimal", unit=USD, desc="Current budget after adjustments.", rule="> 0"),
        F("currency", "string", allowed=(USD,)),
        F("revision", "int", desc="1 + number of ADJUSTED events."),
        F("status", "string", allowed=("ACTIVE", "CLOSED"), desc="CLOSED once the period ended (as-of 31 Dec)."),
    ]),
    Table("budget_event", ("event_id",), "Append-only budget adjustments.", [
        F("event_id", "string", pattern=_pat("budget_event_id"), unique=True),
        FK("budget_id", "budget.budget_id"),
        F("event_type", "string", allowed=("ADJUSTED",)),
        F("event_date", "date", rule="within the budget period"),
        F("old_amount", "decimal", unit=USD),
        F("new_amount", "decimal", unit=USD),
    ]),
    Table("insight", ("insight_id",), "Derived insight produced from ledger + budget aggregations.", [
        ID("insight_id", unique=True),
        FK("user_id", "user_profile.user_id"),
        F("period", "string", pattern=r"^\d{4}-\d{2}$"),
        F("insight_type", "string", allowed=("BUDGET_OVER", "BUDGET_NEAR", "MONTHLY_SUMMARY", "BUDGET_CATEGORY_UNMAPPED")),
        FK("category_code", "category.category_code", False),
        FK("budget_id", "budget.budget_id", False),
        F("metric_value", "decimal", desc="Actual spend (USD) or count of unmapped lines."),
        F("threshold_value", "decimal", False, desc="Budget amount (USD) or income for summaries."),
        F("ratio", "decimal", False, desc="metric / threshold."),
        F("severity", "string", allowed=("INFO", "WARN", "ALERT")),
        F("generated_by_rule", "string", allowed=("IN1", "IN2", "IN3", "IN4")),
        F("created_date", "date"),
    ]),
    Table("exception_case", ("case_id",), "Review case raised by a detection rule (exception path).", [
        ID("case_id", unique=True),
        F("case_type", "string", allowed=CASE_TYPES),
        F("subject_type", "string", allowed=("TRANSACTION", "BUDGET", "SERIES")),
        F("subject_id", "string"),
        FK("user_id", "user_profile.user_id"),
        F("reference_date", "date"),
        F("detected_by_rule", "string", allowed=CR_RULES),
        F("severity", "string", allowed=("LOW", "MEDIUM", "HIGH")),
        F("status", "string", allowed=("OPEN", "ASSIGNED", "RESOLVED")),
        F("assigned_role", "string", False, allowed=("OPS_ANALYST", "RISK_REVIEWER", "SYSTEM_ADMIN")),
        F("opened_at", "datetime"),
        F("closed_at", "datetime", False, rule=">= opened_at; set iff RESOLVED"),
        F("resolution_code", "string", False),
    ]),
    Table("case_event", ("event_id",), "Append-only history of case state changes.", [
        F("event_id", "string", pattern=_pat("case_event_id"), unique=True),
        FK("case_id", "exception_case.case_id"),
        F("event_type", "string", allowed=("OPENED", "ASSIGNED", "RESOLVED")),
        F("event_ts", "datetime"),
        F("actor_role", "string", allowed=("SYSTEM", "OPS_ANALYST", "RISK_REVIEWER", "SYSTEM_ADMIN")),
        F("note_code", "string"),
    ]),
]

GT_TABLES = [
    Table("gt_transaction", ("txn_id",), "Ground-truth label per ledger row. NEVER use as a model feature.", [
        FK("txn_id", "transaction.txn_id", unique=True),
        F("true_category_code", "string", fk="category.category_code"),
        FK("true_merchant_id", "merchant.merchant_id", False),
        F("true_txn_type", "string", allowed=TXN_TYPES + ("TRANSFER_DUPLICATE",)),
        F("true_spend_amount", "decimal", unit=USD, desc="Signed spending effect (refunds negative; transfers/income 0)."),
        F("expected_period", "string", desc="Correct LOCAL month YYYY-MM."),
        F("issue_type", "string", allowed=("NONE",) + ISSUE_TYPES),
        F("merchant_resolvable", "bool", desc="Descriptor is in the alias table."),
        F("is_ambiguous_merchant", "bool"),
        FK("related_txn_id", "transaction.txn_id", False),
        FK("series_id", "recurring_series.series_id", False),
    ], True),
    Table("gt_issue", ("issue_id",), "Registry of every injected edge case.", [
        ID("issue_id", unique=True),
        F("issue_type", "string", allowed=ISSUE_TYPES),
        F("entity_type", "string", allowed=("TRANSACTION", "SERIES_OCCURRENCE", "BUDGET")),
        F("entity_id", "string"),
        F("user_id", "string", fk="user_profile.user_id"),
        F("expected_value", "string", False),
        F("observed_value", "string", False),
        F("note", "string", False),
    ], True),
    Table("gt_recurring_occurrence", ("series_id", "occurrence_no"), "Every scheduled occurrence and whether it posted.", [
        FK("series_id", "recurring_series.series_id"),
        F("occurrence_no", "int"),
        F("expected_date", "date"),
        F("expected_amount", "decimal", unit=USD),
        F("status", "string", allowed=("POSTED", "SKIPPED")),
        FK("txn_id", "transaction.txn_id", False),
        F("actual_date", "date", False),
    ], True),
    Table("gt_user_latent", ("user_id",), "Latent generation parameters (not observable features).", [
        FK("user_id", "user_profile.user_id", unique=True),
        F("persona", "string", allowed=("FRUGAL", "BALANCED", "SPENDER")),
        F("spend_factor", "decimal"),
    ], True),
]

BY_NAME = {t.name: t for t in TABLES + GT_TABLES}

# (parent, child, cardinality, optional?, note)
RELATIONSHIPS = [
    ("user_profile", "account", "1:N", "no", "every user has checking + savings, ~55% also a credit card"),
    ("account", "transaction", "1:N", "no", "ledger rows"),
    ("merchant", "transaction", "1:N", "yes", "NULL when the descriptor is not in the alias table"),
    ("merchant", "merchant_alias", "1:N", "no", ""),
    ("merchant", "category (via merchant_category)", "N:M", "no", "bridge table; ambiguous merchants span categories"),
    ("category", "transaction", "1:N", "no", "system-assigned"),
    ("category", "category (parent_code)", "1:N", "yes", "two-level tree"),
    ("category_rule", "transaction", "1:N", "no", "rule that fired; rules are effective-dated"),
    ("transaction", "transaction (refund_of_txn_id)", "1:N", "yes", "one purchase may be refunded once"),
    ("transaction", "transaction (transfer_group_id)", "1:2", "yes", "two legs of an internal transfer"),
    ("user_profile", "recurring_series", "1:N", "no", ""),
    ("recurring_series", "recurring_series_event", "1:N", "no", "CREATED / AMOUNT_CHANGED / CANCELLED"),
    ("user_profile", "budget", "1:N", "no", "one row per category per month"),
    ("budget", "budget_event", "1:N", "yes", "adjustments; history is never overwritten"),
    ("user_profile", "insight", "1:N", "no", "derived"),
    ("budget", "insight", "1:N", "yes", ""),
    ("user_profile", "exception_case", "1:N", "no", "subject is a transaction, budget line or series occurrence"),
    ("exception_case", "case_event", "1:N", "no", "OPENED -> ASSIGNED -> RESOLVED"),
]

_SQL = {"string": "TEXT", "int": "INTEGER", "decimal": "NUMERIC", "date": "TEXT", "datetime": "TEXT", "bool": "INTEGER"}


def ddl(tables=None):
    out = ["-- Generated by hfsynth. SQLite-compatible; works on PostgreSQL with minor type changes."]
    for t in tables or TABLES:
        lines = []
        for f in t.fields:
            s = f"  {f.name} {_SQL[f.dtype]}" + (" NOT NULL" if f.required else "")
            if f.allowed:
                vals = ",".join("'" + v + "'" for v in f.allowed)
                s += f" CHECK ({f.name} IN ({vals}))"
            lines.append(s)
        lines.append(f"  PRIMARY KEY ({', '.join(t.pk)})")
        for f in t.fields:
            if f.fk and f.fk_enforced and not t.ground_truth:
                rt, rc = f.fk.split(".")
                lines.append(f"  FOREIGN KEY ({f.name}) REFERENCES \"{rt}\"({rc})")
        out.append(f"CREATE TABLE \"{t.name}\" (\n" + ",\n".join(lines) + "\n);")
    return "\n\n".join(out) + "\n"


def data_dictionary_md():
    o = ["# Data dictionary", "",
         "Generated from `hfsynth/schema.py` (single source of truth). Money is USD with 2 decimals; "
         "dates are ISO-8601; booleans are 0/1; NULL is an empty CSV cell.", "",
         "## Relationships and cardinality", "",
         "| Parent | Child | Cardinality | Optional | Note |", "|---|---|---|---|---|"]
    for p, c, k, op, n in RELATIONSHIPS:
        o.append(f"| {p} | {c} | {k} | {op} | {n} |")
    o += ["", "Retained history: `transaction`, `recurring_series_event`, `budget_event`, `case_event` are append-only; "
          "no row is overwritten. Budget category codes are intentionally *not* FK-enforced (edge case E5).", ""]
    for grp, title in ((TABLES, "Input tables"), (GT_TABLES, "Ground-truth tables (separate folder, never features)")):
        o += [f"## {title}", ""]
        for t in grp:
            o += [f"### {t.name}", "", t.desc, "", f"Primary key: `{', '.join(t.pk)}`", "",
                  "| Field | Type | Required | Allowed values | Unit | Unique | FK | Validation / notes |",
                  "|---|---|---|---|---|---|---|---|"]
            for f in t.fields:
                notes = "; ".join(x for x in (f.desc, f.rule, ("pattern " + f.pattern) if f.pattern else "") if x)
                o.append(f"| {f.name} | {f.dtype} | {'yes' if f.required else 'no'} | "
                         f"{', '.join(f.allowed) if f.allowed else ''} | {f.unit} | {'yes' if f.unique or len(t.pk)==1 and f.name==t.pk[0] else ''} | "
                         f"{(f.fk + ('' if f.fk_enforced else ' (not enforced)')) if f.fk else ''} | {notes} |")
            o.append("")
    return "\n".join(o)


@dataclass
class Dataset:
    tables: dict = field(default_factory=dict)   # name -> list[list]
    gt: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def get(self, name):
        return self.tables.get(name) if name in self.tables else self.gt[name]
