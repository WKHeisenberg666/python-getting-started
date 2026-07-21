"""Matches bank transactions against Excel debt rows to detect payments/installment plans,
and finds recurring transactions that look like monthly fixed costs.

Matching is a simple normalized-substring match between a debt's creditor name and a
transaction's description - good enough to flag likely matches, not a guarantee. Nothing here
overwrites a row's "Vorschlag (KI)" status; only confirmed debts are touched.
"""

import re
from collections import defaultdict
from decimal import Decimal

from . import excel_store
from .models import BankTransaction

_LEGAL_SUFFIX_RE = re.compile(r"\b(gmbh|ag|kg|e\.?v\.?|se|ohg|co\.?\s*kg)\b", re.IGNORECASE)


def _normalize(name: str) -> str:
    name = _LEGAL_SUFFIX_RE.sub("", name or "")
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def reconcile_debts_with_transactions(excel_path) -> dict:
    """Updates paid/open amounts and status on confirmed Excel rows based on matching
    transactions. Returns a summary dict with the count of debts touched."""
    transactions = list(BankTransaction.objects.all())
    rows = excel_store.read_rows(excel_path)

    matched_count = 0
    for row in rows:
        if row["status"] in (excel_store.STATUS_PROPOSAL, excel_store.STATUS_SETTLED):
            continue
        normalized_creditor = _normalize(row["creditor_name"])
        if not normalized_creditor:
            continue

        matches = [
            tx
            for tx in transactions
            if tx.amount < 0 and normalized_creditor in _normalize(tx.description)
        ]
        if not matches:
            continue

        paid_total = sum((-tx.amount for tx in matches), Decimal("0"))
        open_amount = max(row["amount"] - paid_total, Decimal("0"))

        if open_amount <= 0:
            new_status = excel_store.STATUS_PAID
        elif len(matches) > 1:
            new_status = excel_store.STATUS_INSTALLMENT
        else:
            new_status = row["status"]

        excel_store.update_row(
            excel_path,
            row["id"],
            paid_amount=float(paid_total),
            open_amount=float(open_amount),
            status=new_status,
        )
        matched_count += 1

    return {"matched_debts": matched_count, "fixed_costs": detect_fixed_costs(transactions)}


def detect_fixed_costs(transactions=None, min_months: int = 2) -> list[dict]:
    """Groups outgoing transactions by (normalized description, amount); ones recurring across
    at least `min_months` distinct calendar months are treated as a monthly fixed cost."""
    if transactions is None:
        transactions = list(BankTransaction.objects.all())

    groups = defaultdict(list)
    for tx in transactions:
        if tx.amount >= 0:
            continue
        groups[(_normalize(tx.description), tx.amount)].append(tx)

    fixed_costs = []
    for (_, amount), txs in groups.items():
        months = {(tx.booking_date.year, tx.booking_date.month) for tx in txs}
        if len(months) >= min_months:
            fixed_costs.append(
                {
                    "description": txs[0].description,
                    "amount": -amount,
                    "months_seen": len(months),
                }
            )
    fixed_costs.sort(key=lambda item: item["amount"], reverse=True)
    return fixed_costs


def monthly_fixed_costs_total(transactions=None) -> Decimal:
    return sum((item["amount"] for item in detect_fixed_costs(transactions)), Decimal("0"))
