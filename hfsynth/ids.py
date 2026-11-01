"""Deterministic, zero-padded, immutable ID builders (+ the regexes used by validation)."""


def user_id(n): return f"USR-{n:06d}"
def account_id(uid, k): return f"ACC-{uid}-{k:02d}"
def txn_id(year, n): return f"TXN-{year}-{n:08d}"
def budget_id(uid, year, month, code): return f"BUD-{uid}-{year}-{month:02d}-{code}"
def series_id(n): return f"REC-{n:06d}"
def merchant_id(n): return f"MER-{n:06d}"
def alias_id(n): return f"ALI-{n:06d}"
def rule_id(n): return f"RUL-{n:06d}"
def insight_id(n): return f"INS-{n:08d}"
def case_id(n): return f"CASE-{n:07d}"
def case_event_id(n): return f"CEV-{n:08d}"
def series_event_id(n): return f"SEV-{n:06d}"
def budget_event_id(n): return f"BEV-{n:07d}"
def transfer_group_id(n): return f"TRG-{n:08d}"
def issue_id(n): return f"ISS-{n:07d}"


PATTERNS = {
    "user_id": r"^USR-\d{6}$",
    "account_id": r"^ACC-USR-\d{6}-\d{2}$",
    "txn_id": r"^TXN-\d{4}-\d{8}$",
    "budget_id": r"^BUD-USR-\d{6}-\d{4}-\d{2}-[A-Z]{3,10}$",
    "series_id": r"^REC-\d{6}$",
    "merchant_id": r"^MER-\d{6}$",
    "alias_id": r"^ALI-\d{6}$",
    "rule_id": r"^RUL-\d{6}$",
    "insight_id": r"^INS-\d{8}$",
    "case_id": r"^CASE-\d{7}$",
    "case_event_id": r"^CEV-\d{8}$",
    "series_event_id": r"^SEV-\d{6}$",
    "budget_event_id": r"^BEV-\d{7}$",
    "transfer_group_id": r"^TRG-\d{8}$",
    "issue_id": r"^ISS-\d{7}$",
    "category_code": r"^[A-Z]{3}$",
}
