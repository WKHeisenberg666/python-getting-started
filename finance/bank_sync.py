"""Pulls balances/transactions for Sparkasse and Revolut via an open-banking aggregator.

Neither Sparkasse nor Revolut hand out a plain personal API key, so this talks to the
GoCardless Bank Account Data API (formerly Nordigen), a PSD2 aggregator that covers both.
It needs three things that can't be fetched automatically and must be set up once by hand:

1. A free GoCardless Bank Account Data account -> GOCARDLESS_SECRET_ID / GOCARDLESS_SECRET_KEY.
2. A "requisition" per bank: an end-user consent + bank-login redirect flow. Run
   `python manage.py gocardless_connect_bank <institution_id>` to start it, complete the
   bank login in the browser, then put the resulting requisition id into
   GOCARDLESS_SPARKASSE_REQUISITION_ID / GOCARDLESS_REVOLUT_REQUISITION_ID.
3. Re-consent every ~90 days, since that's the PSD2-mandated maximum consent lifetime.

`BankConnector` is intentionally a small interface so a different aggregator (FinAPI, Tink, ...)
or direct FinTS access could be swapped in later without touching the sync command or models.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings

GOCARDLESS_BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"


@dataclass
class RemoteBalance:
    account_external_id: str
    balance: Decimal
    currency: str


@dataclass
class RemoteTransaction:
    account_external_id: str
    external_id: str
    booking_date: date
    amount: Decimal
    currency: str
    description: str


class BankConnector(ABC):
    """Interface a concrete aggregator/provider implements."""

    @abstractmethod
    def get_balances(self, requisition_id: str) -> list[RemoteBalance]:
        ...

    @abstractmethod
    def get_transactions(self, requisition_id: str) -> list[RemoteTransaction]:
        ...


class GoCardlessConnector(BankConnector):
    def __init__(self, secret_id: str, secret_key: str):
        if not secret_id or not secret_key:
            raise ValueError(
                "GOCARDLESS_SECRET_ID/GOCARDLESS_SECRET_KEY are not configured. "
                "See finance/bank_sync.py for setup steps."
            )
        self.secret_id = secret_id
        self.secret_key = secret_key
        self._access_token = None

    def get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        response = requests.post(
            f"{GOCARDLESS_BASE_URL}/token/new/",
            json={"secret_id": self.secret_id, "secret_key": self.secret_key},
            timeout=30,
        )
        response.raise_for_status()
        self._access_token = response.json()["access"]
        return self._access_token

    def _get(self, path: str) -> dict:
        response = requests.get(
            f"{GOCARDLESS_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _account_ids(self, requisition_id: str) -> list[str]:
        requisition = self._get(f"/requisitions/{requisition_id}/")
        return requisition.get("accounts", [])

    def get_balances(self, requisition_id: str) -> list[RemoteBalance]:
        results = []
        for account_id in self._account_ids(requisition_id):
            data = self._get(f"/accounts/{account_id}/balances/")
            for balance in data.get("balances", []):
                amount = balance["balanceAmount"]
                results.append(
                    RemoteBalance(
                        account_external_id=account_id,
                        balance=Decimal(amount["amount"]),
                        currency=amount["currency"],
                    )
                )
                break  # first balance entry (usually "interimAvailable") is enough
        return results

    def get_transactions(self, requisition_id: str) -> list[RemoteTransaction]:
        results = []
        for account_id in self._account_ids(requisition_id):
            data = self._get(f"/accounts/{account_id}/transactions/")
            booked = data.get("transactions", {}).get("booked", [])
            for tx in booked:
                amount = tx["transactionAmount"]
                external_id = tx.get("transactionId") or tx.get("internalTransactionId")
                if not external_id:
                    continue
                results.append(
                    RemoteTransaction(
                        account_external_id=account_id,
                        external_id=external_id,
                        booking_date=date.fromisoformat(tx["bookingDate"]),
                        amount=Decimal(amount["amount"]),
                        currency=amount["currency"],
                        description=(
                            tx.get("remittanceInformationUnstructured")
                            or tx.get("creditorName")
                            or tx.get("debtorName")
                            or ""
                        ),
                    )
                )
        return results


def get_connector() -> GoCardlessConnector:
    return GoCardlessConnector(settings.GOCARDLESS_SECRET_ID, settings.GOCARDLESS_SECRET_KEY)
