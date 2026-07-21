from datetime import date, timedelta

from django.core.management.base import BaseCommand

from ...models import Account, Creditor, Debt


class Command(BaseCommand):
    help = "Populates the dashboard with sample creditors/debts/accounts (no real data)."

    def handle(self, *args, **options):
        creditors = [
            ("Inkasso Müller & Partner", "Restschuld Kreditkarte", 1450.00, 30),
            ("Finanzamt", "Einkommensteuer Nachzahlung", 620.50, 14),
            ("Amazon Kreditkarte", "Offener Saldo", 310.20, 21),
        ]
        for name, description, amount, due_in_days in creditors:
            creditor, _ = Creditor.objects.get_or_create(name=name)
            Debt.objects.get_or_create(
                creditor=creditor,
                description=description,
                defaults={
                    "amount": amount,
                    "due_date": date.today() + timedelta(days=due_in_days),
                    "status": Debt.Status.OPEN,
                },
            )

        accounts = [
            (Account.Provider.SPARKASSE, "Girokonto", "DE00 **** 1234", 842.17),
            (Account.Provider.REVOLUT, "Revolut EUR", "LT00 **** 5678", 210.55),
        ]
        for provider, name, iban_masked, balance in accounts:
            Account.objects.get_or_create(
                provider=provider,
                name=name,
                defaults={"iban_masked": iban_masked, "balance": balance},
            )

        self.stdout.write(self.style.SUCCESS("Demo-Daten angelegt."))
