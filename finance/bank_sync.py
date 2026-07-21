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
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

GOCARDLESS_BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"


class BankSyncError(Exception):
    pass


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


@dataclass
class BankSyncResult:
    synced_account_names: list = field(default_factory=list)
    new_transaction_count: int = 0


def run_bank_sync() -> BankSyncResult:
    """Pulls balances + transactions for every bank with a configured requisition. Shared by
    the `sync_bank_accounts` management command and the dashboard's "Jetzt abgleichen" button."""
    from .models import Account, BankTransaction

    provider_requisition_settings = {
        Account.Provider.SPARKASSE: "GOCARDLESS_SPARKASSE_REQUISITION_ID",
        Account.Provider.REVOLUT: "GOCARDLESS_REVOLUT_REQUISITION_ID",
    }
    configured = {
        provider: getattr(settings, setting_name)
        for provider, setting_name in provider_requisition_settings.items()
        if getattr(settings, setting_name)
    }
    if not configured:
        raise BankSyncError(
            "Keine Requisition-IDs konfiguriert. Erst `python manage.py gocardless_connect_bank "
            "<institution_id>` ausführen und GOCARDLESS_SPARKASSE_REQUISITION_ID / "
            "GOCARDLESS_REVOLUT_REQUISITION_ID setzen (siehe README)."
        )

    try:
        connector = get_connector()
        result = BankSyncResult()

        for provider, requisition_id in configured.items():
            for remote_balance in connector.get_balances(requisition_id):
                account, _ = Account.objects.update_or_create(
                    external_account_id=remote_balance.account_external_id,
                    defaults={
                        "provider": provider,
                        "name": remote_balance.account_external_id[:8],
                        "currency": remote_balance.currency,
                        "balance": remote_balance.balance,
                        "last_synced_at": timezone.now(),
                    },
                )
                result.synced_account_names.append(str(account))

            for remote_tx in connector.get_transactions(requisition_id):
                account = Account.objects.filter(
                    external_account_id=remote_tx.account_external_id
                ).first()
                if not account:
                    continue
                _, created = BankTransaction.objects.update_or_create(
                    external_id=remote_tx.external_id,
                    defaults={
                        "account": account,
                        "booking_date": remote_tx.booking_date,
                        "amount": remote_tx.amount,
                        "currency": remote_tx.currency,
                        "description": remote_tx.description,
                    },
                )
                result.new_transaction_count += created
    except BankSyncError:
        raise
    except Exception as exc:
        raise BankSyncError(f"Bank-Sync fehlgeschlagen: {exc}") from exc

    return result
