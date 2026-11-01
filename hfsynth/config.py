"""Generator configuration. Every volume/rate is a parameter so the starter and
full datasets are produced by exactly the same code path."""
from dataclasses import dataclass


@dataclass
class Config:
    seed: int = 20261022
    users: int = 1000
    txns: int = 500_000          # exact total ledger rows (incl. injected edge-case rows)
    year: int = 2026
    out: str = "output"
    currency: str = "USD"

    # --- behavioural rates -------------------------------------------------
    unresolved_rate: float = 0.06        # share of purchases whose descriptor is not in the alias table
    refund_rate: float = 0.03            # share of purchases that get a (correct) refund record

    # --- labelled edge cases (fractions of `txns` unless stated) ----------
    rate_transfer_dup: float = 0.002     # transfer also posted as a spending row
    rate_refund_misclassified: float = 0.0015  # refund credit posted as txn_type=PURCHASE
    rate_tz_boundary: float = 0.002      # purchases forced to the last local evening of a month
    skip_rate: float = 0.02              # share of scheduled (non-salary/rent) occurrences skipped
    budget_mismatch_user_share: float = 0.04   # share of users with a legacy budget category code

    def validate(self):
        if self.users < 20:
            raise ValueError("users must be >= 20")
        if self.txns < self.users * 200:
            raise ValueError(
                f"txns={self.txns} is too small for users={self.users}: the recurring "
                f"schedule alone needs roughly 190-200 rows per user; use at least "
                f"{self.users * 300} (about 300 per user)."
            )
