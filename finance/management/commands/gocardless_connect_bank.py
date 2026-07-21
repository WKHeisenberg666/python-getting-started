"""One-time setup helper: starts the GoCardless bank-login (consent) flow for one bank.

PSD2 requires an interactive bank login for consent, so this can't be fully automated.
Run it once per bank, open the printed link, log in, then copy the requisition id it
printed into GOCARDLESS_SPARKASSE_REQUISITION_ID / GOCARDLESS_REVOLUT_REQUISITION_ID.

Example:
    python manage.py gocardless_connect_bank SPARKASSE_XXXXXXXX \\
        --redirect-uri https://example.com/bank-connected

Find the institution id for your local Sparkasse/Revolut via:
    GET https://bankaccountdata.gocardless.com/api/v2/institutions/?country=de
(requires the same secret_id/secret_key, see finance/bank_sync.py)
"""

import uuid

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...bank_sync import GOCARDLESS_BASE_URL, get_connector


class Command(BaseCommand):
    help = "Starts the GoCardless consent flow for a bank and prints the requisition id."

    def add_arguments(self, parser):
        parser.add_argument("institution_id", help="e.g. SPARKASSE_XXXXXXXX or REVOLUT_REVOGB21")
        parser.add_argument(
            "--redirect-uri",
            default="https://example.com/bank-connected",
            help="Where GoCardless sends the user back to after bank login.",
        )

    def handle(self, *args, **options):
        if not settings.GOCARDLESS_SECRET_ID or not settings.GOCARDLESS_SECRET_KEY:
            raise CommandError("Set GOCARDLESS_SECRET_ID/GOCARDLESS_SECRET_KEY first.")

        connector = get_connector()
        token = connector.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        agreement = requests.post(
            f"{GOCARDLESS_BASE_URL}/agreements/enduser/",
            headers=headers,
            json={
                "institution_id": options["institution_id"],
                "max_historical_days": 180,
                "access_valid_for_days": 90,
                "access_scope": ["balances", "details", "transactions"],
            },
            timeout=30,
        )
        agreement.raise_for_status()

        requisition = requests.post(
            f"{GOCARDLESS_BASE_URL}/requisitions/",
            headers=headers,
            json={
                "redirect": options["redirect_uri"],
                "institution_id": options["institution_id"],
                "reference": str(uuid.uuid4()),
                "agreement": agreement.json()["id"],
                "user_language": "DE",
            },
            timeout=30,
        )
        requisition.raise_for_status()
        data = requisition.json()

        self.stdout.write("1. Bank-Login hier abschließen:")
        self.stdout.write(f"   {data['link']}")
        self.stdout.write("2. Danach diese Requisition-ID in die Umgebungsvariable eintragen:")
        self.stdout.write(self.style.SUCCESS(f"   {data['id']}"))
