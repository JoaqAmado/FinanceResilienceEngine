"""Recent month-by-month history per account, for the app's "look back" step.

Reads marts.fact_account_month once (only the last N months of every account, ~27k rows) into
memory, so each lookup is instant. Values are the mart's own columns, unchanged.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

LOOK_BACK_MONTHS = 6

_COLUMNS = [
    "month", "money_in", "money_out", "net_cash_flow", "fixed_costs", "discretionary_spending",
    "household_bills", "insurance", "loan_payments", "bank_fees",
    "cash_withdrawals_genuine", "card_withdrawals", "transfers_out_other",
    "avg_daily_balance", "month_end_balance", "min_balance", "days_below_zero", "is_lean_month",
]


@lru_cache(maxsize=1)
def _recent_by_account() -> dict[int, list[dict[str, Any]]]:
    from tangerine.engine import ensure_warehouse
    from tangerine.pipeline import connect

    ensure_warehouse()
    con = connect(read_only=True)
    try:
        df = con.execute(
            f"select account_id, {', '.join(_COLUMNS)} from marts.fact_account_month "
            f"where months_from_end <= {LOOK_BACK_MONTHS} order by account_id, month"
        ).df()
    finally:
        con.close()
    out: dict[int, list[dict[str, Any]]] = {}
    for rec in df.to_dict("records"):
        acc = int(rec.pop("account_id"))
        rec["days_below_zero"] = int(rec["days_below_zero"])
        rec["is_lean_month"] = bool(rec["is_lean_month"])
        out.setdefault(acc, []).append(rec)
    return out


def recent_months(account_id: int) -> list[dict[str, Any]]:
    """The account's last LOOK_BACK_MONTHS months of data, oldest first (fewer if history is shorter)."""
    return [dict(r) for r in _recent_by_account().get(int(account_id), [])]
