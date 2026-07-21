from decimal import Decimal

from django.test import TestCase

from . import extraction, ingest
from .models import Debt, Document


class ExtractionParsingTests(TestCase):
    def test_parse_amount_picks_largest_eur_value(self):
        text = "Mahngebühr 5,00 EUR\nGesamtbetrag: 1.234,56 EUR"
        self.assertEqual(extraction.parse_amount(text), Decimal("1234.56"))

    def test_parse_due_date(self):
        text = "Bitte zahlen Sie bis zum 15.08.2026."
        self.assertEqual(extraction.parse_due_date(text).isoformat(), "2026-08-15")

    def test_parse_reference(self):
        text = "Aktenzeichen: AZ-2026-00042"
        self.assertEqual(extraction.parse_reference(text), "AZ-2026-00042")

    def test_guess_doc_type(self):
        self.assertEqual(extraction.guess_doc_type("brief.pdf"), Document.DocType.PDF)
        self.assertEqual(extraction.guess_doc_type("scan.jpg"), Document.DocType.IMAGE)
        self.assertEqual(extraction.guess_doc_type("liste.xlsx"), Document.DocType.EXCEL)


class IngestBytesTests(TestCase):
    def test_ingest_never_auto_creates_a_debt(self):
        # Heuristic amount/creditor guessing was removed after it produced wrong debts on
        # real, noisy OCR text - ingestion now only stores the Document + extracted text.
        content = b"%PDF fake content EUR 42,00 for testing"
        result = ingest.ingest_bytes(content, "test.txt", Document.Source.MANUAL_UPLOAD)
        self.assertTrue(result.created)
        self.assertFalse(result.duplicate)
        self.assertIsNone(result.debt)
        self.assertEqual(Debt.objects.count(), 0)

    def test_duplicate_file_is_not_reingested(self):
        content = b"same bytes"
        first = ingest.ingest_bytes(content, "a.txt", Document.Source.MANUAL_UPLOAD)
        second = ingest.ingest_bytes(content, "a-renamed.txt", Document.Source.MANUAL_UPLOAD)
        self.assertFalse(second.duplicate is False)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.document.id, second.document.id)
        self.assertEqual(Document.objects.count(), 1)

    def test_excel_overview_does_not_create_a_bogus_debt(self):
        import io

        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["FORDERUNGSÜBERSICHT 2026 – Marcel Peters"])
        sheet.append(["Gesamtsumme aller Forderungen", "209679,90 EUR"])
        buffer = io.BytesIO()
        workbook.save(buffer)

        result = ingest.ingest_bytes(buffer.getvalue(), "uebersicht.xlsx", Document.Source.MANUAL_UPLOAD)
        self.assertTrue(result.created)
        self.assertIsNone(result.debt)
        self.assertEqual(Debt.objects.count(), 0)


class DebtExcelSignalTests(TestCase):
    def test_creating_a_debt_appends_it_to_the_excel_export(self):
        import tempfile

        import openpyxl
        from django.test import override_settings

        from .models import Creditor

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_path = f"{tmp_dir}/schuldenliste.xlsx"
            with override_settings(DEBT_EXCEL_EXPORT_PATH=export_path):
                creditor = Creditor.objects.create(name="Test Inkasso GmbH")
                Debt.objects.create(creditor=creditor, amount=Decimal("99.90"))

            workbook = openpyxl.load_workbook(export_path)
            rows = list(workbook.active.iter_rows(values_only=True))
            self.assertEqual(rows[1][1], "Test Inkasso GmbH")
            self.assertEqual(rows[1][2], 99.9)


class DashboardViewTests(TestCase):
    def test_dashboard_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_upload_page_renders(self):
        response = self.client.get("/upload/")
        self.assertEqual(response.status_code, 200)
