from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...bank_sync import BankSyncError, run_bank_sync
from ...reconciliation import reconcile_debts_with_transactions


class Command(BaseCommand):
    help = (
        "Pulls balances/transactions for Sparkasse/Revolut via GoCardless, then matches "
        "transactions against the Excel debt list (paid/installment detection + fixed costs)."
    )

    def handle(self, *args, **options):
        try:
            result = run_bank_sync()
        except BankSyncError as exc:
            raise CommandError(str(exc)) from exc

        for name in result.synced_account_names:
            self.stdout.write(f"Saldo synchronisiert: {name}")
        self.stdout.write(f"{result.new_transaction_count} neue Transaktion(en)")

        summary = reconcile_debts_with_transactions(settings.DEBT_EXCEL_EXPORT_PATH)
        self.stdout.write(f"{summary['matched_debts']} Schulden mit Zahlungen abgeglichen")
        for item in summary["fixed_costs"]:
            self.stdout.write(
                f"  Fixkosten erkannt: {item['description']} – {item['amount']} EUR "
                f"({item['months_seen']}x gesehen)"
            )

        self.stdout.write(self.style.SUCCESS("Bank-Sync + Abgleich abgeschlossen."))
