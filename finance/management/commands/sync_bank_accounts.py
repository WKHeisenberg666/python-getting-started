from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...bank_sync import get_connector
from ...models import Account, BankTransaction

PROVIDER_REQUISITIONS = {
    Account.Provider.SPARKASSE: "GOCARDLESS_SPARKASSE_REQUISITION_ID",
    Account.Provider.REVOLUT: "GOCARDLESS_REVOLUT_REQUISITION_ID",
}


class Command(BaseCommand):
    help = "Pulls balances and transactions for Sparkasse/Revolut via the GoCardless connector."

    def handle(self, *args, **options):
        configured = {
            provider: getattr(settings, setting_name)
            for provider, setting_name in PROVIDER_REQUISITIONS.items()
            if getattr(settings, setting_name)
        }
        if not configured:
            raise CommandError(
                "No requisition IDs configured. Run `gocardless_connect_bank` first and set "
                "GOCARDLESS_SPARKASSE_REQUISITION_ID / GOCARDLESS_REVOLUT_REQUISITION_ID."
            )

        connector = get_connector()

        for provider, requisition_id in configured.items():
            self.stdout.write(f"Syncing {provider}...")
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
                self.stdout.write(f"  Saldo {account}: {account.balance} {account.currency}")

            new_transactions = 0
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
                new_transactions += created
            self.stdout.write(f"  {new_transactions} neue Transaktion(en)")

        self.stdout.write(self.style.SUCCESS("Bank-Sync abgeschlossen."))
